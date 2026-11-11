import io
import os
import subprocess
import threading
from unittest.mock import patch, MagicMock
import pytest

from app.core.config import settings
from app.services.sandbox_service import (
    execute_code,
    extract_java_class_name,
    check_docker_available,
    resolve_sandbox_image,
    STREAM_CHUNK_SIZE,
    MARKER_STREAM_HEADROOM_BYTES,
)


# ==============================================================================
# TEST HELPERS FOR REALISTIC BINARY STREAMING MOCKS
# ==============================================================================

class _CapturingStdin:
    """Thread-safe pipe sink capturing bytes written to container stdin."""

    def __init__(self):
        self.buffer = bytearray()
        self.closed = False

    def write(self, data: bytes) -> int:
        if self.closed:
            raise BrokenPipeError("stdin closed")
        self.buffer.extend(data)
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _ControllablePipe:
    """
    Fake stdout/stderr binary pipe that yields fixed chunks first and can block
    until killed to test mid-stream overflow termination and timeout behavior.
    """

    def __init__(self, initial_bytes: bytes = b"", infinite_chunk: bytes = b"", block_until_killed: bool = False):
        self._buf = io.BytesIO(initial_bytes)
        self._infinite_chunk = infinite_chunk
        self._block_until_killed = block_until_killed
        self.killed_event = threading.Event()
        self.closed = False
        self.bytes_read = 0

    def read(self, n: int = -1) -> bytes:
        if self.closed:
            return b""
        data = self._buf.read(n)
        if data:
            self.bytes_read += len(data)
            return data
        if self._infinite_chunk:
            if self.killed_event.is_set():
                return b""
            chunk = self._infinite_chunk[:n] if n > 0 else self._infinite_chunk
            self.bytes_read += len(chunk)
            return chunk
        if self._block_until_killed:
            self.killed_event.wait(timeout=15)
        return b""

    def close(self) -> None:
        self.closed = True


def _make_streaming_proc(
    stdout_bytes: bytes = b"",
    stderr_bytes: bytes = b"",
    returncode: int = 0,
    infinite_stdout_chunk: bytes = b"",
    infinite_stderr_chunk: bytes = b"",
    block_until_killed: bool = False,
):
    """Build a realistic Popen mock compatible with binary streaming reader threads."""
    killed_event = threading.Event()
    stdout_pipe = _ControllablePipe(
        initial_bytes=stdout_bytes,
        infinite_chunk=infinite_stdout_chunk,
        block_until_killed=block_until_killed,
    )
    stderr_pipe = _ControllablePipe(
        initial_bytes=stderr_bytes,
        infinite_chunk=infinite_stderr_chunk,
        block_until_killed=block_until_killed,
    )
    stdin_pipe = _CapturingStdin()

    proc = MagicMock()
    proc.stdin = stdin_pipe
    proc.stdout = stdout_pipe
    proc.stderr = stderr_pipe
    proc.returncode = None

    def _poll():
        return proc.returncode

    def _kill():
        proc.returncode = 137
        stdout_pipe.killed_event.set()
        stderr_pipe.killed_event.set()
        killed_event.set()

    def _wait():
        if block_until_killed or infinite_stdout_chunk or infinite_stderr_chunk:
            killed_event.wait(timeout=15)
            return proc.returncode if proc.returncode is not None else 137
        proc.returncode = returncode
        return returncode

    proc.poll.side_effect = _poll
    proc.kill.side_effect = _kill
    proc.wait.side_effect = _wait
    return proc


def _extract_markers_from_cmd(cmd: list[str]) -> dict[str, str]:
    """Parse randomized per-run markers out of the `sh -c` runner script in argv."""
    script = cmd[-1]
    import re
    start = re.search(r"<<<CP_START:[a-f0-9]+>>>", script)
    dur = re.search(r"<<<CP_DUR:[a-f0-9]+:", script)
    cerr = re.search(r"<<<CP_CERR:[a-f0-9]+>>>", script)
    cto = re.search(r"<<<CP_CTO:[a-f0-9]+>>>", script)
    return {
        "start": start.group(0) if start else "",
        "dur": dur.group(0) if dur else "",
        "cerr": cerr.group(0) if cerr else "",
        "cto": cto.group(0) if cto else "",
    }


# ==============================================================================
# 1. INPUT, STDIN, AND TIMEOUT VALIDATION TESTS (NO DOCKER DAEMON REQUIRED)
# ==============================================================================

def test_empty_code_returns_validation_error():
    res = execute_code(code="", language="python")
    assert res.status == "validation_error"
    assert "cannot be empty" in res.stderr
    assert res.exit_code == 1


def test_whitespace_only_code_returns_validation_error():
    res = execute_code(code="   \n\t  ", language="python")
    assert res.status == "validation_error"
    assert "cannot be empty" in res.stderr


def test_unsupported_language_returns_validation_error():
    res = execute_code(code="print('hi')", language="rust")  # type: ignore
    assert res.status == "validation_error"
    assert "Unsupported language" in res.stderr


def test_oversized_source_code_returns_validation_error():
    oversized = "a = 1\n" * 20000  # > 50 KB
    res = execute_code(code=oversized, language="python")
    assert res.status == "validation_error"
    assert "exceeds maximum permitted size" in res.stderr


@patch("subprocess.Popen")
def test_oversized_stdin_rejected_before_docker(mock_popen):
    oversized_stdin = "A" * (settings.SANDBOX_MAX_STDIN_SIZE_BYTES + 1)
    res = execute_code(code="print('ok')", language="python", stdin=oversized_stdin)
    assert res.status == "validation_error"
    assert "Standard input exceeds maximum permitted size" in res.stderr
    assert res.exit_code == 1
    mock_popen.assert_not_called()


@patch("subprocess.Popen")
def test_invalid_and_excessive_timeout_rejected_before_docker(mock_popen):
    for bad_timeout in (0, -5, settings.SANDBOX_MAX_TIMEOUT_SECONDS + 1, True):
        res = execute_code(code="print('ok')", language="python", custom_timeout=bad_timeout)  # type: ignore
        assert res.status == "validation_error"
        assert "Execution timeout" in res.stderr
        assert res.exit_code == 1

    for bad_compile in (0, -1, settings.SANDBOX_MAX_COMPILE_TIMEOUT_SECONDS + 1, False):
        res = execute_code(code="int main(){return 0;}", language="cpp", custom_compile_timeout=bad_compile)  # type: ignore
        assert res.status == "validation_error"
        assert "Compilation timeout" in res.stderr
        assert res.exit_code == 1

    mock_popen.assert_not_called()


# ==============================================================================
# 2. JAVA CLASS EXTRACTION & IMAGE DIGEST TESTS
# ==============================================================================

def test_extract_java_class_name_variations():
    assert extract_java_class_name("public class Solution { public static void main... }") == "Solution"
    assert extract_java_class_name("class MyAlg {\n public static void main... }") == "MyAlg"
    assert extract_java_class_name("// No class defined\n int a = 5;") == "Main"
    assert extract_java_class_name("public class BinaryTree_Search123 { }") == "BinaryTree_Search123"
    # String literals, URLs with //, text blocks, and comments containing fake class declarations
    tricky_java = '''
    /* public class FakeCommentClass {} */
    class Helper {
        String s1 = "public class FakeStringClass {}";
        String url = "https://example.com // public class FakeAfterSlash {}";
        String block = """
            public class FakeTextBlockClass {}
        """;
    }
    public final class RealSolution {
        public static void main(String[] args) {}
    }
    '''
    assert extract_java_class_name(tricky_java) == "RealSolution"


def test_resolve_sandbox_image_uses_immutable_digest():
    ref = resolve_sandbox_image("python:3.12-slim", settings.SANDBOX_DOCKER_PYTHON_DIGEST)
    assert ref.startswith("python:3.12-slim@sha256:")
    assert len(settings.SANDBOX_DOCKER_PYTHON_DIGEST) == len("sha256:") + 64


# ==============================================================================
# 3. SECURITY FLAGS & PRIVATE SOURCE TRANSFER TESTS
# ==============================================================================

@patch("subprocess.Popen")
@patch("subprocess.run")
def test_source_code_not_in_docker_env_or_cli_args(mock_run, mock_popen):
    """Ensure source code and stdin are streamed via stdin pipe, never in env vars or argv."""
    secret_code = "SECRET_TOKEN_XYZ = 'do_not_leak_in_env_or_argv'\nprint(SECRET_TOKEN_XYZ)"
    secret_stdin = "SENSITIVE_INPUT_123"

    def _popen_side_effect(cmd, **kwargs):
        m = _extract_markers_from_cmd(cmd)
        return _make_streaming_proc(
            stdout_bytes=f"{m['start']}\nOK\n{m['dur']}5000000>>>".encode("utf-8"),
            returncode=0,
        )

    mock_popen.side_effect = _popen_side_effect

    execute_code(code=secret_code, language="python", stdin=secret_stdin)

    mock_popen.assert_called_once()
    cmd = mock_popen.call_args[0][0]
    kwargs = mock_popen.call_args[1]

    # Source must NOT appear in env flags or any CLI arg
    assert "-e" not in cmd and "--env" not in cmd
    joined_cmd = " ".join(cmd)
    assert "CODE_B64" not in joined_cmd
    assert "SECRET_TOKEN_XYZ" not in joined_cmd
    assert "do_not_leak_in_env_or_argv" not in joined_cmd
    assert secret_stdin not in joined_cmd

    # Base64 of secret_code must also not appear in argv
    import base64
    b64_secret = base64.b64encode(secret_code.encode("utf-8")).decode("ascii")
    assert b64_secret not in joined_cmd

    # Verify container hardening flags & binary streaming mode
    assert kwargs.get("shell") is not True
    assert "--network" in cmd and cmd[cmd.index("--network") + 1] == "none"
    assert "--read-only" in cmd
    assert "--cap-drop" in cmd and cmd[cmd.index("--cap-drop") + 1] == "ALL"
    assert "--security-opt" in cmd and cmd[cmd.index("--security-opt") + 1] == "no-new-privileges"
    assert "--user" in cmd and cmd[cmd.index("--user") + 1] == "1000:1000"
    assert "--cpus" in cmd and cmd[cmd.index("--cpus") + 1] == "0.5"
    assert "--pids-limit" in cmd and cmd[cmd.index("--pids-limit") + 1] == "64"
    assert "--stop-timeout" in cmd
    assert "--pull" in cmd
    assert "--rm" in cmd
    assert "-v" not in cmd and "--volume" not in cmd

    # Verify raw payload was streamed over stdin (code_bytes + stdin_bytes)
    captured_stdin = []
    def _popen_capture(cmd_inner, **kw):
        m = _extract_markers_from_cmd(cmd_inner)
        p = _make_streaming_proc(
            stdout_bytes=f"{m['start']}\nOK\n{m['dur']}5000000>>>".encode("utf-8"),
        )
        captured_stdin.append(p.stdin)
        return p

    mock_popen.side_effect = _popen_capture
    execute_code(code=secret_code, language="python", stdin=secret_stdin)
    assert bytes(captured_stdin[0].buffer) == secret_code.encode("utf-8") + secret_stdin.encode("utf-8")
    assert captured_stdin[0].closed is True


# ==============================================================================
# 4. MOCKED EXECUTION LIFECYCLE TESTS
# ==============================================================================

@patch("subprocess.Popen")
@patch("subprocess.run")
def test_python_execution_success_mocked(mock_run, mock_popen):
    def _popen_side_effect(cmd, **kwargs):
        m = _extract_markers_from_cmd(cmd)
        return _make_streaming_proc(
            stdout_bytes=f"{m['start']}\nHello from Python!\n{m['dur']}12000000>>>\n".encode("utf-8"),
            returncode=0,
        )
    mock_popen.side_effect = _popen_side_effect

    res = execute_code(code="print('Hello from Python!')", language="python")
    assert res.status == "success"
    assert res.stdout == "Hello from Python!\n"
    assert res.stderr == ""
    assert res.exit_code == 0
    assert res.duration_ms == 12.0
    assert res.truncated is False


@patch("subprocess.Popen")
@patch("subprocess.run")
def test_cpp_compilation_and_execution_success_mocked(mock_run, mock_popen):
    def _popen_side_effect(cmd, **kwargs):
        m = _extract_markers_from_cmd(cmd)
        return _make_streaming_proc(
            stdout_bytes=f"{m['start']}\nResult: 42\n{m['dur']}2500000>>>\n".encode("utf-8"),
            returncode=0,
        )
    mock_popen.side_effect = _popen_side_effect

    code = "#include <iostream>\nint main() { std::cout << 'Result: 42' << std::endl; return 0; }"
    res = execute_code(code=code, language="cpp")

    assert res.status == "success"
    assert res.stdout == "Result: 42\n"
    assert res.exit_code == 0
    assert res.duration_ms == 2.5
    assert res.compilation_error is None


@patch("subprocess.Popen")
@patch("subprocess.run")
def test_java_compilation_and_execution_success_mocked(mock_run, mock_popen):
    def _popen_side_effect(cmd, **kwargs):
        m = _extract_markers_from_cmd(cmd)
        return _make_streaming_proc(
            stdout_bytes=f"{m['start']}\nJava Out: 100\n{m['dur']}45000000>>>\n".encode("utf-8"),
            returncode=0,
        )
    mock_popen.side_effect = _popen_side_effect

    code = "public class Solution { public static void main(String[] args) { System.out.println('Java Out: 100'); } }"
    res = execute_code(code=code, language="java")

    assert res.status == "success"
    assert res.stdout == "Java Out: 100\n"
    assert res.exit_code == 0
    assert res.duration_ms == 45.0


@patch("subprocess.Popen")
@patch("subprocess.run")
def test_user_output_containing_marker_like_strings(mock_run, mock_popen):
    """Static or spoofed marker strings in user output must not corrupt status or truncate output."""
    spoofed_text = (
        "<<<CODEPILOT_COMPILE_ERROR>>>\n"
        "<<<CODEPILOT_COMPILE_TIMEOUT>>>\n"
        "<<<CODEPILOT_EXEC_START>>>\n"
        "<<<CODEPILOT_EXEC_DURATION_NS:999>>>\n"
        "Actual Output Line\n"
    )

    def _popen_side_effect(cmd, **kwargs):
        m = _extract_markers_from_cmd(cmd)
        return _make_streaming_proc(
            stdout_bytes=f"{m['start']}\n{spoofed_text}{m['dur']}7000000>>>\n".encode("utf-8"),
            returncode=0,
        )
    mock_popen.side_effect = _popen_side_effect

    res = execute_code(code="print('spoofed')", language="python")
    assert res.status == "success"
    assert res.stdout == spoofed_text
    assert res.duration_ms == 7.0


# ==============================================================================
# 5. BOUNDED STREAMING, OVERFLOW, TIMEOUT, & CLEANUP TESTS
# ==============================================================================

@patch("subprocess.Popen")
@patch("subprocess.run")
def test_compilation_failure_mocked(mock_run, mock_popen):
    def _popen_side_effect(cmd, **kwargs):
        m = _extract_markers_from_cmd(cmd)
        return _make_streaming_proc(
            stdout_bytes=(m["cerr"] + "\nmain.cpp:3:1: error: expected ';' before '}' token\n").encode("utf-8"),
            returncode=42,
        )
    mock_popen.side_effect = _popen_side_effect

    res = execute_code(code="int main() { missing_semicolon }", language="cpp")

    assert res.status == "compilation_error"
    assert res.stdout == ""
    assert res.compilation_error is not None
    assert "expected ';'" in res.compilation_error
    assert res.exit_code == 42


@patch("subprocess.Popen")
@patch("subprocess.run")
def test_compilation_timeout_mocked(mock_run, mock_popen):
    def _popen_side_effect(cmd, **kwargs):
        m = _extract_markers_from_cmd(cmd)
        return _make_streaming_proc(
            stdout_bytes=f"{m['cto']}\nCompilation timed out after 10 seconds.\n".encode("utf-8"),
            returncode=124,
        )
    mock_popen.side_effect = _popen_side_effect

    res = execute_code(code="int main() {}", language="cpp")

    assert res.status == "compilation_timeout"
    assert res.stdout == ""
    assert "Compilation timed out" in str(res.compilation_error)
    assert res.exit_code == 124


@patch("subprocess.Popen")
@patch("subprocess.run")
def test_runtime_failure_mocked(mock_run, mock_popen):
    def _popen_side_effect(cmd, **kwargs):
        m = _extract_markers_from_cmd(cmd)
        return _make_streaming_proc(
            stdout_bytes=f"{m['start']}\n".encode("utf-8"),
            stderr_bytes=b"Traceback (most recent call last):\nZeroDivisionError: division by zero\n",
            returncode=1,
        )
    mock_popen.side_effect = _popen_side_effect

    res = execute_code(code="1 / 0", language="python")

    assert res.status == "runtime_error"
    assert res.exit_code == 1
    assert "ZeroDivisionError" in res.stderr


@patch("subprocess.Popen")
@patch("subprocess.run")
def test_infinite_stdout_stopped_during_streaming_with_bounded_memory_and_cleanup(mock_run, mock_popen):
    """Verify infinite stdout stops reading near 64 KB cap, kills container mid-stream, and cleans up."""
    procs = []

    def _popen_side_effect(cmd, **kwargs):
        m = _extract_markers_from_cmd(cmd)
        proc = _make_streaming_proc(
            stdout_bytes=f"{m['start']}\n".encode("utf-8"),
            infinite_stdout_chunk=b"X" * STREAM_CHUNK_SIZE,
        )
        procs.append(proc)
        return proc

    mock_popen.side_effect = _popen_side_effect

    res = execute_code(code="while True: print('X' * 4096)", language="python")

    assert res.status == "output_limit_exceeded"
    assert res.truncated is True
    assert "[Output truncated: exceeded 64 KB limit]" in res.stdout

    # Prove streaming stopped shortly after 64 KB cap without unbounded accumulation
    proc = procs[0]
    expected_cap = settings.SANDBOX_MAX_OUTPUT_SIZE_BYTES + MARKER_STREAM_HEADROOM_BYTES
    assert proc.stdout.bytes_read <= expected_cap + STREAM_CHUNK_SIZE
    assert len(res.stdout.encode("utf-8")) <= 66000

    # Prove container was force-removed on overflow
    rm_calls = [c[0][0] for c in mock_run.call_args_list if c[0][0][:3] == ["docker", "rm", "-f"]]
    assert len(rm_calls) >= 1
    assert rm_calls[0][3].startswith("codepilot-sbx-")


@patch("subprocess.Popen")
@patch("subprocess.run")
def test_infinite_stderr_stopped_during_streaming_with_bounded_memory(mock_run, mock_popen):
    """Verify infinite stderr stops reading at 64 KB cap and returns output_limit_exceeded."""
    procs = []

    def _popen_side_effect(cmd, **kwargs):
        m = _extract_markers_from_cmd(cmd)
        proc = _make_streaming_proc(
            stdout_bytes=f"{m['start']}\n".encode("utf-8"),
            infinite_stderr_chunk=b"E" * STREAM_CHUNK_SIZE,
        )
        procs.append(proc)
        return proc

    mock_popen.side_effect = _popen_side_effect

    res = execute_code(code="import sys\nwhile True: sys.stderr.write('E' * 4096)", language="python")

    assert res.status == "output_limit_exceeded"
    assert res.truncated is True
    assert "[Error output truncated: exceeded 64 KB limit]" in res.stderr

    proc = procs[0]
    assert proc.stderr.bytes_read <= settings.SANDBOX_MAX_OUTPUT_SIZE_BYTES + STREAM_CHUNK_SIZE
    assert len(res.stderr.encode("utf-8")) <= 66000


@patch("subprocess.Popen")
@patch("subprocess.run")
def test_timeout_triggers_container_cleanup(mock_run, mock_popen, monkeypatch):
    """Verify host timeout kills running container and invokes docker rm -f cleanup."""
    monkeypatch.setattr("app.services.sandbox_service.HOST_TIMEOUT_BUFFER_SECONDS", 0)

    procs = []

    def _popen_side_effect(cmd, **kwargs):
        proc = _make_streaming_proc(block_until_killed=True)
        procs.append(proc)
        return proc

    mock_popen.side_effect = _popen_side_effect

    res = execute_code(code="while True: pass", language="python", custom_timeout=1)

    assert res.status == "timeout"
    assert "Execution timed out" in res.stderr
    assert res.exit_code == 124
    procs[0].kill.assert_called()

    rm_calls = [c[0][0] for c in mock_run.call_args_list if c[0][0][:3] == ["docker", "rm", "-f"]]
    assert len(rm_calls) >= 1
    assert rm_calls[0][3].startswith("codepilot-sbx-")


# ==============================================================================
# 6. DOCKER INFRASTRUCTURE & EXCEPTION CLEANUP TESTS
# ==============================================================================

@patch("subprocess.Popen")
@patch("subprocess.run")
def test_docker_cli_missing_raises_infrastructure_error(mock_run, mock_popen):
    mock_popen.side_effect = FileNotFoundError("No such file or directory: 'docker'")
    res = execute_code(code="print('test')", language="python")

    assert res.status == "infrastructure_error"
    assert "not installed" in res.stderr


@patch("subprocess.Popen")
@patch("subprocess.run")
def test_docker_daemon_and_image_errors_classified(mock_run, mock_popen):
    mock_popen.return_value = _make_streaming_proc(
        stderr_bytes=b"Cannot connect to the Docker daemon at npipe:////./pipe/docker_engine.",
        returncode=125,
    )
    res_daemon = execute_code(code="print('test')", language="python")
    assert res_daemon.status == "infrastructure_error"
    assert "Docker daemon is not running or unreachable" in res_daemon.stderr
    assert "npipe://" not in res_daemon.stderr
    rm_calls = [c[0][0] for c in mock_run.call_args_list if c[0][0][:3] == ["docker", "rm", "-f"]]
    assert len(rm_calls) >= 1

    mock_run.reset_mock()
    mock_popen.return_value = _make_streaming_proc(
        stderr_bytes=b"Unable to find image 'python:3.12-slim' locally",
        returncode=125,
    )
    res_image = execute_code(code="print('test')", language="python")
    assert res_image.status == "infrastructure_error"
    assert "not available locally" in res_image.stderr
    rm_calls = [c[0][0] for c in mock_run.call_args_list if c[0][0][:3] == ["docker", "rm", "-f"]]
    assert len(rm_calls) >= 1


@patch("subprocess.Popen")
@patch("subprocess.run")
def test_unrecognized_pre_start_docker_error_classified_as_infrastructure_with_cleanup(mock_run, mock_popen, caplog):
    """Unrecognized CLI/OCI/cgroup/seccomp/AppArmor errors before markers must classify as infrastructure_error."""
    raw_host_err = b"cgroup2 mkdir /sys/fs/cgroup/host-secret-tenant: apparmor seccomp denied\n"
    mock_popen.return_value = _make_streaming_proc(
        stdout_bytes=b"",
        stderr_bytes=raw_host_err,
        returncode=126,
    )

    with caplog.at_level("ERROR", logger="app.services.sandbox_service"):
        res = execute_code(code="SECRET_CODE = 'do_not_log'\nprint(SECRET_CODE)", language="python")

    assert res.status == "infrastructure_error"
    assert res.stdout == ""
    assert "apparmor" not in res.stderr.lower()
    assert "host-secret-tenant" not in res.stderr
    assert "/sys/fs/cgroup" not in res.stderr

    # Diagnostic detail preserved server-side without exposing user source code
    assert any(
        "Sandbox pre-start failure" in rec.message
        and "host-secret-tenant" in rec.message
        and "do_not_log" not in rec.message
        for rec in caplog.records
    )

    # Container cleanup invoked after pre-start failure
    rm_calls = [c[0][0] for c in mock_run.call_args_list if c[0][0][:3] == ["docker", "rm", "-f"]]
    assert len(rm_calls) >= 1
    assert rm_calls[0][3].startswith("codepilot-sbx-")


@patch("subprocess.Popen")
@patch("subprocess.run")
def test_post_marker_runtime_error_not_misclassified_as_infrastructure(mock_run, mock_popen):
    """Once markers.start or compile marker is emitted, stderr phrases must not become infrastructure_error."""
    def _popen_runtime(cmd, **kwargs):
        m = _extract_markers_from_cmd(cmd)
        return _make_streaming_proc(
            stdout_bytes=f"{m['start']}\n".encode("utf-8"),
            stderr_bytes=b"ValueError: unable to find image or oci runtime in user string\n",
            returncode=1,
        )

    mock_popen.side_effect = _popen_runtime
    res = execute_code(code="raise ValueError('oci runtime')", language="python")
    assert res.status == "runtime_error"
    assert "oci runtime" in res.stderr
    assert res.exit_code == 1


@patch("subprocess.Popen")
@patch("subprocess.run")
def test_cleanup_always_invoked_on_unexpected_exception(mock_run, mock_popen, monkeypatch):
    """Ensure docker rm -f <container> and proc.kill() run even if streaming raises."""
    monkeypatch.setattr("app.services.sandbox_service.HOST_TIMEOUT_BUFFER_SECONDS", 0)
    proc = _make_streaming_proc(block_until_killed=True)
    mock_popen.return_value = proc

    with patch("threading.Thread.join", side_effect=RuntimeError("Unexpected thread join failure")):
        res = execute_code(code="print('crash')", language="python", custom_timeout=1)

    assert res.status == "infrastructure_error"
    proc.kill.assert_called()
    rm_calls = [c[0][0] for c in mock_run.call_args_list if c[0][0][:3] == ["docker", "rm", "-f"]]
    assert len(rm_calls) >= 1
    assert rm_calls[0][3].startswith("codepilot-sbx-")


# ==============================================================================
# 7. OPT-IN REAL DOCKER E2E INTEGRATION TESTS
# ==============================================================================

IS_DOCKER_AVAILABLE, DOCKER_VERSION = check_docker_available()
RUN_REAL_DOCKER = os.getenv("RUN_REAL_DOCKER_SANDBOX_TESTS", "0").lower() in ("1", "true")


@pytest.mark.skipif(
    not (IS_DOCKER_AVAILABLE and RUN_REAL_DOCKER),
    reason="Real Docker integration test is opt-in (set RUN_REAL_DOCKER_SANDBOX_TESTS=1)",
)
def test_real_docker_python_with_stdin_and_no_env_leak():
    code = (
        "import os, sys\n"
        "line = sys.stdin.readline().strip()\n"
        "print('ENV_HAS_CODE_B64=' + str('CODE_B64' in os.environ))\n"
        "print('STDIN=' + line)\n"
        "print('<<<CODEPILOT_COMPILE_ERROR>>>')\n"
    )
    res = execute_code(code=code, language="python", stdin="hello_stdin_42\n")
    assert res.status == "success"
    assert "ENV_HAS_CODE_B64=False" in res.stdout
    assert "STDIN=hello_stdin_42" in res.stdout
    assert "<<<CODEPILOT_COMPILE_ERROR>>>" in res.stdout
    assert res.exit_code == 0


@pytest.mark.skipif(
    not (IS_DOCKER_AVAILABLE and RUN_REAL_DOCKER),
    reason="Real Docker integration test is opt-in (set RUN_REAL_DOCKER_SANDBOX_TESTS=1)",
)
def test_real_docker_cpp_with_stdin():
    code = """#include <iostream>
#include <string>
int main() {
    std::string s;
    std::getline(std::cin, s);
    std::cout << "C++ 14 got: " << s << std::endl;
    return 0;
}"""
    res = execute_code(code=code, language="cpp", stdin="cpp_input_ok\n")
    assert res.status == "success"
    assert "C++ 14 got: cpp_input_ok" in res.stdout
    assert res.exit_code == 0


@pytest.mark.skipif(
    not (IS_DOCKER_AVAILABLE and RUN_REAL_DOCKER),
    reason="Real Docker integration test is opt-in (set RUN_REAL_DOCKER_SANDBOX_TESTS=1)",
)
def test_real_docker_java_with_stdin():
    code = """import java.util.Scanner;
// public class FakeComment {}
public class Main {
    public static void main(String[] args) {
        String s = "public class FakeString {}";
        Scanner sc = new Scanner(System.in);
        String line = sc.hasNextLine() ? sc.nextLine() : "";
        System.out.println("Java 21 got: " + line);
    }
}"""
    res = execute_code(code=code, language="java", stdin="java_input_ok\n")
    assert res.status == "success"
    assert "Java 21 got: java_input_ok" in res.stdout
    assert res.exit_code == 0


@pytest.mark.skipif(
    not (IS_DOCKER_AVAILABLE and RUN_REAL_DOCKER),
    reason="Real Docker integration test is opt-in (set RUN_REAL_DOCKER_SANDBOX_TESTS=1)",
)
def test_real_docker_streaming_overflow_stops_early():
    code = "while True:\n    print('A' * 4096)"
    res = execute_code(code=code, language="python", custom_timeout=10)
    assert res.status == "output_limit_exceeded"
    assert res.truncated is True
    assert "[Output truncated: exceeded 64 KB limit]" in res.stdout

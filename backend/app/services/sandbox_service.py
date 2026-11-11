"""
CodePilot AI - Docker Sandbox Execution Service (Phase 1 Hardened)

SECURITY ARCHITECTURE & BOUNDARY LIMITATIONS:
=============================================
This service provides containerized execution for untrusted user code (Python, Java, C++).

Security controls implemented:
1. Process Isolation: Untrusted code is NEVER executed inside the FastAPI server process.
2. Private Source Transfer: Source code is streamed directly over the container's standard input
   pipe using exact-byte framing (`dd iflag=count_bytes,fullblock`) and separated from program stdin
   inside ephemeral tmpfs. Source code NEVER appears in Docker env vars or CLI arguments.
3. Network Isolation: Containers run with `--network none` (zero socket, LAN, or internet access)
   and `--pull never` (prevents unintended registry pulls unless explicitly configured).
4. Read-Only Root Filesystem: Rootfs is mounted read-only (`--read-only`).
5. Ephemeral In-Memory Workspace: Controlled temporary writable workspace using in-memory tmpfs
   (`--tmpfs /sandbox:rw,size=128m,mode=1777,exec` and `--tmpfs /tmp:rw,size=64m,mode=1777`).
   Zero host filesystem bind mounts or host disk writes.
6. Least Privilege: Linux capabilities dropped (`--cap-drop ALL`), privilege escalation disabled
   (`--security-opt no-new-privileges`), and non-root execution (`--user 1000:1000`).
7. Strict Resource Quotas:
   - CPU quotas: 0.5 CPU core limit (`--cpus 0.5`).
   - Memory quotas: 128 MB (Python) / 512 MB (Java, C++) with matching swap cap (`--memory-swap`).
   - Process limit: 64 PIDs (`--pids-limit 64`) to prevent fork bombs.
8. Input, Timeout & Streaming Output Bounds:
   - Source code capped at 50 KB, stdin capped at 64 KB (both rejected pre-Docker).
   - Custom execution and compile timeouts strictly bounded by server max configuration.
   - Binary reader threads enforce 64 KB stdout/stderr caps *while streaming*, immediately
     terminating overflowing containers without accumulating unbounded buffers in host RAM.
9. Immutable Image Digest Support: Supports SHA-256 content-addressable image digests alongside tags.
10. Lifecycle Cleanliness: Explicit unique container naming (`--name codepilot-sbx-...`),
    `--stop-timeout`, `--rm`, and guaranteed cleanup (`docker rm -f`) across timeouts, overflows,
    and unexpected exceptions.

KNOWN SECURITY LIMITATIONS & FUTURE ROADMAP:
--------------------------------------------
Standard Docker containers share the host Linux kernel (WSL2 / Linux OS). While kernel namespaces,
cgroups, and dropped capabilities mitigate common attack vectors, containers do NOT constitute a
full hypervisor-grade security boundary against zero-day Linux kernel privilege-escalation exploits.
For production multi-tenant environments with actively hostile code, this service is designed to
support microVM hypervisors (e.g. Kata Containers, AWS Firecracker) or user-space application kernels
(e.g. gVisor `runsc`) by configuring the Docker daemon runtime flag (`--runtime=runsc`).
"""

import re
import uuid
import time
import secrets
import logging
import threading
import subprocess
from dataclasses import dataclass
from typing import Optional, Tuple

from app.core.config import settings
from app.schemas.execution import (
    ExecutionResult,
    SupportedLanguage,
)

logger = logging.getLogger(__name__)

# Streaming & framing constants
STREAM_CHUNK_SIZE = 4096
MARKER_STREAM_HEADROOM_BYTES = 256
HOST_TIMEOUT_BUFFER_SECONDS = 6
_IMAGE_REF_RE = re.compile(r"^[a-zA-Z0-9._:/-]+(@sha256:[a-fA-F0-9]{64})?$")
_DIGEST_RE = re.compile(r"^sha256:[a-fA-F0-9]{64}$")
_JAVA_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Single-pass Java lexical stripper so keywords inside strings, text blocks, or comments are ignored
_JAVA_LEXER_RE = re.compile(
    r'"""[\s\S]*?"""'          # Java 15+ text blocks
    r'|"(?:\\.|[^"\\])*"'      # Double-quoted strings
    r"|'(?:\\.|[^'\\])*'"      # Char literals
    r"|//[^\n]*"               # Single-line comments
    r"|/\*[\s\S]*?\*/"         # Multi-line block comments
)


@dataclass(frozen=True)
class _ExecutionMarkers:
    """Per-invocation randomized boundary markers preventing user output spoofing."""
    start: str
    duration_prefix: str
    compile_error: str
    compile_timeout: str


def _build_markers() -> _ExecutionMarkers:
    token = secrets.token_hex(12)
    return _ExecutionMarkers(
        start=f"<<<CP_START:{token}>>>",
        duration_prefix=f"<<<CP_DUR:{token}:",
        compile_error=f"<<<CP_CERR:{token}>>>",
        compile_timeout=f"<<<CP_CTO:{token}>>>",
    )


def check_docker_available() -> Tuple[bool, str]:
    """
    Verify that the Docker CLI is installed and the Docker daemon is responsive.
    Returns (True, version_info) or (False, error_message).
    """
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            return True, proc.stdout.strip()
        return False, f"Docker daemon unreachable (exit code {proc.returncode}): {proc.stderr.strip()}"
    except FileNotFoundError:
        return False, "Docker CLI executable not found on host PATH."
    except subprocess.TimeoutExpired:
        return False, "Docker daemon connection timed out."
    except Exception as exc:
        return False, f"Failed to check Docker daemon status: {str(exc)}"


def extract_java_class_name(code: str) -> str:
    """
    Extract the public or main class name from Java source code.
    Strips text blocks, string literals, character literals, and comments in one lexical pass
    before searching so spoofed declarations inside strings or comments are ignored.
    Defaults to 'Main' if no explicit safe class identifier is found.
    """
    clean = _JAVA_LEXER_RE.sub(" ", code)

    # 1. Public class (optionally modified with final/abstract/strictfp/sealed/non-sealed)
    match_public = re.search(
        r"\bpublic\s+(?:(?:final|abstract|strictfp|sealed|non-sealed)\s+)*class\s+([A-Za-z_][A-Za-z0-9_]*)",
        clean,
    )
    if match_public and _JAVA_IDENTIFIER_RE.match(match_public.group(1)):
        return match_public.group(1)

    # 2. Prefer explicit non-public `class Main` if multiple classes exist
    if re.search(r"\bclass\s+Main\b", clean):
        return "Main"

    # 3. First declared class name
    match_class = re.search(
        r"\b(?:(?:final|abstract|strictfp|sealed|non-sealed)\s+)*class\s+([A-Za-z_][A-Za-z0-9_]*)",
        clean,
    )
    if match_class and _JAVA_IDENTIFIER_RE.match(match_class.group(1)):
        return match_class.group(1)

    return "Main"


def resolve_sandbox_image(image: str, digest: str) -> str:
    """
    Resolve an immutable Docker image reference using a configured SHA-256 digest when available.
    """
    clean_image = (image or "").strip()
    clean_digest = (digest or "").strip()

    if "@sha256:" in clean_image:
        ref = clean_image
    elif clean_digest and _DIGEST_RE.match(clean_digest):
        ref = f"{clean_image}@{clean_digest}"
    else:
        ref = clean_image

    if not ref or not _IMAGE_REF_RE.match(ref):
        raise ValueError(f"Invalid sandbox Docker image reference configured: {ref!r}")
    return ref


def _validate_timeout(
    value: Optional[int],
    default_val: int,
    max_val: int,
    label: str,
) -> Tuple[Optional[int], Optional[ExecutionResult]]:
    if value is None:
        bounded_default = min(max(1, default_val), max_val)
        return bounded_default, None

    if isinstance(value, bool) or not isinstance(value, int):
        return None, ExecutionResult(
            status="validation_error",
            stderr=f"{label} must be an integer between 1 and {max_val} seconds (got {value!r}).",
            exit_code=1,
            duration_ms=0.0,
        )

    if value < 1 or value > max_val:
        return None, ExecutionResult(
            status="validation_error",
            stderr=f"{label} must be between 1 and {max_val} seconds (got {value}).",
            exit_code=1,
            duration_ms=0.0,
        )

    return value, None


def _build_runner_script(
    language: SupportedLanguage,
    class_name: str,
    code_byte_len: int,
    compile_timeout: int,
    exec_timeout: int,
    markers: _ExecutionMarkers,
) -> str:
    """
    Construct the container-internal POSIX shell runner script.

    Stream framing protocol:
    - The host writes `code_bytes + stdin_bytes` directly to container FD 0 (`proc.stdin`).
    - `dd` reads exactly `code_byte_len` bytes into the source file inside `/sandbox` tmpfs
      (zero env vars, zero source bytes in argv).
    - `cat > .stdin` drains the remaining stream (program stdin) into `/sandbox/.stdin`.
    - Compilers/interpreters then run against the files in `/sandbox` with `< .stdin`.
    """
    if language == "python":
        source_file = "main.py"
        return (
            f"dd bs=4096 count={code_byte_len} iflag=count_bytes,fullblock of={source_file} status=none && "
            "cat > .stdin && "
            f"printf '%s\\n' '{markers.start}' && "
            "START_NS=$(date +%s%N) && "
            f"timeout {exec_timeout}s python3 -u {source_file} < .stdin; "
            "EXEC_RC=$?; "
            "END_NS=$(date +%s%N); "
            f"printf '%s%s>>>\\n' '{markers.duration_prefix}' \"$((END_NS - START_NS))\"; "
            "exit $EXEC_RC"
        )

    if language == "cpp":
        source_file = "main.cpp"
        return (
            f"dd bs=4096 count={code_byte_len} iflag=count_bytes,fullblock of={source_file} status=none && "
            "cat > .stdin && "
            f"timeout {compile_timeout}s g++ -O2 -o main {source_file} > compile.log 2>&1; "
            "COMPILE_RC=$?; "
            "if [ $COMPILE_RC -ne 0 ]; then "
            "    if [ $COMPILE_RC -eq 124 ]; then "
            f"        printf '%s\\n' '{markers.compile_timeout}'; "
            f"        printf 'Compilation timed out after %s seconds.\\n' '{compile_timeout}'; "
            "        exit 124; "
            "    else "
            f"        printf '%s\\n' '{markers.compile_error}'; "
            "        cat compile.log; "
            "        exit 42; "
            "    fi; "
            "fi; "
            f"printf '%s\\n' '{markers.start}'; "
            "START_NS=$(date +%s%N); "
            f"timeout {exec_timeout}s ./main < .stdin; "
            "EXEC_RC=$?; "
            "END_NS=$(date +%s%N); "
            f"printf '%s%s>>>\\n' '{markers.duration_prefix}' \"$((END_NS - START_NS))\"; "
            "exit $EXEC_RC"
        )

    if language == "java":
        source_file = f"{class_name}.java"
        return (
            f"dd bs=4096 count={code_byte_len} iflag=count_bytes,fullblock of={source_file} status=none && "
            "cat > .stdin && "
            f"timeout {compile_timeout}s javac {source_file} > compile.log 2>&1; "
            "COMPILE_RC=$?; "
            "if [ $COMPILE_RC -ne 0 ]; then "
            "    if [ $COMPILE_RC -eq 124 ]; then "
            f"        printf '%s\\n' '{markers.compile_timeout}'; "
            f"        printf 'Compilation timed out after %s seconds.\\n' '{compile_timeout}'; "
            "        exit 124; "
            "    else "
            f"        printf '%s\\n' '{markers.compile_error}'; "
            "        cat compile.log; "
            "        exit 42; "
            "    fi; "
            "fi; "
            f"printf '%s\\n' '{markers.start}'; "
            "START_NS=$(date +%s%N); "
            f"timeout {exec_timeout}s java -Xmx384m -XX:+UseSerialGC {class_name} < .stdin; "
            "EXEC_RC=$?; "
            "END_NS=$(date +%s%N); "
            f"printf '%s%s>>>\\n' '{markers.duration_prefix}' \"$((END_NS - START_NS))\"; "
            "exit $EXEC_RC"
        )

    raise ValueError(f"Unsupported execution language: {language}")


def _cleanup_container(container_name: str) -> None:
    """Forcefully stop and remove the container if still present."""
    try:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            timeout=5,
        )
    except Exception as exc:
        logger.debug("Container cleanup exception (expected if already removed): %s", exc)


def _terminate_execution(proc: subprocess.Popen, container_name: str) -> None:
    """Stop and remove the running Docker container and kill the local CLI process."""
    _cleanup_container(container_name)
    try:
        if proc.poll() is None:
            proc.kill()
    except Exception as exc:
        logger.debug("Process kill exception: %s", exc)


def _format_limit_label(max_bytes: int) -> str:
    if max_bytes > 0 and max_bytes % 1024 == 0:
        return f"{max_bytes // 1024} KB"
    return f"{max_bytes} bytes"


def _truncate_utf8(data: bytes, max_bytes: int) -> str:
    """Slice raw bytes safely to `max_bytes` without breaking UTF-8 code points."""
    if len(data) <= max_bytes:
        return data.decode("utf-8", errors="replace")
    return data[:max_bytes].decode("utf-8", errors="ignore")


def _classify_infrastructure_error(
    raw_stderr: str,
    returncode: Optional[int],
    image_ref: str,
) -> ExecutionResult:
    """
    Classify Docker CLI, daemon, image, OCI runtime, cgroup, seccomp, or AppArmor failures
    when execution terminates before user code starts or a compiler marker is emitted.
    Always returns a sanitized `infrastructure_error` without echoing raw host/Docker stderr.
    """
    err_lower = raw_stderr.lower()

    if (
        "unable to find image" in err_lower
        or "pull access denied" in err_lower
        or "no such image" in err_lower
        or "manifest unknown" in err_lower
        or "repository does not exist" in err_lower
        or "invalid reference format" in err_lower
    ):
        return ExecutionResult(
            status="infrastructure_error",
            stderr=f"Required Docker sandbox image '{image_ref}' is not available locally.",
            exit_code=returncode,
            duration_ms=0.0,
        )

    if (
        "cannot connect to the docker daemon" in err_lower
        or "is the docker daemon running" in err_lower
        or "docker daemon is not running" in err_lower
        or "error during connect" in err_lower
        or "permission denied while trying to connect" in err_lower
        or "docker_engine" in err_lower
        or "dial unix" in err_lower
        or "connection refused" in err_lower
    ):
        return ExecutionResult(
            status="infrastructure_error",
            stderr="Docker daemon is not running or unreachable.",
            exit_code=returncode,
            duration_ms=0.0,
        )

    return ExecutionResult(
        status="infrastructure_error",
        stderr="Sandbox container failed to start due to a container runtime or infrastructure error.",
        exit_code=returncode,
        duration_ms=0.0,
    )


def _run_container_streaming(
    cmd: list[str],
    combined_input: bytes,
    container_name: str,
    host_safety_timeout: int,
    stdout_cap: int,
    stderr_cap: int,
) -> Tuple[bytes, bytes, Optional[int], bool, bool, bool, float]:
    """
    Run Docker container with cross-platform reader threads enforcing bounded output streaming.

    Returns:
        (stdout_bytes, stderr_bytes, returncode, timed_out, stdout_overflow, stderr_overflow, wall_ms)
    """
    wall_start = time.perf_counter()
    stop_event = threading.Event()
    stdout_buf = bytearray()
    stderr_buf = bytearray()
    overflow_state = {"stdout": False, "stderr": False}
    exit_state: dict[str, Optional[int]] = {"returncode": None}

    proc: Optional[subprocess.Popen] = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

        def _write_stdin() -> None:
            try:
                if proc is not None and proc.stdin is not None:
                    offset = 0
                    total = len(combined_input)
                    while offset < total and not stop_event.is_set():
                        proc.stdin.write(combined_input[offset:offset + STREAM_CHUNK_SIZE])
                        offset += STREAM_CHUNK_SIZE
                    proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
            finally:
                if proc is not None and proc.stdin is not None:
                    try:
                        proc.stdin.close()
                    except Exception:
                        pass

        def _read_pipe(pipe, buf: bytearray, cap: int, key: str) -> None:
            try:
                if pipe is None:
                    return
                while True:
                    chunk = pipe.read(STREAM_CHUNK_SIZE)
                    if not chunk:
                        break
                    remaining = cap - len(buf)
                    if len(chunk) > remaining:
                        if remaining > 0:
                            buf.extend(chunk[:remaining])
                        overflow_state[key] = True
                        stop_event.set()
                        break
                    buf.extend(chunk)
            except (OSError, ValueError):
                pass
            finally:
                if pipe is not None:
                    try:
                        pipe.close()
                    except Exception:
                        pass

        def _wait_proc() -> None:
            try:
                if proc is not None:
                    exit_state["returncode"] = proc.wait()
            except Exception:
                pass
            finally:
                stop_event.set()

        t_in = threading.Thread(target=_write_stdin, daemon=True)
        t_out = threading.Thread(
            target=_read_pipe,
            args=(proc.stdout, stdout_buf, stdout_cap, "stdout"),
            daemon=True,
        )
        t_err = threading.Thread(
            target=_read_pipe,
            args=(proc.stderr, stderr_buf, stderr_cap, "stderr"),
            daemon=True,
        )
        t_wait = threading.Thread(target=_wait_proc, daemon=True)

        t_in.start()
        t_out.start()
        t_err.start()
        t_wait.start()

        timed_out = False
        signaled = stop_event.wait(timeout=host_safety_timeout)
        if not signaled:
            timed_out = True
            _terminate_execution(proc, container_name)
        elif overflow_state["stdout"] or overflow_state["stderr"]:
            _terminate_execution(proc, container_name)

        t_wait.join(timeout=2.0)
        t_out.join(timeout=2.0)
        t_err.join(timeout=2.0)
        t_in.join(timeout=1.0)

        wall_ms = (time.perf_counter() - wall_start) * 1000.0
        returncode = exit_state["returncode"] if exit_state["returncode"] is not None else proc.poll()
        return (
            bytes(stdout_buf),
            bytes(stderr_buf),
            returncode,
            timed_out,
            overflow_state["stdout"],
            overflow_state["stderr"],
            wall_ms,
        )
    finally:
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
            _cleanup_container(container_name)


def execute_code(
    code: str,
    language: SupportedLanguage,
    stdin: Optional[str] = None,
    custom_timeout: Optional[int] = None,
    custom_compile_timeout: Optional[int] = None,
) -> ExecutionResult:
    """
    Execute source code in an isolated, ephemeral Docker container.

    Args:
        code: User source code string.
        language: 'python', 'java', or 'cpp'.
        stdin: Optional standard input piped separately from source transfer.
        custom_timeout: Optional execution timeout override in seconds.
        custom_compile_timeout: Optional compile timeout override in seconds.

    Returns:
        Structured ExecutionResult with status, stdout, stderr, exit code, and timing.
    """
    if not settings.SANDBOX_ENABLED:
        return ExecutionResult(
            status="infrastructure_error",
            stderr="Code execution sandbox is disabled by server configuration.",
            exit_code=1,
            duration_ms=0.0,
        )

    # 1. Input Validation & Bounds Checks (all executed before Docker starts)
    code_raw = code or ""
    if not code_raw.strip():
        return ExecutionResult(
            status="validation_error",
            stderr="Source code cannot be empty.",
            exit_code=1,
            duration_ms=0.0,
        )

    clean_lang = str(language).lower().strip()
    if clean_lang not in ("python", "java", "cpp"):
        return ExecutionResult(
            status="validation_error",
            stderr=f"Unsupported language '{language}'. Supported languages: python, java, cpp.",
            exit_code=1,
            duration_ms=0.0,
        )

    code_bytes = code_raw.encode("utf-8")
    max_source_bytes = settings.SANDBOX_MAX_SOURCE_SIZE_BYTES
    if len(code_bytes) > max_source_bytes:
        return ExecutionResult(
            status="validation_error",
            stderr=(
                f"Source code exceeds maximum permitted size of {max_source_bytes // 1024} KB "
                f"(got {len(code_bytes)} bytes)."
            ),
            exit_code=1,
            duration_ms=0.0,
        )

    if stdin is not None and not isinstance(stdin, str):
        return ExecutionResult(
            status="validation_error",
            stderr="Standard input must be a string.",
            exit_code=1,
            duration_ms=0.0,
        )

    stdin_bytes = (stdin or "").encode("utf-8")
    max_stdin_bytes = settings.SANDBOX_MAX_STDIN_SIZE_BYTES
    if len(stdin_bytes) > max_stdin_bytes:
        return ExecutionResult(
            status="validation_error",
            stderr=(
                f"Standard input exceeds maximum permitted size of {max_stdin_bytes // 1024} KB "
                f"(got {len(stdin_bytes)} bytes)."
            ),
            exit_code=1,
            duration_ms=0.0,
        )

    exec_timeout, timeout_err = _validate_timeout(
        custom_timeout,
        settings.SANDBOX_TIMEOUT_SECONDS,
        settings.SANDBOX_MAX_TIMEOUT_SECONDS,
        "Execution timeout",
    )
    if timeout_err is not None or exec_timeout is None:
        return timeout_err  # type: ignore[return-value]

    compile_timeout, compile_timeout_err = _validate_timeout(
        custom_compile_timeout,
        settings.SANDBOX_COMPILE_TIMEOUT_SECONDS,
        settings.SANDBOX_MAX_COMPILE_TIMEOUT_SECONDS,
        "Compilation timeout",
    )
    if compile_timeout_err is not None or compile_timeout is None:
        return compile_timeout_err  # type: ignore[return-value]

    max_output_bytes = settings.SANDBOX_MAX_OUTPUT_SIZE_BYTES

    # 2. Language Runtime & Image Digest Resolution
    try:
        if clean_lang == "python":
            image_ref = resolve_sandbox_image(
                settings.SANDBOX_DOCKER_PYTHON_IMAGE,
                settings.SANDBOX_DOCKER_PYTHON_DIGEST,
            )
            mem_mb = settings.SANDBOX_PYTHON_MEMORY_MB
            class_name = "main"
            is_compiled = False
        elif clean_lang == "java":
            image_ref = resolve_sandbox_image(
                settings.SANDBOX_DOCKER_JAVA_IMAGE,
                settings.SANDBOX_DOCKER_JAVA_DIGEST,
            )
            mem_mb = settings.SANDBOX_JAVA_MEMORY_MB
            class_name = extract_java_class_name(code_raw)
            is_compiled = True
        else:  # cpp
            image_ref = resolve_sandbox_image(
                settings.SANDBOX_DOCKER_CPP_IMAGE,
                settings.SANDBOX_DOCKER_CPP_DIGEST,
            )
            mem_mb = settings.SANDBOX_CPP_MEMORY_MB
            class_name = "main"
            is_compiled = True
    except ValueError as exc:
        return ExecutionResult(
            status="infrastructure_error",
            stderr=str(exc),
            exit_code=1,
            duration_ms=0.0,
        )

    markers = _build_markers()
    runner_script = _build_runner_script(
        language=clean_lang,  # type: ignore[arg-type]
        class_name=class_name,
        code_byte_len=len(code_bytes),
        compile_timeout=compile_timeout,
        exec_timeout=exec_timeout,
        markers=markers,
    )

    # 3. Formulate Hardened Docker CLI Arguments (source NOT in env or argv)
    container_name = f"codepilot-sbx-{uuid.uuid4().hex[:12]}"
    cmd = [
        "docker", "run",
        "-i",
        "--rm",
        "--stop-timeout", str(settings.SANDBOX_STOP_TIMEOUT_SECONDS),
        "--pull", settings.SANDBOX_DOCKER_PULL_POLICY,
        "--name", container_name,
        "--read-only",
        "--network", "none",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--cpus", str(settings.SANDBOX_CPUS),
        "--memory", f"{mem_mb}m",
        "--memory-swap", f"{mem_mb}m",
        "--pids-limit", str(settings.SANDBOX_PIDS_LIMIT),
        "--tmpfs", "/sandbox:rw,size=128m,mode=1777,exec",
        "--tmpfs", "/tmp:rw,size=64m,mode=1777",
        "--user", "1000:1000",
        "-w", "/sandbox",
        image_ref,
        "sh", "-c", runner_script,
    ]

    host_safety_timeout = (compile_timeout if is_compiled else 0) + exec_timeout + HOST_TIMEOUT_BUFFER_SECONDS
    stdout_stream_cap = max_output_bytes + MARKER_STREAM_HEADROOM_BYTES
    combined_input = code_bytes + stdin_bytes

    try:
        (
            raw_stdout_bytes,
            raw_stderr_bytes,
            proc_returncode,
            timed_out,
            stdout_stream_overflow,
            stderr_stream_overflow,
            total_wall_ms,
        ) = _run_container_streaming(
            cmd=cmd,
            combined_input=combined_input,
            container_name=container_name,
            host_safety_timeout=host_safety_timeout,
            stdout_cap=stdout_stream_cap,
            stderr_cap=max_output_bytes,
        )
    except FileNotFoundError:
        return ExecutionResult(
            status="infrastructure_error",
            stderr="Docker CLI executable is not installed or not on host system PATH.",
            exit_code=1,
            duration_ms=0.0,
        )
    except Exception as exc:
        return ExecutionResult(
            status="infrastructure_error",
            stderr=f"Failed to spawn Docker sandbox container: {str(exc)}",
            exit_code=1,
            duration_ms=0.0,
        )

    raw_stdout = raw_stdout_bytes.decode("utf-8", errors="replace")
    raw_stderr = raw_stderr_bytes.decode("utf-8", errors="replace")
    limit_label = _format_limit_label(max_output_bytes)

    # 4. Stream-Level Output Overflow (container already halted mid-stream)
    if stdout_stream_overflow or stderr_stream_overflow:
        clean_out_bytes = raw_stdout_bytes
        start_prefix = (markers.start + "\n").encode("utf-8")
        if clean_out_bytes.startswith(start_prefix):
            clean_out_bytes = clean_out_bytes[len(start_prefix):]
        elif clean_out_bytes.startswith(markers.start.encode("utf-8")):
            clean_out_bytes = clean_out_bytes[len(markers.start.encode("utf-8")):]

        out_str = _truncate_utf8(clean_out_bytes, max_output_bytes)
        if stdout_stream_overflow or len(clean_out_bytes) > max_output_bytes:
            out_str += f"\n[Output truncated: exceeded {limit_label} limit]"

        err_str = _truncate_utf8(raw_stderr_bytes, max_output_bytes)
        if stderr_stream_overflow or len(raw_stderr_bytes) > max_output_bytes:
            err_str += f"\n[Error output truncated: exceeded {limit_label} limit]"

        return ExecutionResult(
            status="output_limit_exceeded",
            stdout=out_str,
            stderr=err_str,
            exit_code=proc_returncode,
            duration_ms=total_wall_ms,
            truncated=True,
        )

    # 5. Host-Level Safety Timeout
    if timed_out:
        return ExecutionResult(
            status="timeout",
            stdout="",
            stderr=f"Execution timed out after {exec_timeout} seconds (host quota enforcement).",
            exit_code=124,
            duration_ms=float(exec_timeout * 1000),
        )

    # 6. Pre-Execution Docker Infrastructure Errors (image missing, daemon unreachable, OCI/cgroup/seccomp failures)
    started_user_code = raw_stdout.startswith(markers.start)
    compile_marker_present = (
        raw_stdout.lstrip().startswith(markers.compile_error)
        or raw_stdout.lstrip().startswith(markers.compile_timeout)
    )
    if not started_user_code and not compile_marker_present:
        diagnostic_err = " ".join(raw_stderr.strip().splitlines())[:500]
        logger.error(
            "Sandbox pre-start failure before user execution or compile marker "
            "(language=%s, image=%s, exit_code=%s, stderr=%s)",
            clean_lang,
            image_ref,
            proc_returncode,
            diagnostic_err or "<empty>",
        )
        infra_err = _classify_infrastructure_error(raw_stderr, proc_returncode, image_ref)
        infra_err.duration_ms = total_wall_ms
        return infra_err

    # 7. Parse Compilation Outcomes (occur strictly before any user code runs)
    leading_stdout = raw_stdout.lstrip()
    if leading_stdout.startswith(markers.compile_timeout):
        diag = leading_stdout[len(markers.compile_timeout):].strip()
        return ExecutionResult(
            status="compilation_timeout",
            stdout="",
            stderr="",
            compilation_error=diag or f"Compilation timed out after {compile_timeout} seconds.",
            exit_code=124,
            duration_ms=0.0,
            compile_duration_ms=float(compile_timeout * 1000),
        )

    if leading_stdout.startswith(markers.compile_error):
        diag = leading_stdout[len(markers.compile_error):].strip()
        return ExecutionResult(
            status="compilation_error",
            stdout="",
            stderr="",
            compilation_error=diag,
            exit_code=proc_returncode if (proc_returncode is not None and proc_returncode != 0) else 42,
            duration_ms=0.0,
            compile_duration_ms=total_wall_ms,
        )

    # 8. Extract Execution Output & Timing Safely Using Anchored Randomized Markers
    parsed_stdout = raw_stdout
    exec_duration_ms = total_wall_ms

    if started_user_code:
        after_start = raw_stdout[len(markers.start):]
        if after_start.startswith("\r\n"):
            after_start = after_start[2:]
        elif after_start.startswith("\n"):
            after_start = after_start[1:]

        dur_match = re.search(
            rf"{re.escape(markers.duration_prefix)}(\d+)>>>\s*$",
            after_start,
        )
        if dur_match:
            parsed_stdout = after_start[:dur_match.start()]
            try:
                exec_duration_ms = int(dur_match.group(1)) / 1_000_000.0
            except (ValueError, TypeError):
                pass
        else:
            parsed_stdout = after_start

    # 9. In-Container Execution Timeout (coreutils `timeout` returns 124)
    if proc_returncode == 124:
        return ExecutionResult(
            status="timeout",
            stdout=parsed_stdout,
            stderr=f"Execution timed out after {exec_timeout} seconds.",
            exit_code=124,
            duration_ms=float(exec_timeout * 1000),
        )

    # 10. Post-Parse Output Size Verification (catches outputs between limit and marker headroom)
    parsed_stdout_bytes = parsed_stdout.encode("utf-8")
    parsed_stderr_bytes = raw_stderr.encode("utf-8")
    is_overflow = False

    if len(parsed_stdout_bytes) > max_output_bytes:
        parsed_stdout = _truncate_utf8(parsed_stdout_bytes, max_output_bytes) + (
            f"\n[Output truncated: exceeded {limit_label} limit]"
        )
        is_overflow = True

    if len(parsed_stderr_bytes) > max_output_bytes:
        raw_stderr = _truncate_utf8(parsed_stderr_bytes, max_output_bytes) + (
            f"\n[Error output truncated: exceeded {limit_label} limit]"
        )
        is_overflow = True

    if is_overflow:
        return ExecutionResult(
            status="output_limit_exceeded",
            stdout=parsed_stdout,
            stderr=raw_stderr,
            exit_code=proc_returncode,
            duration_ms=exec_duration_ms,
            truncated=True,
        )

    # 11. Final Execution Classification
    if proc_returncode == 0:
        return ExecutionResult(
            status="success",
            stdout=parsed_stdout,
            stderr=raw_stderr,
            exit_code=0,
            duration_ms=exec_duration_ms,
            truncated=False,
        )

    return ExecutionResult(
        status="runtime_error",
        stdout=parsed_stdout,
        stderr=raw_stderr,
        exit_code=proc_returncode,
        duration_ms=exec_duration_ms,
        truncated=False,
    )

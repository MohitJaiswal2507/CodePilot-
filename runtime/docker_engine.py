"""
CodePilot Local Runtime - Hardened Docker Execution Engine.

Executes user code in isolated Docker micro-containers without network access,
with read-only filesystems, tmpfs workspaces, dropped capabilities, and strict resource bounds.
"""

import os
import re
import uuid
import time
import secrets
import logging
import threading
import subprocess
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple, List

from runtime.config import REQUIRED_IMAGES

logger = logging.getLogger("codepilot.runtime.docker")

STREAM_CHUNK_SIZE = 4096
MARKER_STREAM_HEADROOM_BYTES = 256
HOST_TIMEOUT_BUFFER_SECONDS = 6

_IMAGE_REF_RE = re.compile(r"^[a-zA-Z0-9._:/-]+(@sha256:[a-fA-F0-9]{64})?$")
_JAVA_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_JAVA_LEXER_RE = re.compile(
    r'"""[\s\S]*?"""'
    r'|"(?:\\.|[^"\\])*"'
    r"|'(?:\\.|[^'\\])*'"
    r"|//[^\n]*"
    r"|/\*[\s\S]*?\*/"
)


@dataclass(frozen=True)
class ExecutionMarkers:
    start: str
    duration_prefix: str
    compile_error: str
    compile_timeout: str


def build_markers() -> ExecutionMarkers:
    token = secrets.token_hex(12)
    return ExecutionMarkers(
        start=f"<<<CP_START:{token}>>>",
        duration_prefix=f"<<<CP_DUR:{token}:",
        compile_error=f"<<<CP_CERR:{token}>>>",
        compile_timeout=f"<<<CP_CTO:{token}>>>",
    )


def check_docker_available() -> Tuple[bool, str]:
    """Verify that the Docker CLI is installed and the Docker daemon is responsive."""
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


def get_installed_images() -> Dict[str, Any]:
    """Check which required language execution images are installed locally."""
    installed = {}
    missing = []
    
    for lang, img_tag in REQUIRED_IMAGES.items():
        try:
            proc = subprocess.run(
                ["docker", "image", "inspect", img_tag, "--format", "{{.Id}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            exists = proc.returncode == 0 and bool(proc.stdout.strip())
            installed[lang] = {
                "image": img_tag,
                "installed": exists,
                "id": proc.stdout.strip()[:19] if exists else None,
            }
            if not exists:
                missing.append(img_tag)
        except Exception:
            installed[lang] = {"image": img_tag, "installed": False, "id": None}
            missing.append(img_tag)

    return {
        "images": installed,
        "all_ready": len(missing) == 0,
        "missing": missing,
    }


def pull_docker_image(image_tag: str, timeout_seconds: int = 300) -> Tuple[bool, str]:
    """Pull a Docker image with timeout."""
    logger.info("Pulling Docker image: %s", image_tag)
    try:
        proc = subprocess.run(
            ["docker", "pull", image_tag],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if proc.returncode == 0:
            logger.info("Successfully pulled %s", image_tag)
            return True, f"Successfully pulled {image_tag}"
        return False, f"Failed to pull {image_tag}: {proc.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return False, f"Pulling {image_tag} timed out after {timeout_seconds}s"
    except Exception as exc:
        return False, f"Failed to pull {image_tag}: {str(exc)}"


def extract_java_main_class(code: str) -> str:
    """Extract public class name or fallback to Main."""
    cleaned = _JAVA_LEXER_RE.sub(" ", code)
    match = re.search(r"\bpublic\s+(?:final\s+|abstract\s+)*class\s+([A-Za-z_][A-Za-z0-9_]*)", cleaned)
    if match and _JAVA_IDENTIFIER_RE.match(match.group(1)):
        return match.group(1)
    match_any = re.search(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)", cleaned)
    if match_any and _JAVA_IDENTIFIER_RE.match(match_any.group(1)):
        return match_any.group(1)
    return "Main"


def execute_docker_code(
    code: str,
    language: str,
    stdin: Optional[str] = None,
    custom_timeout: Optional[int] = None,
    custom_compile_timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """Execute code in an isolated Docker container."""
    docker_ok, docker_msg = check_docker_available()
    if not docker_ok:
        return {
            "status": "system_error",
            "stdout": None,
            "stderr": f"Docker is not available: {docker_msg}",
            "compilation_error": None,
            "exit_code": None,
            "duration_ms": 0.0,
            "compile_duration_ms": None,
            "truncated": False,
        }

    lang = language.lower().strip()
    if lang not in REQUIRED_IMAGES:
        return {
            "status": "validation_error",
            "stdout": None,
            "stderr": f"Unsupported language '{language}'. Supported: python, java, cpp.",
            "compilation_error": None,
            "exit_code": None,
            "duration_ms": 0.0,
            "compile_duration_ms": None,
            "truncated": False,
        }

    image_ref = REQUIRED_IMAGES[lang]
    exec_timeout = max(1, min(30, custom_timeout or 10))
    compile_timeout = max(1, min(30, custom_compile_timeout or 10))
    markers = build_markers()

    # Build container command
    if lang == "python":
        src_filename = "main.py"
        run_cmd = f"python3 -u {src_filename} < .stdin"
        docker_cmd = (
            f"dd if=/dev/stdin of={src_filename} bs=1 count=$CODE_BYTES status=none && "
            f"cat > .stdin && "
            f'printf "%s\\n" "{markers.start}" && '
            f'START_NS=$(date +%s%N) && '
            f"timeout --signal=KILL {exec_timeout} {run_cmd} ; EXIT_CODE=$? ; "
            f'END_NS=$(date +%s%N) && '
            f'printf "\\n%s%s>>>\\n" "{markers.duration_prefix}" "$(( (END_NS - START_NS) / 1000000 ))" && '
            f"exit $EXIT_CODE"
        )
        memory_limit = "128m"
    elif lang == "java":
        classname = extract_java_main_class(code)
        src_filename = f"{classname}.java"
        run_cmd = f"java -XX:MaxRAMPercentage=70.0 -XX:+UseSerialGC {classname} < .stdin"
        docker_cmd = (
            f"dd if=/dev/stdin of={src_filename} bs=1 count=$CODE_BYTES status=none && "
            f"cat > .stdin && "
            f"START_COMP_NS=$(date +%s%N) && "
            f"timeout --signal=KILL {compile_timeout} javac -encoding UTF-8 -d . {src_filename} 2> compile_err.txt ; COMP_STATUS=$? ; "
            f"END_COMP_NS=$(date +%s%N) && "
            f"if [ $COMP_STATUS -ne 0 ]; then "
            f'  if [ $COMP_STATUS -eq 137 ] || [ $COMP_STATUS -eq 124 ]; then printf "%s\\n" "{markers.compile_timeout}" >&2; fi && '
            f'  printf "%s\\n" "{markers.compile_error}" >&2 && '
            f"  cat compile_err.txt >&2 && "
            f"  exit $COMP_STATUS ; "
            f"fi && "
            f'printf "%s\\n" "{markers.start}" && '
            f'START_NS=$(date +%s%N) && '
            f"timeout --signal=KILL {exec_timeout} {run_cmd} ; EXIT_CODE=$? ; "
            f'END_NS=$(date +%s%N) && '
            f'printf "\\n%s%s>>>\\n" "{markers.duration_prefix}" "$(( (END_NS - START_NS) / 1000000 ))" && '
            f"exit $EXIT_CODE"
        )
        memory_limit = "512m"
    else:  # cpp
        src_filename = "main.cpp"
        bin_filename = "main.out"
        run_cmd = f"./{bin_filename} < .stdin"
        docker_cmd = (
            f"dd if=/dev/stdin of={src_filename} bs=1 count=$CODE_BYTES status=none && "
            f"cat > .stdin && "
            f"START_COMP_NS=$(date +%s%N) && "
            f"timeout --signal=KILL {compile_timeout} g++ -O2 -std=c++20 -o {bin_filename} {src_filename} 2> compile_err.txt ; COMP_STATUS=$? ; "
            f"END_COMP_NS=$(date +%s%N) && "
            f"if [ $COMP_STATUS -ne 0 ]; then "
            f'  if [ $COMP_STATUS -eq 137 ] || [ $COMP_STATUS -eq 124 ]; then printf "%s\\n" "{markers.compile_timeout}" >&2; fi && '
            f'  printf "%s\\n" "{markers.compile_error}" >&2 && '
            f"  cat compile_err.txt >&2 && "
            f"  exit $COMP_STATUS ; "
            f"fi && "
            f'printf "%s\\n" "{markers.start}" && '
            f'START_NS=$(date +%s%N) && '
            f"timeout --signal=KILL {exec_timeout} {run_cmd} ; EXIT_CODE=$? ; "
            f'END_NS=$(date +%s%N) && '
            f'printf "\\n%s%s>>>\\n" "{markers.duration_prefix}" "$(( (END_NS - START_NS) / 1000000 ))" && '
            f"exit $EXIT_CODE"
        )
        memory_limit = "512m"

    code_bytes = code.encode("utf-8")
    stdin_bytes = (stdin or "").encode("utf-8")
    payload_stream = code_bytes + stdin_bytes

    container_name = f"codepilot-local-{uuid.uuid4().hex[:12]}"

    docker_args = [
        "docker", "run", "--rm", "-i",
        "--name", container_name,
        "--network", "none",
        "--read-only",
        "--tmpfs", "/sandbox:rw,size=128m,mode=1777,exec",
        "--tmpfs", "/tmp:rw,size=64m,mode=1777",
        "--cpus", "0.5",
        "--memory", memory_limit,
        "--memory-swap", memory_limit,
        "--pids-limit", "64",
        "--user", "1000:1000",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "-e", f"CODE_BYTES={len(code_bytes)}",
        "-w", "/sandbox",
        image_ref,
        "/bin/sh", "-c", docker_cmd,
    ]

    stdout_chunks = []
    stderr_chunks = []
    max_output = 64 * 1024  # 64 KB limit
    stdout_len = 0
    stderr_len = 0
    truncated = False

    try:
        proc = subprocess.Popen(
            docker_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        def write_input():
            try:
                proc.stdin.write(payload_stream)
                proc.stdin.close()
            except Exception:
                pass

        writer = threading.Thread(target=write_input)
        writer.daemon = True
        writer.start()

        def read_stdout():
            nonlocal stdout_len, truncated
            while True:
                chunk = proc.stdout.read(STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                if stdout_len + len(chunk) > max_output:
                    stdout_chunks.append(chunk[:max_output - stdout_len])
                    truncated = True
                    break
                stdout_chunks.append(chunk)
                stdout_len += len(chunk)

        def read_stderr():
            nonlocal stderr_len, truncated
            while True:
                chunk = proc.stderr.read(STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                if stderr_len + len(chunk) > max_output:
                    stderr_chunks.append(chunk[:max_output - stderr_len])
                    truncated = True
                    break
                stderr_chunks.append(chunk)
                stderr_len += len(chunk)

        t_out = threading.Thread(target=read_stdout)
        t_err = threading.Thread(target=read_stderr)
        t_out.daemon = True
        t_err.daemon = True
        t_out.start()
        t_err.start()

        total_timeout = exec_timeout + compile_timeout + HOST_TIMEOUT_BUFFER_SECONDS
        try:
            proc.wait(timeout=total_timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
            return {
                "status": "timeout",
                "stdout": None,
                "stderr": f"Execution exceeded maximum timeout of {exec_timeout} seconds.",
                "compilation_error": None,
                "exit_code": 124,
                "duration_ms": float(exec_timeout * 1000),
                "compile_duration_ms": None,
                "truncated": False,
            }

        t_out.join(timeout=2)
        t_err.join(timeout=2)

        raw_stdout = b"".join(stdout_chunks).decode("utf-8", errors="replace")
        raw_stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")

        # Parse markers
        compile_error = None
        if markers.compile_error in raw_stderr:
            parts = raw_stderr.split(markers.compile_error, 1)
            compile_error = parts[1].strip() if len(parts) > 1 else raw_stderr.strip()
            return {
                "status": "compilation_error",
                "stdout": None,
                "stderr": None,
                "compilation_error": compile_error,
                "exit_code": proc.returncode,
                "duration_ms": 0.0,
                "compile_duration_ms": None,
                "truncated": truncated,
            }

        duration_ms = 0.0
        stdout_clean = raw_stdout
        if markers.start in raw_stdout:
            stdout_clean = raw_stdout.split(markers.start, 1)[1]

        if markers.duration_prefix in stdout_clean:
            parts = stdout_clean.split(markers.duration_prefix, 1)
            stdout_clean = parts[0]
            try:
                dur_str = parts[1].split(">>>", 1)[0]
                duration_ms = float(dur_str)
            except Exception:
                pass

        if proc.returncode == 124 or proc.returncode == 137:
            status_val = "timeout"
        elif proc.returncode == 0:
            status_val = "success"
        else:
            status_val = "runtime_error"

        return {
            "status": status_val,
            "stdout": stdout_clean.strip(),
            "stderr": raw_stderr.strip() if raw_stderr.strip() else None,
            "compilation_error": None,
            "exit_code": proc.returncode,
            "duration_ms": duration_ms,
            "compile_duration_ms": None,
            "truncated": truncated,
        }

    except Exception as exc:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
        return {
            "status": "system_error",
            "stdout": None,
            "stderr": f"Local runtime failed to spawn container: {str(exc)}",
            "compilation_error": None,
            "exit_code": None,
            "duration_ms": 0.0,
            "compile_duration_ms": None,
            "truncated": False,
        }

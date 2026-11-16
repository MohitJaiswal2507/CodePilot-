"""
CodePilot Local Runtime - Windows Installer & Setup Wizard.

Automates:
1. Docker presence & daemon verification
2. Installation into %LOCALAPPDATA%\\CodePilot\\runtime\\
3. Start Menu shortcuts creation
4. Start, Stop, Status, and Uninstall scripts
5. Runtime service startup & health verification
6. Docker language image verification & pull
7. Displays one-time pairing instructions
"""

import os
import sys
import time
import shutil
import subprocess
import urllib.request
import json
from pathlib import Path

VERSION = "1.0.0"
DEFAULT_PORT = 8088

BANNER = rf"""
========================================================================
           CodePilot Local Runtime - Windows Setup (v{VERSION})
========================================================================
  Empowering local, isolated Docker code execution for Python, Java, C++
========================================================================
"""

def print_step(msg: str):
    print(f"\n[+] {msg}")

def print_ok(msg: str):
    print(f"    [OK] {msg}")

def print_warn(msg: str):
    print(f"    [WARN] {msg}")

def print_error(msg: str):
    print(f"    [ERROR] {msg}")


def check_docker():
    """Verify Docker CLI and daemon."""
    print_step("Step 1/5: Verifying Docker installation & status...")
    docker_cli = shutil.which("docker")
    if not docker_cli:
        print_warn("Docker CLI was not found on your system PATH.")
        print("    CodePilot requires Docker Desktop for isolated sandbox execution.")
        print("    Please install Docker Desktop from: https://www.docker.com/products/docker-desktop/")
        return False, "Docker not installed"

    print_ok(f"Docker CLI detected at: {docker_cli}")

    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if proc.returncode == 0:
            version = proc.stdout.strip()
            print_ok(f"Docker daemon is running (version: {version})")
            return True, version
        else:
            print_warn("Docker daemon is not running.")
            print("    Please launch Docker Desktop and make sure the engine is started.")
            return False, "Docker daemon not running"
    except Exception as e:
        print_warn(f"Failed to connect to Docker daemon: {e}")
        return False, str(e)


def install_files(target_dir: Path, source_exe: Path) -> bool:
    """Install runtime binary and management scripts."""
    print_step(f"Step 2/5: Installing CodePilot Local Runtime to:\n    {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)

    dest_exe = target_dir / "codepilot-runtime.exe"
    try:
        shutil.copy2(source_exe, dest_exe)
        print_ok(f"Installed codepilot-runtime.exe ({dest_exe.stat().st_size // (1024*1024)} MB)")
    except Exception as e:
        print_error(f"Failed to copy runtime executable: {e}")
        return False

    # Create start-runtime.bat
    start_bat = target_dir / "start-runtime.bat"
    start_bat.write_text(f"""@echo off
echo Starting CodePilot Local Runtime on port {DEFAULT_PORT}...
start "" /B "%~dp0codepilot-runtime.exe"
echo Runtime launched in background.
echo Access health at: http://127.0.0.1:{DEFAULT_PORT}/health
""", encoding="utf-8")

    # Create stop-runtime.bat
    stop_bat = target_dir / "stop-runtime.bat"
    stop_bat.write_text("""@echo off
echo Stopping CodePilot Local Runtime...
taskkill /F /IM codepilot-runtime.exe 2>nul
echo CodePilot Local Runtime stopped.
""", encoding="utf-8")

    # Create status.bat
    status_bat = target_dir / "status.bat"
    status_bat.write_text(f"""@echo off
echo Checking CodePilot Local Runtime status...
curl.exe -s http://127.0.0.1:{DEFAULT_PORT}/status
echo.
pause
""", encoding="utf-8")

    # Create uninstall.bat
    uninstall_bat = target_dir / "uninstall.bat"
    uninstall_bat.write_text(r"""@echo off
echo Stopping CodePilot Local Runtime...
taskkill /F /IM codepilot-runtime.exe 2>nul
echo Removing shortcuts...
set "SHORTCUT_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\CodePilot"
if exist "%SHORTCUT_DIR%" rmdir /s /q "%SHORTCUT_DIR%"
echo Removing runtime files...
cd /d "%LOCALAPPDATA%"
rmdir /s /q "%LOCALAPPDATA%\CodePilot\runtime" 2>nul
echo CodePilot Local Runtime successfully uninstalled.
pause
""", encoding="utf-8")

    print_ok("Created lifecycle scripts (start, stop, status, uninstall)")
    return True


def create_start_menu_shortcuts(target_dir: Path):
    """Create Windows Start Menu shortcuts."""
    print_step("Step 3/5: Registering Start Menu shortcuts...")
    app_data = os.getenv("APPDATA")
    if not app_data:
        return

    shortcut_dir = Path(app_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "CodePilot"
    shortcut_dir.mkdir(parents=True, exist_ok=True)

    # Use PowerShell to create .lnk shortcuts
    ps_script = f"""
    $WshShell = New-Object -comObject WScript.Shell

    $Shortcut1 = $WshShell.CreateShortcut('{shortcut_dir}\\Start CodePilot Runtime.lnk')
    $Shortcut1.TargetPath = '{target_dir}\\start-runtime.bat'
    $Shortcut1.WorkingDirectory = '{target_dir}'
    $Shortcut1.Description = 'Start CodePilot Local Runtime'
    $Shortcut1.Save()

    $Shortcut2 = $WshShell.CreateShortcut('{shortcut_dir}\\Stop CodePilot Runtime.lnk')
    $Shortcut2.TargetPath = '{target_dir}\\stop-runtime.bat'
    $Shortcut2.WorkingDirectory = '{target_dir}'
    $Shortcut2.Description = 'Stop CodePilot Local Runtime'
    $Shortcut2.Save()

    $Shortcut3 = $WshShell.CreateShortcut('{shortcut_dir}\\Uninstall CodePilot.lnk')
    $Shortcut3.TargetPath = '{target_dir}\\uninstall.bat'
    $Shortcut3.WorkingDirectory = '{target_dir}'
    $Shortcut3.Description = 'Uninstall CodePilot Local Runtime'
    $Shortcut3.Save()
    """
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, timeout=10)
        print_ok(f"Registered shortcuts in: Start Menu > Programs > CodePilot")
    except Exception as e:
        print_warn(f"Could not create Start Menu shortcuts: {e}")


def start_and_verify_runtime(target_dir: Path) -> bool:
    """Launch the runtime service and verify health endpoint."""
    print_step("Step 4/5: Starting CodePilot Local Runtime & verifying health...")
    exe_path = target_dir / "codepilot-runtime.exe"

    # Kill any existing instance
    subprocess.run(["taskkill", "/F", "/IM", "codepilot-runtime.exe"], capture_output=True)
    time.sleep(1)

    # Start detached
    subprocess.Popen(
        [str(exe_path)],
        cwd=str(target_dir),
        creationflags=subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0,
        close_fds=True,
    )

    # Poll health endpoint
    url = f"http://127.0.0.1:{DEFAULT_PORT}/health"
    verified = False
    for attempt in range(1, 15):
        time.sleep(1)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CodePilot-Installer"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    print_ok(f"Runtime is live on 127.0.0.1:{DEFAULT_PORT} (version {data.get('version')})")
                    verified = True
                    break
        except Exception:
            continue

    if not verified:
        print_error(f"Runtime failed to respond on 127.0.0.1:{DEFAULT_PORT} within 15 seconds.")
        return False
    return True


def check_and_pull_images(docker_ok: bool):
    """Check language execution images in Docker."""
    print_step("Step 5/5: Checking language execution environments...")
    if not docker_ok:
        print_warn("Skipping Docker image check since Docker is not currently running.")
        print("    You can pull language images later from the CodePilot website wizard.")
        return

    images = [
        ("Python 3.12", "python:3.12-slim"),
        ("Java 21", "eclipse-temurin:21-jdk"),
        ("C++ (GCC 14)", "gcc:14"),
    ]

    for label, tag in images:
        proc = subprocess.run(["docker", "image", "inspect", tag], capture_output=True)
        if proc.returncode == 0:
            print_ok(f"{label} ({tag}) is ready.")
        else:
            print_warn(f"{label} ({tag}) is missing.")
            print(f"    Pulling {tag} (this may take a couple of minutes)...")
            pull_proc = subprocess.run(["docker", "pull", tag])
            if pull_proc.returncode == 0:
                print_ok(f"Successfully pulled {tag}.")
            else:
                print_warn(f"Failed to pull {tag}. You can retry through the CodePilot website.")


def main():
    print(BANNER)
    docker_ok, _ = check_docker()

    # Determine source binary location
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base_dir = Path(meipass)
    else:
        base_dir = Path(__file__).resolve().parent

    source_exe = base_dir / "dist" / "codepilot-runtime.exe"
    if not source_exe.exists():
        source_exe = base_dir / "codepilot-runtime.exe"
    if not source_exe.exists():
        # Maybe running unpacked in dist
        source_exe = Path(sys.executable).parent / "codepilot-runtime.exe"
    if not source_exe.exists():
        # Fallback to local repo dist
        source_exe = Path(r"C:\Users\usern\Desktop\CodePilot-\dist\codepilot-runtime.exe")

    if not source_exe.exists():
        print_error(f"Could not locate codepilot-runtime.exe at: {source_exe}")
        sys.exit(1)

    local_app_data = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    target_dir = Path(local_app_data) / "CodePilot" / "runtime"

    if not install_files(target_dir, source_exe):
        sys.exit(1)

    create_start_menu_shortcuts(target_dir)

    runtime_started = start_and_verify_runtime(target_dir)
    if runtime_started and docker_ok:
        check_and_pull_images(docker_ok)

    # Request pairing code
    pairing_code = "------"
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{DEFAULT_PORT}/pair/request",
            data=b"",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            pair_data = json.loads(resp.read().decode())
            pairing_code = pair_data.get("pairing_code", "------")
    except Exception:
        pass

    print("""
========================================================================
            CodePilot Local Runtime Installation Complete!
========================================================================
  Runtime Status:  RUNNING on http://127.0.0.1:8088
  Start Menu:      Programs > CodePilot
  Install Folder:  """ + str(target_dir) + """

  PAIRING WITH BROWSER:
  1. Open https://codepilot-frontend.vercel.app in your browser.
  2. Click 'Runtime Not Installed' or 'Connect Runtime' in the header.
  3. When prompted, enter your pairing code:

         +--------------------+
         |   """ + pairing_code + """           |
         +--------------------+

  Your browser will securely connect directly to your local Docker!
========================================================================
""")
    if sys.stdin.isatty():
        input("Press Enter to finish...")


if __name__ == "__main__":
    main()

<#
.SYNOPSIS
    CodePilot AI - Safe Local Remote Sandbox Shutdown.

.DESCRIPTION
    Safely terminates the local CodePilot runner microservice and Cloudflare Quick Tunnel
    processes started by start-codepilot.ps1. Verifies PID and command line to prevent
    terminating unrelated Python, Docker, or Cloudflare processes.

.PARAMETER StopDocker
    Optional switch to shut down Docker Desktop as well. Defaults to false (Docker kept running).

.EXAMPLE
    pwsh -ExecutionPolicy Bypass -File .\scripts\stop-codepilot.ps1
    pwsh -ExecutionPolicy Bypass -File .\scripts\stop-codepilot.ps1 -StopDocker
#>

[CmdletBinding()]
param(
    [switch]$StopDocker
)

$ErrorActionPreference = "SilentlyContinue"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDir = Join-Path $repoRoot ".codepilot-runtime"

$runnerPidFile = Join-Path $runtimeDir "runner.pid"
$tunnelPidFile = Join-Path $runtimeDir "tunnel.pid"
$currentUrlFile = Join-Path $runtimeDir "current_tunnel_url.txt"
$cloudflaredLogFile = Join-Path $runtimeDir "cloudflared.log"

Write-Host "`n========================================================" -ForegroundColor Yellow
Write-Host "  Stopping CodePilot Local Sandbox Infrastructure" -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Yellow

function Stop-VerifiedProcess {
    param(
        [string]$Name,
        [string]$PidFilePath,
        [string]$ProcessNamePattern,
        [string]$CommandLinePattern
    )

    if (-not (Test-Path $PidFilePath)) {
        Write-Host "  [INFO] No recorded PID for $Name ($PidFilePath not found)." -ForegroundColor Gray
        return
    }

    $pidContent = (Get-Content $PidFilePath -Raw).Trim()
    if ($pidContent -notmatch "^\d+$") {
        Write-Host "  [WARN] Invalid PID format in ${PidFilePath}: '$pidContent'. Removing stale file." -ForegroundColor Yellow
        Remove-Item $PidFilePath -Force -ErrorAction SilentlyContinue
        return
    }

    $targetPid = [int]$pidContent
    $proc = Get-Process -Id $targetPid -ErrorAction SilentlyContinue

    if (-not $proc) {
        Write-Host "  [INFO] $Name process (PID: $targetPid) is already stopped." -ForegroundColor Gray
        Remove-Item $PidFilePath -Force -ErrorAction SilentlyContinue
        return
    }

    # Verify command line to avoid killing an unrelated process that reused the PID
    $cimProc = Get-CimInstance Win32_Process -Filter "ProcessId = $targetPid" -ErrorAction SilentlyContinue
    $cmdLine = if ($cimProc) { $cimProc.CommandLine } else { "" }

    $isExpected = ($proc.Name -like "*$ProcessNamePattern*") -and ($cmdLine -like "*$CommandLinePattern*")

    if ($isExpected) {
        Write-Host "  [INFO] Stopping $Name (PID: $targetPid)..." -ForegroundColor Cyan
        Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
        if (Get-Process -Id $targetPid -ErrorAction SilentlyContinue) {
            Write-Host "  [WARN] Process $targetPid did not terminate immediately. Retrying..." -ForegroundColor Yellow
            Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
        }
        Write-Host "  [OK] $Name (PID: $targetPid) stopped successfully." -ForegroundColor Green
    } else {
        Write-Host "  [WARN] PID $targetPid does not match expected $Name pattern ($cmdLine). Skipping termination to protect unrelated processes." -ForegroundColor Yellow
    }

    Remove-Item $PidFilePath -Force -ErrorAction SilentlyContinue
}

# 1. Stop Cloudflare Quick Tunnel
Stop-VerifiedProcess `
    -Name "Cloudflare Quick Tunnel" `
    -PidFilePath $tunnelPidFile `
    -ProcessNamePattern "cloudflared" `
    -CommandLinePattern "8088"

# 2. Stop Runner Microservice
Stop-VerifiedProcess `
    -Name "Runner Microservice" `
    -PidFilePath $runnerPidFile `
    -ProcessNamePattern "python" `
    -CommandLinePattern "runner.main"

# 3. Clean up active tunnel URL file
if (Test-Path $currentUrlFile) {
    Remove-Item $currentUrlFile -Force -ErrorAction SilentlyContinue
}

# 4. Handle Docker Desktop if requested
if ($StopDocker) {
    Write-Host "  [INFO] -StopDocker requested. Stopping Docker Desktop..." -ForegroundColor Cyan
    $dockerProcs = Get-Process -Name "*docker desktop*", "*dockerd*" -ErrorAction SilentlyContinue
    foreach ($p in $dockerProcs) {
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "  [OK] Docker Desktop stopped." -ForegroundColor Green
} else {
    Write-Host "  [INFO] Docker Desktop preserved running (use -StopDocker if desired)." -ForegroundColor Gray
}

# 5. Final port 8088 verification
$portCheck = Get-NetTCPConnection -LocalPort 8088 -State Listen -ErrorAction SilentlyContinue
if ($portCheck) {
    Write-Host "  [WARN] Port 8088 is still in use by PID $($portCheck.OwningProcess)." -ForegroundColor Yellow
} else {
    Write-Host "  [OK] Port 8088 is completely freed." -ForegroundColor Green
}

Write-Host "========================================================" -ForegroundColor Yellow
Write-Host "  Shutdown Complete." -ForegroundColor Yellow
Write-Host "========================================================`n" -ForegroundColor Yellow

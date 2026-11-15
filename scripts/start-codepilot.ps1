<#
.SYNOPSIS
    CodePilot AI - Zero-Cost Automated Startup & Quick Tunnel URL Synchronization.

.DESCRIPTION
    Automates local Docker check, isolated runner startup, Cloudflare Quick Tunnel
    establishment, URL extraction, and safe synchronization with the Vercel Preview backend.

.PARAMETER NonInteractive
    Skip interactive prompts; do not update Vercel without explicit ForceSync.

.PARAMETER ForceSync
    Automatically update Vercel Preview SANDBOX_RUNNER_URL and redeploy Preview without prompting.

.PARAMETER DryRun
    Perform preflights, health checks, and URL comparison without modifying Vercel or starting processes.

.PARAMETER Port
    Local port for the runner microservice (default: 8088).

.PARAMETER TunnelTimeoutSeconds
    Maximum time in seconds to wait for Cloudflare Quick Tunnel edge DNS propagation and health check (default: 90).

.EXAMPLE
    pwsh -ExecutionPolicy Bypass -File .\scripts\start-codepilot.ps1
    pwsh -ExecutionPolicy Bypass -File .\scripts\start-codepilot.ps1 -ForceSync
#>

[CmdletBinding()]
param(
    [switch]$NonInteractive,
    [switch]$ForceSync,
    [switch]$DryRun,
    [int]$Port = 8088,
    [int]$TunnelTimeoutSeconds = 90
)

$ErrorActionPreference = "Stop"

# Constants & Configuration
$EXPECTED_PROJECT_ID = "prj_mkFq7dLb0DlbZoIyqk4fWndY0Bn2"
$EXPECTED_PROJECT_NAME = "codepilot-backend"
$EXPECTED_ORG_ID = "team_xnLY8bJl2R0tfGUvkEIOIATY"
$EXPECTED_TEAM_NAME = "vanni-ai"
$STABLE_PREVIEW_DOMAIN = "codepilot-backend-preview.vercel.app"
$STABLE_PREVIEW_URL = "https://$STABLE_PREVIEW_DOMAIN"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDir = Join-Path $repoRoot ".codepilot-runtime"
$secretFile = Join-Path $repoRoot ".env.runner_secret"
$projectJsonFile = Join-Path $repoRoot "backend\.vercel\project.json"

$runnerPidFile = Join-Path $runtimeDir "runner.pid"
$tunnelPidFile = Join-Path $runtimeDir "tunnel.pid"
$currentUrlFile = Join-Path $runtimeDir "current_tunnel_url.txt"
$lastSyncedUrlFile = Join-Path $runtimeDir "last_synced_tunnel_url.txt"
$deploymentMetadataFile = Join-Path $runtimeDir "last_deployment.json"
$cloudflaredLogFile = Join-Path $runtimeDir "cloudflared.log"

function Write-Step {
    param([string]$Title)
    Write-Host "`n========================================================" -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host "========================================================" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "  [OK] $Message" -ForegroundColor Green
}

function Write-Info {
    param([string]$Message)
    Write-Host "  [INFO] $Message" -ForegroundColor Gray
}

function Write-WarnMsg {
    param([string]$Message)
    Write-Host "  [WARN] $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "  [ERROR] $Message" -ForegroundColor Red
    throw $Message
}

function Ensure-RuntimeDir {
    if (-not (Test-Path $runtimeDir)) {
        New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    }
}

$scriptStartedRunnerProc = $null
$scriptStartedTunnelProc = $null

function Cleanup-StartedProcesses {
    param([string]$Reason)
    Write-WarnMsg "Cleaning up processes started during this invocation ($Reason)..."

    if ($scriptStartedTunnelProc) {
        try {
            if (-not $scriptStartedTunnelProc.HasExited) {
                Write-Info "Stopping started Cloudflare tunnel process (PID: $($scriptStartedTunnelProc.Id))..."
                Stop-Process -Id $scriptStartedTunnelProc.Id -Force -ErrorAction SilentlyContinue
            }
        } catch {}
        if (Test-Path $tunnelPidFile) { Remove-Item $tunnelPidFile -Force -ErrorAction SilentlyContinue }
        if (Test-Path $currentUrlFile) { Remove-Item $currentUrlFile -Force -ErrorAction SilentlyContinue }
    }

    if ($scriptStartedRunnerProc) {
        try {
            if (-not $scriptStartedRunnerProc.HasExited) {
                Write-Info "Stopping started Runner microservice process (PID: $($scriptStartedRunnerProc.Id))..."
                Stop-Process -Id $scriptStartedRunnerProc.Id -Force -ErrorAction SilentlyContinue
            }
        } catch {}
        if (Test-Path $runnerPidFile) { Remove-Item $runnerPidFile -Force -ErrorAction SilentlyContinue }
    }
}

function Dump-CloudflaredDiagnostics {
    param(
        [string]$LastError,
        [System.Diagnostics.Process]$Proc
    )
    Write-Host "`n--------------------------------------------------------" -ForegroundColor Yellow
    Write-Host "  Cloudflare Quick Tunnel Failure Diagnostics" -ForegroundColor Yellow
    Write-Host "--------------------------------------------------------" -ForegroundColor Yellow
    if ($LastError) {
        Write-Host "  Last Health Check Failure: $LastError" -ForegroundColor Red
    }
    if ($Proc) {
        if ($Proc.HasExited) {
            Write-Host "  Tunnel Process Status: EXITED (ExitCode: $($Proc.ExitCode))" -ForegroundColor Red
        } else {
            Write-Host "  Tunnel Process Status: RUNNING (PID: $($Proc.Id))" -ForegroundColor Cyan
        }
    }
    if (Test-Path $cloudflaredLogFile) {
        Write-Host "  Recent entries from ${cloudflaredLogFile}:" -ForegroundColor Yellow
        $lines = Get-Content $cloudflaredLogFile -ErrorAction SilentlyContinue
        if ($lines) {
            $tail = $lines | Select-Object -Last 15
            foreach ($l in $tail) {
                Write-Host "    $l" -ForegroundColor Gray
            }
        } else {
            Write-Host "    <log file is empty>" -ForegroundColor Gray
        }
    } else {
        Write-Host "  Log file not found at: $cloudflaredLogFile" -ForegroundColor Gray
    }
    Write-Host "--------------------------------------------------------`n" -ForegroundColor Yellow
}

# ==============================================================================
# STAGE 1: Preflight Verification
# ==============================================================================
Write-Step "Stage 1: Preflight Verification"

# 1. OS check
if ($env:OS -notmatch "Windows") {
    Write-Fail "This startup script is designed for Windows 11 host environments."
}
Write-Success "Operating System: Windows ($($env:OS))"

# 2. Secret file check
if (-not (Test-Path $secretFile)) {
    Write-Fail "Runner secret file not found at: $secretFile. Please generate .env.runner_secret before starting."
}
$secretContent = Get-Content $secretFile -Raw -ErrorAction SilentlyContinue
if ($secretContent -notmatch "SANDBOX_RUNNER_SECRET=([0-9a-fA-F]{64})") {
    Write-Fail "Secret file exists but does not contain a valid 64-character hexadecimal SANDBOX_RUNNER_SECRET."
}
Write-Success "Runner secret file verified (.env.runner_secret present and valid)."

# 3. Project Identity check
if (-not (Test-Path $projectJsonFile)) {
    Write-Fail "Vercel project config not found at: $projectJsonFile."
}
try {
    $projJson = Get-Content $projectJsonFile -Raw | ConvertFrom-Json
    if ($projJson.projectId -ne $EXPECTED_PROJECT_ID) {
        Write-Fail "Vercel projectId mismatch! Expected: $EXPECTED_PROJECT_ID, Found: $($projJson.projectId). Aborting to protect unrelated projects."
    }
    if ($projJson.orgId -ne $EXPECTED_ORG_ID) {
        Write-Fail "Vercel orgId mismatch! Expected: $EXPECTED_ORG_ID, Found: $($projJson.orgId). Aborting to protect unrelated teams."
    }
    Write-Success "Vercel project verified ($EXPECTED_PROJECT_NAME / $EXPECTED_PROJECT_ID)."
} catch {
    Write-Fail "Failed to parse ${projectJsonFile}: $_"
}

# 4. CLI Tools Check
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCmd) {
    Write-Fail "Docker CLI is not found on PATH. Please install or add Docker to PATH."
}
Write-Success "Docker CLI found: $($dockerCmd.Source)"

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Fail "Python is not found on PATH."
}
$uvicornCheck = python -m uvicorn --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Uvicorn is not installed in the active Python environment ($uvicornCheck)."
}
Write-Success "Python & Uvicorn available ($($uvicornCheck.ToString().Trim()))."

# 5. Cloudflared check
$cloudflaredCmd = Get-Command cloudflared -ErrorAction SilentlyContinue
$cloudflaredPath = $null
if ($cloudflaredCmd) {
    $cloudflaredPath = $cloudflaredCmd.Source
} elseif (Test-Path "C:\Program Files (x86)\cloudflared\cloudflared.exe") {
    $cloudflaredPath = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
} elseif (Test-Path "C:\Program Files\cloudflared\cloudflared.exe") {
    $cloudflaredPath = "C:\Program Files\cloudflared\cloudflared.exe"
} else {
    Write-Fail "cloudflared is not installed or not in PATH. Install via: winget install --id Cloudflare.cloudflared -e"
}
$cloudflaredVer = & $cloudflaredPath --version 2>&1
Write-Success "Cloudflared found: $cloudflaredPath ($($cloudflaredVer.ToString().Trim()))"

# 6. Vercel CLI & Auth Check
$vercelCmd = Get-Command vercel -ErrorAction SilentlyContinue
if (-not $vercelCmd) {
    Write-Fail "Vercel CLI is not found on PATH. Please install globally via npm or nvm."
}
$vercelUser = (vercel whoami 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    Write-WarnMsg "Vercel CLI is not currently authenticated ($vercelUser). Local runner will start, but Vercel Preview synchronization will require manual login ('vercel login')."
} else {
    Write-Success "Vercel CLI authenticated as: $($vercelUser.ToString().Trim())"
}

Ensure-RuntimeDir

if ($DryRun) {
    Write-WarnMsg "DryRun mode enabled: skipping stage 2-6 live process execution."
}

# ==============================================================================
# STAGE 2: Ensure Docker Daemon Readiness
# ==============================================================================
Write-Step "Stage 2: Docker Daemon Health"

function Test-DockerDaemon {
    try {
        $info = docker info --format "{{.ServerVersion}}" 2>$null
        if ($LASTEXITCODE -eq 0 -and $info) {
            return $info.Trim()
        }
    } catch {}
    return $null
}

$dockerVersion = Test-DockerDaemon
if ($dockerVersion) {
    Write-Success "Docker daemon is running and healthy (Version: $dockerVersion)."
} else {
    Write-WarnMsg "Docker daemon is not running. Attempting to launch Docker Desktop..."
    
    $dockerExeLocations = @(
        "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe",
        "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    )
    $dockerExe = $dockerExeLocations | Where-Object { Test-Path $_ } | Select-Object -First 1
    
    if (-not $dockerExe) {
        Write-Fail "Docker Desktop executable not found in standard paths. Please launch Docker Desktop manually."
    }

    if (-not $DryRun) {
        Write-Info "Starting: $dockerExe"
        Start-Process -FilePath $dockerExe -NoNewWindow
        
        Write-Info "Waiting for Docker daemon to become responsive (up to 60s)..."
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        while ($sw.Elapsed.TotalSeconds -lt 60) {
            Start-Sleep -Seconds 3
            $dockerVersion = Test-DockerDaemon
            if ($dockerVersion) { break }
            Write-Host "." -NoNewline
        }
        Write-Host ""
        
        if (-not $dockerVersion) {
            Write-Fail "Docker daemon did not become ready within 60 seconds. Please check Docker Desktop status."
        }
        Write-Success "Docker daemon is ready (Version: $dockerVersion)."
    }
}

# ==============================================================================
# STAGE 3: Start or Reuse Local Sandbox Runner
# ==============================================================================
Write-Step "Stage 3: Local Runner Microservice (127.0.0.1:$Port)"

function Test-RunnerHealth {
    param([int]$CheckPort)
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$CheckPort/health" -Method Get -TimeoutSec 3 -ErrorAction Stop
        if ($resp.status -eq "ok" -and $resp.docker_available -eq $true) {
            return $resp
        }
    } catch {}
    return $null
}

$existingRunner = Test-RunnerHealth -CheckPort $Port
if ($existingRunner) {
    Write-Success "Existing runner microservice detected on 127.0.0.1:$Port (Docker: $($existingRunner.docker_version)). Reusing."
} else {
    # Check if port is occupied by unknown process
    $tcp = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($tcp) {
        $occupier = Get-CimInstance Win32_Process -Filter "ProcessId = $($tcp.OwningProcess)" -ErrorAction SilentlyContinue
        Write-Fail "Port $Port is occupied by PID $($tcp.OwningProcess) ($($occupier.Name)), but /health failed. Refusing to terminate unknown process. Please investigate or free port $Port."
    }

    if (-not $DryRun) {
        Write-Info "Starting CodePilot Runner on 127.0.0.1:$Port..."
        
        # Extract secret safely into process environment
        $secretLine = Get-Content $secretFile | Where-Object { $_ -match "^SANDBOX_RUNNER_SECRET=(.*)$" } | Select-Object -First 1
        $secretVal = $secretLine.Substring("SANDBOX_RUNNER_SECRET=".Length).Trim()
        
        $env:SANDBOX_RUNNER_SECRET = $secretVal
        $env:PYTHONPATH = "backend"

        $runnerProc = Start-Process -FilePath "python" `
            -ArgumentList "-m uvicorn runner.main:runner_app --app-dir backend --host 127.0.0.1 --port $Port" `
            -WorkingDirectory $repoRoot `
            -NoNewWindow `
            -PassThru

        $scriptStartedRunnerProc = $runnerProc

        # Clear secret from caller shell session
        $env:SANDBOX_RUNNER_SECRET = $null
        $secretVal = $null

        Set-Content -Path $runnerPidFile -Value $runnerProc.Id -Force
        Write-Info "Runner process started (PID: $($runnerProc.Id)). Waiting for health check..."

        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $runnerReady = $false
        while ($sw.Elapsed.TotalSeconds -lt 15) {
            Start-Sleep -Seconds 1
            $check = Test-RunnerHealth -CheckPort $Port
            if ($check) {
                $runnerReady = $true
                break
            }
        }

        if (-not $runnerReady) {
            Cleanup-StartedProcesses -Reason "Runner microservice failed health check within 15 seconds"
            Write-Fail "Runner started on PID $($runnerProc.Id) but failed to respond on 127.0.0.1:$Port/health within 15 seconds."
        }
        Write-Success "Runner microservice is healthy on 127.0.0.1:$Port."
    }
}

# Verify unauthenticated /execute rejects with 401
if (-not $DryRun) {
    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/execute" -Method Post -Body '{"code":"print(1)","language":"python"}' -ContentType "application/json" -TimeoutSec 3 -ErrorAction Stop
        Cleanup-StartedProcesses -Reason "Security violation: Local runner accepted unauthenticated execution"
        Write-Fail "Security violation: Local runner accepted unauthenticated execution!"
    } catch {
        if ($_.Exception.Response.StatusCode.value__ -eq 401) {
            Write-Success "Security verified: Unauthenticated execution on 127.0.0.1:$Port correctly rejected (HTTP 401)."
        } else {
            Write-WarnMsg "Unauthenticated execution returned HTTP $($_.Exception.Response.StatusCode.value__) instead of 401."
        }
    }
}

# ==============================================================================
# STAGE 4: Start or Reuse Cloudflare Quick Tunnel
# ==============================================================================
Write-Step "Stage 4: Cloudflare Quick Tunnel"

$tunnelUrl = $null

# Check if an existing tunnel is recorded and healthy
if (Test-Path $currentUrlFile) {
    $candidateUrl = (Get-Content $currentUrlFile -Raw).Trim()
    if ($candidateUrl -match "^https://[a-zA-Z0-9-]+\.trycloudflare\.com$") {
        try {
            $h = Invoke-RestMethod -Uri "$candidateUrl/health" -Method Get -TimeoutSec 4 -ErrorAction Stop
            if ($h.status -eq "ok") {
                $tunnelUrl = $candidateUrl
                Write-Success "Existing active Quick Tunnel detected: $tunnelUrl. Reusing."
            }
        } catch {}
    }
}

if (-not $tunnelUrl -and -not $DryRun) {
    # Check for stale tunnel PID or process before starting new tunnel
    if (Test-Path $tunnelPidFile) {
        $stalePidContent = (Get-Content $tunnelPidFile -Raw -ErrorAction SilentlyContinue).Trim()
        if ($stalePidContent -match "^\d+$") {
            $stalePid = [int]$stalePidContent
            $staleProc = Get-Process -Id $stalePid -ErrorAction SilentlyContinue
            if ($staleProc) {
                $cimProc = Get-CimInstance Win32_Process -Filter "ProcessId = $stalePid" -ErrorAction SilentlyContinue
                $cmdLine = if ($cimProc) { $cimProc.CommandLine } else { "" }
                if (($staleProc.Name -like "*cloudflared*") -and ($cmdLine -like "*$Port*")) {
                    Write-Info "Terminating stale Cloudflare tunnel process (PID: $stalePid)..."
                    Stop-Process -Id $stalePid -Force -ErrorAction SilentlyContinue
                    Start-Sleep -Milliseconds 500
                }
            }
        }
        Remove-Item $tunnelPidFile -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $currentUrlFile) {
        Remove-Item $currentUrlFile -Force -ErrorAction SilentlyContinue
    }

    Write-Info "Establishing new Cloudflare Quick Tunnel forwarding to 127.0.0.1:$Port..."
    
    # Clean previous tunnel log
    if (Test-Path $cloudflaredLogFile) { Remove-Item $cloudflaredLogFile -Force -ErrorAction SilentlyContinue }

    $tunnelProc = Start-Process -FilePath $cloudflaredPath `
        -ArgumentList "tunnel --url http://127.0.0.1:$Port" `
        -WorkingDirectory $repoRoot `
        -RedirectStandardError $cloudflaredLogFile `
        -NoNewWindow `
        -PassThru

    $scriptStartedTunnelProc = $tunnelProc
    Set-Content -Path $tunnelPidFile -Value $tunnelProc.Id -Force
    Write-Info "Tunnel process launched (PID: $($tunnelProc.Id)). Capturing assigned trycloudflare.com URL..."

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $extractedUrl = $null
    while ($sw.Elapsed.TotalSeconds -lt 30) {
        Start-Sleep -Seconds 1
        if ($tunnelProc.HasExited) {
            break
        }
        if (Test-Path $cloudflaredLogFile) {
            $logContent = Get-Content $cloudflaredLogFile -Raw -ErrorAction SilentlyContinue
            $matchesAll = [regex]::Matches($logContent, 'https://[a-zA-Z0-9-]+\.trycloudflare\.com')
            if ($matchesAll.Count -gt 0) {
                $extractedUrl = $matchesAll[$matchesAll.Count - 1].Value.Trim()
                break
            }
        }
    }

    if (-not $extractedUrl) {
        Dump-CloudflaredDiagnostics -LastError "Timed out waiting for trycloudflare.com URL in log" -Proc $tunnelProc
        Cleanup-StartedProcesses -Reason "Failed to capture trycloudflare.com URL within 30 seconds"
        Write-Fail "Failed to capture trycloudflare.com URL within 30 seconds. Inspect $cloudflaredLogFile for details."
    }

    # Strict URL validation
    if ($extractedUrl -notmatch "^https://[a-zA-Z0-9-]+\.trycloudflare\.com$") {
        Dump-CloudflaredDiagnostics -LastError "Extracted tunnel URL '$extractedUrl' failed security validation" -Proc $tunnelProc
        Cleanup-StartedProcesses -Reason "Extracted tunnel URL failed security validation"
        Write-Fail "Extracted tunnel URL '$extractedUrl' failed security validation (must be HTTPS on trycloudflare.com)."
    }

    Write-Success "Quick Tunnel URL assigned: $extractedUrl"

    # Verify public tunnel connectivity with sensible retries and configurable timeout
    Write-Info "Verifying public tunnel connectivity (timeout: ${TunnelTimeoutSeconds}s)..."
    $tunnelHealthy = $false
    $lastError = $null
    $healthSw = [System.Diagnostics.Stopwatch]::StartNew()
    $attempt = 0

    while ($healthSw.Elapsed.TotalSeconds -lt $TunnelTimeoutSeconds) {
        $attempt++
        if ($tunnelProc.HasExited) {
            $lastError = "cloudflared process terminated unexpectedly (ExitCode: $($tunnelProc.ExitCode))"
            break
        }

        try {
            $h = Invoke-RestMethod -Uri "$extractedUrl/health" -Method Get -TimeoutSec 4 -ErrorAction Stop
            if ($h.status -eq "ok") {
                $tunnelHealthy = $true
                break
            }
        } catch {
            $lastError = $_.Exception.Message
            $elapsed = [math]::Round($healthSw.Elapsed.TotalSeconds)
            
            # Flush local DNS cache if "No such host is known" to avoid waiting out Windows DNS negative cache
            if ($lastError -match "No such host is known") {
                Clear-DnsClientCache -ErrorAction SilentlyContinue
            }

            if ($attempt -eq 1 -or $attempt % 4 -eq 0 -or $elapsed -ge 15) {
                Write-Host "  ... Waiting for Cloudflare DNS & edge routing (${elapsed}s / ${TunnelTimeoutSeconds}s) [Last: $lastError]" -ForegroundColor DarkGray
            }
            Start-Sleep -Seconds 2
        }
    }

    if (-not $tunnelHealthy) {
        Dump-CloudflaredDiagnostics -LastError $lastError -Proc $tunnelProc
        Cleanup-StartedProcesses -Reason "Public tunnel failed health check within ${TunnelTimeoutSeconds} seconds"
        Write-Fail "Public tunnel at $extractedUrl failed health check within ${TunnelTimeoutSeconds} seconds. Last error: $lastError"
    }

    Write-Success "Public tunnel is healthy and routing traffic to 127.0.0.1:$Port."

    # Verify public unauthenticated /execute
    try {
        $null = Invoke-RestMethod -Uri "$extractedUrl/execute" -Method Post -Body '{"code":"print(1)","language":"python"}' -ContentType "application/json" -TimeoutSec 5 -ErrorAction Stop
        Dump-CloudflaredDiagnostics -LastError "Security violation: Public tunnel accepted unauthenticated execution!" -Proc $tunnelProc
        Cleanup-StartedProcesses -Reason "Security violation: Public tunnel accepted unauthenticated execution"
        Write-Fail "Security violation: Public tunnel accepted unauthenticated execution!"
    } catch {
        if ($_.Exception.Response.StatusCode.value__ -eq 401) {
            Write-Success "Security verified: Public tunnel correctly enforces HMAC authentication (HTTP 401)."
        } else {
            Write-WarnMsg "Public tunnel unauthenticated execution returned HTTP $($_.Exception.Response.StatusCode.value__) instead of 401."
        }
    }

    $tunnelUrl = $extractedUrl
    Set-Content -Path $currentUrlFile -Value $tunnelUrl -Force
}

# ==============================================================================
# STAGE 5: Compare Quick Tunnel URL with Vercel Preview
# ==============================================================================
Write-Step "Stage 5: Preview URL Synchronization Assessment"

$lastSyncedUrl = $null
if (Test-Path $lastSyncedUrlFile) {
    $lastSyncedUrl = (Get-Content $lastSyncedUrlFile -Raw).Trim()
}

Write-Info "Current Tunnel URL:      $tunnelUrl"
Write-Info "Last Synchronized URL:   $(if ($lastSyncedUrl) { $lastSyncedUrl } else { '<None / Initial>' })"

$needSync = ($tunnelUrl -ne $lastSyncedUrl)

if (-not $needSync) {
    Write-Success "Current Quick Tunnel URL matches the deployed Preview configuration. No Vercel deployment required."
} else {
    Write-WarnMsg "Quick Tunnel URL has changed or is not yet synchronized with Vercel Preview!"
    Write-Host "    Old Preview URL: $(if ($lastSyncedUrl) { $lastSyncedUrl } else { '<None / Initial>' })" -ForegroundColor Yellow
    Write-Host "    New Tunnel URL:  $tunnelUrl" -ForegroundColor Yellow
    Write-Host "    Action Needed:   Update SANDBOX_RUNNER_URL on Vercel Preview and trigger a Preview redeployment.`n" -ForegroundColor Yellow

    $doSync = $false
    if ($ForceSync) {
        $doSync = $true
        Write-Info "ForceSync flag set; proceeding with automatic synchronization."
    } elseif ($NonInteractive) {
        Write-WarnMsg "NonInteractive mode set and ForceSync not specified. Skipping Vercel synchronization."
    } else {
        $prompt = Read-Host "Do you want to update Vercel Preview SANDBOX_RUNNER_URL and redeploy Preview now? [y/N]"
        if ($prompt -match "^[yY](es)?$") {
            $doSync = $true
        } else {
            Write-Info "Synchronization declined by user. Local runner and tunnel remain available."
        }
    }

    if ($doSync -and -not $DryRun) {
        # ==============================================================================
        # STAGE 6: Synchronize Vercel Preview & Redeploy
        # ==============================================================================
        Write-Step "Stage 6: Synchronizing Vercel Preview Deployment"

        # Validate directory and project identity
        Set-Location (Join-Path $repoRoot "backend")
        
        Write-Info "Updating SANDBOX_RUNNER_URL in Vercel Preview environment..."
        $envUpdateOutput = vercel env add SANDBOX_RUNNER_URL --environment preview --value "$tunnelUrl" --force --yes --no-sensitive 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "Failed to update SANDBOX_RUNNER_URL in Vercel: $envUpdateOutput"
        }
        Write-Success "Vercel Preview SANDBOX_RUNNER_URL updated to: $tunnelUrl"

        # Deploy Preview
        Write-Info "Triggering Vercel Preview redeployment (Preview target only)..."
        $deployOutput = vercel deploy --yes 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "Vercel Preview deployment failed: $deployOutput"
        }

        # Extract deployment URL
        $newDeployUrl = $null
        foreach ($line in ($deployOutput -split "`n")) {
            if ($line -match "https://(codepilot-backend-[a-zA-Z0-9-]+-vanni-ai\.vercel\.app)") {
                $newDeployUrl = $matches[0].Trim()
                break
            }
        }

        if (-not $newDeployUrl) {
            Write-Fail "Could not parse new deployment URL from Vercel output: $deployOutput"
        }
        Write-Success "New Preview deployment ready: $newDeployUrl"

        # Assign stable preview alias
        Write-Info "Assigning stable alias $STABLE_PREVIEW_DOMAIN to $newDeployUrl..."
        $aliasOutput = vercel alias set $newDeployUrl $STABLE_PREVIEW_DOMAIN 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "Failed to set stable preview alias: $aliasOutput"
        }
        Write-Success "Stable preview alias assigned: $STABLE_PREVIEW_URL"

        # Save synchronization state
        Set-Content -Path $lastSyncedUrlFile -Value $tunnelUrl -Force
        $meta = @{
            synchronized_at = (Get-Date).ToString("o")
            tunnel_url = $tunnelUrl
            deployment_url = $newDeployUrl
            alias = $STABLE_PREVIEW_URL
        } | ConvertTo-Json
        Set-Content -Path $deploymentMetadataFile -Value $meta -Force
        
        Set-Location $repoRoot
    }
}

# ==============================================================================
# STAGE 7: Final Verification & Status Report
# ==============================================================================
Write-Step "Stage 7: Final Infrastructure Health Verification"

# Retain active processes on successful execution
$scriptStartedRunnerProc = $null
$scriptStartedTunnelProc = $null

$previewHealthy = $false
try {
    $prevHealth = Invoke-RestMethod -Uri "$STABLE_PREVIEW_URL/api/health" -Method Get -TimeoutSec 5 -ErrorAction Stop
    if ($prevHealth.status -eq "healthy" -and $prevHealth.database -eq "ok" -and $prevHealth.environment -eq "preview") {
        $previewHealthy = $true
    }
} catch {
    Write-WarnMsg "Could not query stable preview endpoint: $_"
}

Write-Host "`n========================================================" -ForegroundColor Green
Write-Host "  CodePilot Remote Sandbox Status Report" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
Write-Host "  Docker Daemon:          Ready ($dockerVersion)" -ForegroundColor White
Write-Host "  Local Runner:           Active (http://127.0.0.1:$Port)" -ForegroundColor White
Write-Host "  Cloudflare Quick Tunnel: Active ($tunnelUrl)" -ForegroundColor White
Write-Host "  Vercel Backend Preview: $(if ($previewHealthy) { "$STABLE_PREVIEW_URL (Healthy)" } else { "$STABLE_PREVIEW_URL (Unverified)" })" -ForegroundColor White
Write-Host "  Sync Status:            $(if ($needSync) { "Updated & Redeployed" } else { "Up to date (No redeploy needed)" })" -ForegroundColor White
Write-Host "========================================================`n" -ForegroundColor Green

Write-Info "To stop the local runner and tunnel when finished, run:"
Write-Host "  pwsh -ExecutionPolicy Bypass -File .\scripts\stop-codepilot.ps1`n" -ForegroundColor Cyan

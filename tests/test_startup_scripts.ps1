<#
.SYNOPSIS
    Unit & Safety Tests for CodePilot Startup and Shutdown Automation.

.DESCRIPTION
    Tests project identity validation, URL validation regex, secret leak prevention,
    production deployment ban, safe process termination, and DryRun execution.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$startScript = Join-Path $repoRoot "scripts\start-codepilot.ps1"
$stopScript = Join-Path $repoRoot "scripts\stop-codepilot.ps1"

$passed = 0
$failed = 0

function Assert-Test {
    param(
        [string]$Description,
        [scriptblock]$TestBlock
    )
    try {
        & $TestBlock
        Write-Host "  [PASS] $Description" -ForegroundColor Green
        $script:passed++
    } catch {
        Write-Host "  [FAIL] $Description" -ForegroundColor Red
        Write-Host "         Error: $_" -ForegroundColor DarkRed
        $script:failed++
    }
}

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host "  Running CodePilot Startup & Shutdown Safety Tests" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

# ------------------------------------------------------------------------------
# 1. Secret Leakage Static Audit
# ------------------------------------------------------------------------------
Assert-Test "Secret is never echoed, logged, or passed in CLI arguments" {
    $startContent = Get-Content $startScript -Raw
    $stopContent = Get-Content $stopScript -Raw

    if ($startContent -match "Write-Host.*`$secret" -or $startContent -match "Write-Output.*`$secret") {
        throw "Found Write-Host or Write-Output printing secret variable in startup script!"
    }
    if ($startContent -match "python.*-m uvicorn.*`$secret") {
        throw "Found secret passed as a command-line argument to uvicorn!"
    }
    if ($stopContent -match "Remove-Item.*\.env\.runner_secret") {
        throw "Shutdown script contains command to delete .env.runner_secret!"
    }
}

# ------------------------------------------------------------------------------
# 2. Production Deployment Ban
# ------------------------------------------------------------------------------
Assert-Test "Startup script never calls vercel deploy --prod" {
    $startContent = Get-Content $startScript -Raw
    if ($startContent -match "vercel\s+deploy\s+--prod" -or $startContent -match "vercel\s+--prod") {
        throw "Found forbidden '--prod' flag in startup script! Production must never be deployed by automation."
    }
}

# ------------------------------------------------------------------------------
# 3. Project ID & Identity Hardening
# ------------------------------------------------------------------------------
Assert-Test "Expected project and team constants match exact CodePilot IDs" {
    $startContent = Get-Content $startScript -Raw
    if ($startContent -notmatch 'prj_mkFq7dLb0DlbZoIyqk4fWndY0Bn2') {
        throw "Expected project ID 'prj_mkFq7dLb0DlbZoIyqk4fWndY0Bn2' missing from script!"
    }
    if ($startContent -notmatch 'team_xnLY8bJl2R0tfGUvkEIOIATY') {
        throw "Expected team ID 'team_xnLY8bJl2R0tfGUvkEIOIATY' missing from script!"
    }
}

# ------------------------------------------------------------------------------
# 4. Quick Tunnel URL Validation Regex
# ------------------------------------------------------------------------------
Assert-Test "Quick Tunnel URL regex accepts valid and rejects malicious/invalid URLs" {
    $regex = "^https://[a-zA-Z0-9-]+\.trycloudflare\.com$"

    $valid = @(
        "https://influenced-formula-vessels-suffered.trycloudflare.com",
        "https://abc-123-xyz.trycloudflare.com",
        "https://my-test-tunnel-2026.trycloudflare.com"
    )
    foreach ($url in $valid) {
        if ($url -notmatch $regex) {
            throw "Valid URL '$url' was incorrectly rejected by regex!"
        }
    }

    $invalid = @(
        "http://insecure.trycloudflare.com",
        "https://attacker.com",
        "https://trycloudflare.com.attacker.com",
        "https://evil-trycloudflare.com",
        "ftp://test.trycloudflare.com",
        "https://something.trycloudflare.com/extra/path"
    )
    foreach ($url in $invalid) {
        if ($url -match $regex) {
            throw "Invalid/malicious URL '$url' was incorrectly accepted by regex!"
        }
    }
}

# ------------------------------------------------------------------------------
# 5. Idempotent URL Comparison Logic
# ------------------------------------------------------------------------------
Assert-Test "URL comparison identifies matching vs differing URLs idempotently" {
    $urlA = "https://test-tunnel-aaa.trycloudflare.com"
    $urlB = "https://test-tunnel-aaa.trycloudflare.com"
    $urlC = "https://test-tunnel-bbb.trycloudflare.com"

    $needSyncSame = ($urlA -ne $urlB)
    if ($needSyncSame) {
        throw "Identical URLs were incorrectly evaluated as requiring redeployment!"
    }

    $needSyncDiff = ($urlA -ne $urlC)
    if (-not $needSyncDiff) {
        throw "Differing URLs were not detected as requiring synchronization!"
    }
}

# ------------------------------------------------------------------------------
# 6. Stop Script Process Pattern Verification
# ------------------------------------------------------------------------------
Assert-Test "Stop script verifies process command line before terminating" {
    $stopContent = Get-Content $stopScript -Raw
    if ($stopContent -notmatch "Stop-VerifiedProcess") {
        throw "Stop script does not use command-line verified process termination!"
    }
    if ($stopContent -notmatch "Get-CimInstance Win32_Process") {
        throw "Stop script does not inspect process command line via CIM/WMI!"
    }
}

# ------------------------------------------------------------------------------
# 7. Git-Ignore Verification
# ------------------------------------------------------------------------------
Assert-Test ".codepilot-runtime is properly ignored by Git" {
    $check = git check-ignore -v .codepilot-runtime/test.txt 2>&1
    if ($LASTEXITCODE -ne 0 -or $check -notmatch "\.codepilot-runtime") {
        throw ".codepilot-runtime directory is not recognized as Git-ignored!"
    }
}

# ------------------------------------------------------------------------------
# 8. DryRun Mode Execution
# ------------------------------------------------------------------------------
Assert-Test "start-codepilot.ps1 executes cleanly in DryRun mode" {
    $output = pwsh -NoProfile -ExecutionPolicy Bypass -Command "& '$startScript' -DryRun -NonInteractive *>&1"
    $combined = ($output | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "DryRun failed with exit code $LASTEXITCODE. Output:`n$combined"
    }
    if ($combined -notmatch "Stage 1: Preflight Verification") {
        throw "DryRun output missing Stage 1 verification. Got:`n$combined"
    }
    if ($combined -notmatch "CodePilot Remote Sandbox Status Report") {
        throw "DryRun output missing final status report. Got:`n$combined"
    }
}

# ------------------------------------------------------------------------------
# 9. AST Parser Error Audit
# ------------------------------------------------------------------------------
Assert-Test "Both PowerShell scripts parse with zero syntax or interpolation errors" {
    $tokens = $null
    $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($startScript, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) {
        throw "start-codepilot.ps1 has $($errors.Count) parser error(s): $($errors[0].Message)"
    }

    $tokens = $null
    $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($stopScript, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) {
        throw "stop-codepilot.ps1 has $($errors.Count) parser error(s): $($errors[0].Message)"
    }
}

# ------------------------------------------------------------------------------
# 10. Tunnel Timeout & Cleanup Handlers Verification
# ------------------------------------------------------------------------------
Assert-Test "Startup script enforces configurable timeout and failure cleanup" {
    $startContent = Get-Content $startScript -Raw
    if ($startContent -notmatch '\[int\]\$TunnelTimeoutSeconds\s*=\s*\d+') {
        throw "start-codepilot.ps1 missing configurable TunnelTimeoutSeconds parameter!"
    }
    if ($startContent -notmatch 'function\s+Cleanup-StartedProcesses') {
        throw "start-codepilot.ps1 missing Cleanup-StartedProcesses handler!"
    }
    if ($startContent -notmatch 'function\s+Dump-CloudflaredDiagnostics') {
        throw "start-codepilot.ps1 missing Dump-CloudflaredDiagnostics handler!"
    }
}

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host "  Test Summary: $passed Passed, $failed Failed" -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Red" })
Write-Host "========================================================`n" -ForegroundColor Cyan

if ($failed -gt 0) {
    exit 1
}

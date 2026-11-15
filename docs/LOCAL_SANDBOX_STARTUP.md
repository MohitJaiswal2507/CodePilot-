# CodePilot Local Sandbox Infrastructure — Automated Startup & Synchronization

This document explains how to start, monitor, synchronize, and shut down the CodePilot remote Docker execution engine on a Windows 11 host with **zero monthly hosting costs**.

---

## Architecture Overview

```
[Browser: https://codepilot-frontend.vercel.app]
                      │
                      ▼ (Neon Auth JWT)
[Vercel Preview Backend: https://codepilot-backend-preview.vercel.app]
                      │
                      ▼ (HMAC-SHA256 Signed HTTP Request)
[Cloudflare Quick Tunnel: https://*.trycloudflare.com]
                      │ (Outbound QUIC tunnel)
                      ▼
[Local Runner Microservice: http://127.0.0.1:8088]
                      │ (HMAC Verified + Anti-Replay + 256KB Boundary)
                      ▼
[Isolated Docker Container Engine: python:3.12-slim, temurin:21, gcc:14]
```

- **Cost**: ₹0 / month (uses free Cloudflare Quick Tunnels and your local Docker daemon).
- **Security**: Port 8088 binds **strictly to `127.0.0.1`**. No ports are forwarded on your router.
- **HMAC Authentication**: Public requests to `/execute` require a 256-bit cryptographically secure HMAC signature and fresh timestamp ($\le 30$s).

---

## Quick Start Commands

### 1. Start the Remote Sandbox
From the repository root in PowerShell:
```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\start-codepilot.ps1
```
*(Or in Windows PowerShell 5.1: `powershell -ExecutionPolicy Bypass -File .\scripts\start-codepilot.ps1`)*

### 2. Stop the Remote Sandbox
```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\stop-codepilot.ps1
```
*(To also close Docker Desktop when finished, pass the `-StopDocker` switch: `.\scripts\stop-codepilot.ps1 -StopDocker`)*

---

## What the Startup Script Does (7 Automated Stages)

1. **Preflight Checks**:
   - Verifies Windows environment, Docker CLI, Python, Uvicorn, Cloudflared, and Vercel CLI.
   - Verifies `.env.runner_secret` exists and contains a valid 64-hexadecimal secret without printing it.
   - Verifies `backend/.vercel/project.json` matches project `codepilot-backend` (`prj_mkFq7dLb0DlbZoIyqk4fWndY0Bn2`) to protect all other projects.
2. **Docker Readiness**:
   - Checks if Docker daemon is responsive. If stopped, automatically launches Docker Desktop and waits up to 60 seconds for readiness.
3. **Local Runner Microservice**:
   - Checks `127.0.0.1:8088/health`. If already healthy, reuses it.
   - If not running, launches Uvicorn (`runner.main:runner_app`) with `PYTHONPATH=backend` and stores the PID in `.codepilot-runtime/runner.pid`.
   - Rejects execution on `0.0.0.0`.
4. **Cloudflare Quick Tunnel**:
   - Checks for an active tunnel. If healthy, reuses it.
   - If starting fresh, launches `cloudflared tunnel --url http://127.0.0.1:8088`.
   - Parses the generated `https://[name].trycloudflare.com` URL.
   - Tests public `/health` (`200 OK`) and unauthenticated `/execute` (`401 Unauthorized`).
5. **URL Synchronization Check**:
   - Compares the assigned tunnel URL with the last synchronized URL in `.codepilot-runtime/last_synced_tunnel_url.txt`.
   - **If identical**: Skips Vercel update and redeployment.
   - **If changed**: Explains that the URL changed and asks for confirmation:
     ```text
     Do you want to update Vercel Preview SANDBOX_RUNNER_URL and redeploy Preview now? [y/N]
     ```
     *(Use `-ForceSync` to automate without prompting)*.
6. **Preview-Only Deployment**:
   - Updates `SANDBOX_RUNNER_URL` in Vercel **Preview environment only** (Production is never touched).
   - Triggers `vercel deploy --yes` (Preview deployment).
   - Re-attaches the stable alias: `https://codepilot-backend-preview.vercel.app`.
7. **Final Verification**:
   - Verifies local runner, public tunnel, backend Preview `/api/health`, and database status.

---

## First-Time Setup Requirements

1. **Vercel CLI Authentication**:
   Ensure you are logged into Vercel CLI:
   ```powershell
   vercel whoami
   # If not logged in:
   vercel login
   ```
2. **Docker Desktop**:
   Ensure Docker Desktop is installed and configured for Linux containers (WSL 2 backend).
3. **Windows Clock Synchronization**:
   Ensure your Windows clock is synchronized via **Settings** $\rightarrow$ **Time & Language** $\rightarrow$ **Date & time** $\rightarrow$ **Sync now**. This ensures timestamps match Vercel's UTC clock within the 30-second HMAC window.

---

## Frequently Asked Questions & Troubleshooting

### Why does a changed Quick Tunnel URL require a Preview redeployment?
Because Cloudflare Quick Tunnels generate ephemeral URLs on startup (e.g. `https://random-words.trycloudflare.com`), Vercel Preview's serverless backend must know the new URL (`SANDBOX_RUNNER_URL`) to forward execution requests. In serverless environments, updating environment variables requires a new deployment to take effect.

### What happens when my laptop goes to sleep or network reconnects?
- The Cloudflare Quick Tunnel connection closes.
- If the frontend attempts code execution while the laptop is asleep, the backend returns `HTTP 503` with notice:
  `"Code execution sandbox infrastructure is currently unavailable."`
- When you wake the laptop, run `.\scripts\start-codepilot.ps1`. If Cloudflare assigns a new URL, confirm the prompt to update Vercel Preview.

### How to troubleshoot HTTP 503?
1. Run `.\scripts\start-codepilot.ps1` to check health across all stages.
2. If the runner logs report `timestamp skew too large (> 30s)`:
   - Sync your Windows clock (**Settings $\rightarrow$ Date & time $\rightarrow$ Sync now**).
3. If the runner logs report `HMAC signature mismatch`:
   - Verify that `.env.runner_secret` has not been regenerated or mismatched with Vercel Preview's `SANDBOX_RUNNER_SECRET`.
4. If Docker reports daemon offline:
   - Ensure Docker Desktop is running and WSL2 is responsive.

### How are background processes tracked and cleaned?
Process IDs are tracked in the `.codepilot-runtime/` directory:
- `.codepilot-runtime/runner.pid`
- `.codepilot-runtime/tunnel.pid`
- `.codepilot-runtime/current_tunnel_url.txt`
- `.codepilot-runtime/last_synced_tunnel_url.txt`

When `.\scripts\stop-codepilot.ps1` is run, it checks the PID against `Win32_Process` to ensure it only terminates the specific python runner and cloudflared processes, leaving all other programs untouched.

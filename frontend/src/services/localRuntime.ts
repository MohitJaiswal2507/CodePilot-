/**
 * CodePilot Local Runtime Client
 *
 * Connects directly to the user's local CodePilot Runtime daemon running at
 * http://127.0.0.1:8088. Enables 100% client-side Docker code execution on the
 * user's personal machine, eliminating any cloud sandbox dependency.
 */

import { ExecutionResult, SandboxLanguage } from "@/services/api";

export const LOCAL_RUNTIME_PORT = 8088;
export const LOCAL_RUNTIME_BASE_URL = `http://127.0.0.1:${LOCAL_RUNTIME_PORT}`;
export const LOCAL_RUNTIME_TOKEN_KEY = "codepilot_local_runtime_token";

export interface LocalRuntimeHealth {
  status: "ok" | "unhealthy" | "offline";
  service: string;
  version: string;
  docker_available: boolean;
  docker_version: string | null;
  paired: boolean;
  pairing_active: boolean;
  os: string;
  latencyMs?: number;
}

export interface LocalRuntimeStatus {
  runtime_version: string;
  os: string;
  arch: string;
  docker: {
    available: boolean;
    version: string | null;
  };
  languages: {
    images: Record<
      string,
      {
        installed: boolean;
        tag: string;
        size_mb?: number;
      }
    >;
    all_ready: boolean;
    missing: string[];
  };
  paired: boolean;
}

export interface PairRequestResult {
  pairing_code: string;
  expires_in_seconds: number;
  message: string;
}

export interface PairConfirmResult {
  status: "paired";
  session_token: string;
  token_prefix: string;
  version: string;
}

export type PlatformType = "windows" | "mac" | "linux" | "mobile" | "unknown";

/**
 * Detect client operating system from navigator userAgent/platform.
 */
export function detectClientPlatform(): PlatformType {
  if (typeof window === "undefined" || !navigator) return "unknown";

  const userAgent = navigator.userAgent || "";
  const platform = (navigator as unknown as { userAgentData?: { platform?: string } }).userAgentData?.platform || navigator.platform || "";

  // Mobile detection
  if (/Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(userAgent)) {
    return "mobile";
  }

  // Desktop OS detection
  if (/Win/i.test(platform) || /Windows/i.test(userAgent)) {
    return "windows";
  }
  if (/Mac/i.test(platform) || /Macintosh/i.test(userAgent)) {
    return "mac";
  }
  if (/Linux/i.test(platform) || /Linux/i.test(userAgent)) {
    return "linux";
  }

  return "unknown";
}

/**
 * Get stored session token from localStorage.
 */
export function getLocalRuntimeToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(LOCAL_RUNTIME_TOKEN_KEY);
  } catch {
    return null;
  }
}

/**
 * Set session token in localStorage.
 */
export function setLocalRuntimeToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(LOCAL_RUNTIME_TOKEN_KEY, token);
  } catch {
    // ignore
  }
}

/**
 * Remove session token from localStorage.
 */
export function removeLocalRuntimeToken(): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(LOCAL_RUNTIME_TOKEN_KEY);
  } catch {
    // ignore
  }
}

/**
 * Check if the local runtime is running and responsive.
 * Uses a short timeout (2000ms) to avoid hanging UI.
 */
export async function checkLocalRuntimeHealth(
  timeoutMs: number = 2000
): Promise<LocalRuntimeHealth | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const start = performance.now();

  try {
    const res = await fetch(`${LOCAL_RUNTIME_BASE_URL}/health`, {
      method: "GET",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
      },
    });

    const elapsed = Math.round(performance.now() - start);

    if (res.ok) {
      const data = await res.json();
      return {
        ...data,
        latencyMs: elapsed,
      };
    }
    return null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Retrieve comprehensive status (Docker engine status, installed images, OS info).
 */
export async function getLocalRuntimeStatus(
  timeoutMs: number = 3000
): Promise<LocalRuntimeStatus | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${LOCAL_RUNTIME_BASE_URL}/status`, {
      method: "GET",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
      },
    });

    if (res.ok) {
      return await res.json();
    }
    return null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Request a new one-time 6-digit pairing code from the local runtime.
 */
export async function requestLocalPairingCode(): Promise<PairRequestResult> {
  const res = await fetch(`${LOCAL_RUNTIME_BASE_URL}/pair/request`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Pairing request failed." }));
    throw new Error(err.detail || "Failed to generate pairing code.");
  }

  return await res.json();
}

/**
 * Confirm pairing with a 6-digit code, receiving and persisting session token.
 */
export async function confirmLocalPairing(pairingCode: string): Promise<PairConfirmResult> {
  const cleanCode = pairingCode.trim();
  const res = await fetch(`${LOCAL_RUNTIME_BASE_URL}/pair/confirm`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({ pairing_code: cleanCode }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Pairing verification failed." }));
    throw new Error(err.detail || "Invalid or expired pairing code.");
  }

  const data: PairConfirmResult = await res.json();
  if (data.session_token) {
    setLocalRuntimeToken(data.session_token);
  }
  return data;
}

/**
 * Disconnect local runtime, invalidating session token on server and clearing localStorage.
 */
export async function disconnectLocalRuntime(): Promise<void> {
  const token = getLocalRuntimeToken();
  if (token) {
    try {
      await fetch(`${LOCAL_RUNTIME_BASE_URL}/disconnect`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      });
    } catch {
      // ignore network errors on disconnect
    }
  }
  removeLocalRuntimeToken();
}

/**
 * Trigger Docker image pull on the local machine for a specific language environment.
 */
export async function pullDockerImageLocally(
  imageTag: string
): Promise<{ status: string; image: string }> {
  const token = getLocalRuntimeToken();
  if (!token) {
    throw new Error("Local runtime is not paired. Please pair your browser first.");
  }

  const res = await fetch(`${LOCAL_RUNTIME_BASE_URL}/docker/pull`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({ image: imageTag }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to pull Docker image." }));
    throw new Error(err.detail || `Failed to pull ${imageTag}.`);
  }

  return await res.json();
}

/**
 * Execute code inside local Docker engine via Local Runtime daemon.
 */
export async function executeCodeLocally(payload: {
  code: string;
  language: SandboxLanguage;
  stdin?: string | null;
  timeout?: number;
}): Promise<ExecutionResult> {
  const token = getLocalRuntimeToken();
  if (!token) {
    throw new Error("Local runtime is not paired. Please connect your local runtime.");
  }

  const res = await fetch(`${LOCAL_RUNTIME_BASE_URL}/execute`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      code: payload.code,
      language: payload.language,
      stdin: payload.stdin || null,
      custom_timeout: payload.timeout,
    }),
  });

  if (!res.ok) {
    if (res.status === 401) {
      removeLocalRuntimeToken();
      throw new Error("Local runtime session expired. Please pair again.");
    }
    const err = await res.json().catch(() => ({ detail: "Execution failed on local runtime." }));
    throw new Error(err.detail || `Local runtime execution error (${res.status})`);
  }

  return await res.json();
}

export interface HealthStatus {
  status: "healthy" | "unhealthy" | "offline";
  service: string;
  version: string;
  environment: string;
  timestamp: string;
  latencyMs?: number;
  error?: string;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function fetchBackendHealth(): Promise<HealthStatus> {
  const startTime = performance.now();
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 4000);

    const response = await fetch(`${API_BASE_URL}/api/health`, {
      method: "GET",
      signal: controller.signal,
      headers: {
        "Accept": "application/json",
      },
      cache: "no-store",
    });

    clearTimeout(timeoutId);
    const latencyMs = Math.round(performance.now() - startTime);

    if (!response.ok) {
      return {
        status: "unhealthy",
        service: "CodePilot AI Backend",
        version: "unknown",
        environment: "unknown",
        timestamp: new Date().toISOString(),
        latencyMs,
        error: `HTTP ${response.status}: ${response.statusText}`,
      };
    }

    const data = await response.json();
    return {
      ...data,
      latencyMs,
    };
  } catch (err: unknown) {
    const latencyMs = Math.round(performance.now() - startTime);
    const errorMessage = err instanceof Error ? err.message : "Failed to connect to backend server";
    return {
      status: "offline",
      service: "CodePilot AI Backend",
      version: "0.1.0",
      environment: "development",
      timestamp: new Date().toISOString(),
      latencyMs,
      error: errorMessage,
    };
  }
}


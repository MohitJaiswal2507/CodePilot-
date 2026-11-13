"use client";

import React, { useEffect, useState, useCallback } from "react";
import { RefreshCw, AlertTriangle, WifiOff } from "lucide-react";
import { fetchBackendHealth, HealthStatus } from "@/services/api";
import { cn } from "@/lib/cn";
import { IconButton } from "@/components/ui";

export function HealthBadge() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const checkHealth = useCallback(async () => {
    setLoading(true);
    const result = await fetchBackendHealth();
    setHealth(result);
    setLoading(false);
  }, []);

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, [checkHealth]);

  const isHealthy = health?.status === "healthy";
  const isOffline = !health || health.status === "offline";

  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 h-8 px-2.5 rounded-md border text-xs font-medium transition-colors",
        isHealthy
          ? "bg-[#111113] text-[#FAFAFA] border-[#27272A]"
          : isOffline
          ? "bg-red-500/10 text-red-300 border-red-500/25"
          : "bg-amber-500/10 text-amber-300 border-amber-500/25"
      )}
    >
      <span className="relative flex h-2 w-2 shrink-0" aria-hidden="true">
        <span
          className={cn(
            "relative inline-flex rounded-full h-2 w-2",
            isHealthy ? "bg-emerald-500" : isOffline ? "bg-red-500" : "bg-amber-500"
          )}
        />
      </span>

      <span className="flex items-center gap-1.5 whitespace-nowrap">
        {isHealthy ? (
          <>
            <span className="hidden sm:inline text-[#A1A1AA]">API</span>
            <span className="text-[#FAFAFA]">Connected</span>
            {health.latencyMs !== undefined && (
              <span className="hidden lg:inline text-[11px] text-[#71717A] font-mono tabular-nums">
                {health.latencyMs}ms
              </span>
            )}
          </>
        ) : isOffline ? (
          <>
            <WifiOff className="w-3.5 h-3.5 text-red-400 shrink-0" aria-hidden="true" />
            <span>Offline</span>
          </>
        ) : (
          <>
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" aria-hidden="true" />
            <span>Degraded</span>
          </>
        )}
      </span>

      <IconButton
        label="Refresh backend connection status"
        size="sm"
        onClick={checkHealth}
        disabled={loading}
        className="h-6 w-6 text-[#71717A] hover:text-[#FAFAFA]"
      >
        <RefreshCw className={cn("w-3 h-3", loading && "animate-spin")} />
      </IconButton>
    </div>
  );
}

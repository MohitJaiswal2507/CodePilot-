"use client";

import React, { useEffect, useState, useCallback } from "react";
import { RefreshCw, CheckCircle2, AlertTriangle, WifiOff } from "lucide-react";
import { fetchBackendHealth, HealthStatus } from "@/services/api";

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
    const interval = setInterval(checkHealth, 30000); // Polling every 30s
    return () => clearInterval(interval);
  }, [checkHealth]);

  const isHealthy = health?.status === "healthy";
  const isOffline = !health || health.status === "offline";

  return (
    <div className="flex items-center gap-3">
      <div 
        className={`flex items-center gap-2.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors ${
          isHealthy 
            ? "bg-emerald-950/30 text-emerald-300 border-emerald-800/60" 
            : isOffline 
            ? "bg-rose-950/30 text-rose-300 border-rose-800/60"
            : "bg-amber-950/30 text-amber-300 border-amber-800/60"
        }`}
      >
        <span className="relative flex h-2 w-2">
          {isHealthy && (
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
          )}
          <span className={`relative inline-flex rounded-full h-2 w-2 ${
            isHealthy ? "bg-emerald-500" : isOffline ? "bg-rose-500" : "bg-amber-500"
          }`}></span>
        </span>

        <span className="flex items-center gap-1.5">
          {isHealthy ? (
            <>
              <span>Backend Connected</span>
              <span className="text-[10px] text-emerald-400 font-mono">({health.version})</span>
              {health.latencyMs !== undefined && (
                <span className="text-[10px] text-emerald-500 font-mono">[{health.latencyMs}ms]</span>
              )}
            </>
          ) : isOffline ? (
            <>
              <WifiOff className="w-3.5 h-3.5 text-rose-400" />
              <span>Backend Offline</span>
            </>
          ) : (
            <>
              <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
              <span>Backend Degraded</span>
            </>
          )}
        </span>

        <button
          onClick={checkHealth}
          disabled={loading}
          title="Refresh connection status"
          className="ml-1 text-slate-400 hover:text-slate-200 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>
    </div>
  );
}


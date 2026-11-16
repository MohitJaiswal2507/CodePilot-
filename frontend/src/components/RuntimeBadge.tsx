"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Laptop } from "lucide-react";
import {
  checkLocalRuntimeHealth,
  getLocalRuntimeToken,
  LocalRuntimeHealth,
} from "@/services/localRuntime";
import { cn } from "@/lib/cn";

interface RuntimeBadgeProps {
  onOpenWizard: () => void;
}

export function RuntimeBadge({ onOpenWizard }: RuntimeBadgeProps) {
  const [health, setHealth] = useState<LocalRuntimeHealth | null>(null);
  const [hasToken, setHasToken] = useState<boolean>(false);

  const checkStatus = useCallback(async () => {
    const token = getLocalRuntimeToken();
    setHasToken(!!token);

    const res = await checkLocalRuntimeHealth(2000);
    setHealth(res);
  }, []);

  useEffect(() => {
    checkStatus();
    const interval = setInterval(checkStatus, 15000);

    // Listen for custom runtime events
    const handleRuntimeChanged = () => checkStatus();
    window.addEventListener("codepilot-runtime-changed", handleRuntimeChanged);

    return () => {
      clearInterval(interval);
      window.removeEventListener("codepilot-runtime-changed", handleRuntimeChanged);
    };
  }, [checkStatus]);

  const isLive = health?.status === "ok";
  const isPaired = isLive && hasToken;

  return (
    <button
      type="button"
      onClick={onOpenWizard}
      title={
        isPaired
          ? `Local Docker Runtime v${health?.version || "1.0"} is active and paired`
          : isLive
          ? "Local Runtime running, click to pair browser"
          : "Local Runtime not detected. Click to install desktop runtime."
      }
      className={cn(
        "inline-flex items-center gap-2 h-8 px-2.5 rounded-md border text-xs font-medium transition-all cursor-pointer",
        isPaired
          ? "bg-[#111113] hover:bg-[#18181B] text-[#FAFAFA] border-[#27272A] hover:border-[#3F3F46]"
          : isLive
          ? "bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border-amber-500/30"
          : "bg-blue-500/10 hover:bg-blue-500/20 text-blue-300 border-blue-500/30"
      )}
    >
      <span className="relative flex h-2 w-2 shrink-0" aria-hidden="true">
        <span
          className={cn(
            "relative inline-flex rounded-full h-2 w-2",
            isPaired ? "bg-emerald-500" : isLive ? "bg-amber-400" : "bg-blue-400"
          )}
        />
      </span>

      <span className="flex items-center gap-1.5 whitespace-nowrap">
        <Laptop className="w-3.5 h-3.5 shrink-0 opacity-80" aria-hidden="true" />
        {isPaired ? (
          <>
            <span className="hidden sm:inline text-[#A1A1AA]">Local:</span>
            <span className="text-[#FAFAFA]">Connected</span>
            {health?.version && (
              <span className="hidden xl:inline text-[10px] text-emerald-400 font-mono">
                v{health.version}
              </span>
            )}
          </>
        ) : isLive ? (
          <>
            <span className="text-amber-300">Pair Runtime</span>
          </>
        ) : (
          <>
            <span className="text-blue-300">Setup Runtime</span>
          </>
        )}
      </span>
    </button>
  );
}

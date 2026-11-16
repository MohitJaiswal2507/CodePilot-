"use client";

import { useState, useEffect, useCallback } from "react";
import {
  checkLocalRuntimeHealth,
  getLocalRuntimeToken,
  executeCodeLocally,
  LocalRuntimeHealth,
} from "@/services/localRuntime";
import { runCode, ExecutionResult, SandboxLanguage } from "@/services/api";

export function useLocalRuntime() {
  const [health, setHealth] = useState<LocalRuntimeHealth | null>(null);
  const [isPaired, setIsPaired] = useState<boolean>(false);
  const [isChecking, setIsChecking] = useState<boolean>(true);

  const checkStatus = useCallback(async () => {
    setIsChecking(true);
    const token = getLocalRuntimeToken();
    const h = await checkLocalRuntimeHealth(1500);
    setHealth(h);
    setIsPaired(h?.status === "ok" && !!token);
    setIsChecking(false);
  }, []);

  useEffect(() => {
    checkStatus();
    const interval = setInterval(checkStatus, 15000);
    const handleRuntimeChanged = () => checkStatus();
    window.addEventListener("codepilot-runtime-changed", handleRuntimeChanged);

    return () => {
      clearInterval(interval);
      window.removeEventListener("codepilot-runtime-changed", handleRuntimeChanged);
    };
  }, [checkStatus]);

  /**
   * Execute code: Prefers local Docker execution when paired,
   * falling back to cloud runner if unpaired.
   */
  const execute = useCallback(
    async (params: {
      code: string;
      language: SandboxLanguage;
      stdin?: string | null;
      forceLocal?: boolean;
    }): Promise<{ result: ExecutionResult; isLocal: boolean }> => {
      const token = getLocalRuntimeToken();
      const canRunLocally = health?.status === "ok" && !!token;

      if (canRunLocally || params.forceLocal) {
        const localResult = await executeCodeLocally({
          code: params.code,
          language: params.language,
          stdin: params.stdin,
        });
        return { result: localResult, isLocal: true };
      }

      const cloudResult = await runCode({
        code: params.code,
        language: params.language,
        stdin: params.stdin,
      });
      return { result: cloudResult, isLocal: false };
    },
    [health]
  );

  return {
    health,
    isPaired,
    isLive: health?.status === "ok",
    isDockerOk: health?.status === "ok" && health.docker_available,
    isChecking,
    checkStatus,
    execute,
  };
}

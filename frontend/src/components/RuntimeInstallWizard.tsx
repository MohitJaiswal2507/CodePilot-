"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  Download,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  X,
  Laptop,
  Terminal,
  ShieldCheck,
  FileArchive,
  ArrowRight,
  ExternalLink,
  Lock,
} from "lucide-react";
import {
  checkLocalRuntimeHealth,
  getLocalRuntimeStatus,
  getLocalRuntimeToken,
  confirmLocalPairing,
  requestLocalPairingCode,
  disconnectLocalRuntime,
  pullDockerImageLocally,
  detectClientPlatform,
  LocalRuntimeHealth,
  LocalRuntimeStatus,
  PlatformType,
} from "@/services/localRuntime";

interface RuntimeInstallWizardProps {
  isOpen: boolean;
  onClose: () => void;
}

export function RuntimeInstallWizard({ isOpen, onClose }: RuntimeInstallWizardProps) {
  const [platform, setPlatform] = useState<PlatformType>("windows");
  const [health, setHealth] = useState<LocalRuntimeHealth | null>(null);
  const [status, setStatus] = useState<LocalRuntimeStatus | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [pairingCode, setPairingCode] = useState<string>("");
  const [pairingError, setPairingError] = useState<string | null>(null);
  const [isPairing, setIsPairing] = useState<boolean>(false);
  const [pullingImage, setPullingImage] = useState<string | null>(null);
  const [pullMessage, setPullMessage] = useState<string | null>(null);

  // Poll runtime status
  const refreshRuntime = useCallback(async () => {
    setIsLoading(true);
    const h = await checkLocalRuntimeHealth(2500);
    setHealth(h);
    if (h?.status === "ok") {
      const s = await getLocalRuntimeStatus(3000);
      setStatus(s);
    } else {
      setStatus(null);
    }
    setIsLoading(false);
  }, []);

  useEffect(() => {
    setPlatform(detectClientPlatform());
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    refreshRuntime();
    const interval = setInterval(refreshRuntime, 4000);
    return () => clearInterval(interval);
  }, [isOpen, refreshRuntime]);

  const handlePairSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pairingCode.trim()) return;
    setIsPairing(true);
    setPairingError(null);
    try {
      await confirmLocalPairing(pairingCode.trim());
      setPairingCode("");
      window.dispatchEvent(new Event("codepilot-runtime-changed"));
      await refreshRuntime();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Pairing failed.";
      setPairingError(msg);
    } finally {
      setIsPairing(false);
    }
  };

  const handleRequestNewCode = async () => {
    try {
      const res = await requestLocalPairingCode();
      if (res.pairing_code) {
        setPairingCode(res.pairing_code);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to generate pairing code.";
      setPairingError(msg);
    }
  };

  const handleDisconnect = async () => {
    await disconnectLocalRuntime();
    window.dispatchEvent(new Event("codepilot-runtime-changed"));
    await refreshRuntime();
  };

  const handlePullImage = async (tag: string) => {
    setPullingImage(tag);
    setPullMessage(`Pulling ${tag} via local Docker...`);
    try {
      await pullDockerImageLocally(tag);
      setPullMessage(`Successfully pulled ${tag}!`);
      await refreshRuntime();
    } catch (err: unknown) {
      setPullMessage(err instanceof Error ? err.message : `Failed to pull ${tag}`);
    } finally {
      setPullingImage(null);
    }
  };

  if (!isOpen) return null;

  const isLive = health?.status === "ok";
  const hasToken = !!getLocalRuntimeToken();
  const isPaired = isLive && hasToken;
  const isDockerOk = isLive && health?.docker_available;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="wizard-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 animate-in fade-in"
    >
      <div className="w-full max-w-2xl bg-[#0F1117] border border-[#272B36] rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-6 py-4 border-b border-[#272B36] bg-[#0A0C10] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-blue-500/10 border border-blue-500/20 text-[#3B82F6] flex items-center justify-center">
              <Laptop className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 id="wizard-title" className="text-base font-semibold text-white">
                  CodePilot Local Runtime
                </h2>
                <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-[#181C25] text-blue-300 border border-blue-500/20">
                  {platform}
                </span>
              </div>
              <p className="text-xs text-zinc-400">
                Execute Python, Java, and C++ inside your own Docker container
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={refreshRuntime}
              disabled={isLoading}
              title="Refresh status"
              className="p-1.5 rounded-lg bg-[#181C25] hover:bg-[#202533] border border-white/[0.08] text-zinc-300 hover:text-white transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin text-blue-400" : ""}`} />
            </button>
            <button
              onClick={onClose}
              aria-label="Close dialog"
              className="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-white/[0.06] transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Status Strip */}
        <div className="px-6 py-2.5 bg-[#12151D] border-b border-white/[0.06] flex flex-wrap items-center justify-between text-xs gap-3">
          <div className="flex items-center gap-2">
            <span className="text-zinc-500 font-medium">Daemon:</span>
            <span
              className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium border ${
                isLive
                  ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                  : "bg-zinc-800 text-zinc-400 border-zinc-700"
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${isLive ? "bg-emerald-400" : "bg-zinc-500"}`}
              />
              {isLive ? `Running (127.0.0.1:8088)` : "Offline / Not Running"}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-zinc-500 font-medium">Docker:</span>
            <span
              className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium border ${
                isDockerOk
                  ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                  : isLive
                  ? "bg-rose-500/10 text-rose-300 border-rose-500/30"
                  : "bg-zinc-800 text-zinc-400 border-zinc-700"
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  isDockerOk ? "bg-emerald-400" : isLive ? "bg-rose-400" : "bg-zinc-500"
                }`}
              />
              {isDockerOk
                ? `Ready (${health?.docker_version || "Active"})`
                : isLive
                ? "Daemon Stopped"
                : "Not checked"}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-zinc-500 font-medium">Pairing:</span>
            <span
              className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium border ${
                isPaired
                  ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                  : "bg-zinc-800 text-zinc-400 border-zinc-700"
              }`}
            >
              <Lock className="w-3 h-3" />
              {isPaired ? "Paired & Authenticated" : "Unpaired"}
            </span>
          </div>
        </div>

        {/* Content Body */}
        <div className="p-6 overflow-y-auto space-y-6">
          {/* Step 1: Download & Install */}
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-600/20 text-blue-400 border border-blue-500/30 text-xs font-bold">
                1
              </span>
              <h3 className="text-sm font-semibold text-white">Download CodePilot Local Runtime</h3>
            </div>

            <p className="text-xs text-zinc-400 pl-8">
              A standalone desktop service that links your browser directly to your local Docker daemon.
              No cloud runner or tunnels needed.
            </p>

            <div className="pl-8 grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
              {/* Windows One-Click Installer */}
              <a
                href="/downloads/codepilot-runtime-setup-win-x64.exe"
                download
                className="p-3.5 rounded-xl border border-blue-500/30 bg-blue-500/10 hover:bg-blue-500/20 transition-all flex flex-col justify-between group cursor-pointer"
              >
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-white flex items-center gap-1.5">
                      <Download className="w-4 h-4 text-blue-400" />
                      Windows Installer (x64)
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300 font-mono">
                      ~29.8 MB
                    </span>
                  </div>
                  <p className="text-[11px] text-zinc-400 mt-1.5">
                    Automated setup wizard. Configures shortcuts, starts daemon, and verifies Docker.
                  </p>
                </div>
                <div className="mt-3 flex items-center gap-1 text-xs font-semibold text-blue-400 group-hover:text-blue-300">
                  <span>Download .exe</span>
                  <ArrowRight className="w-3.5 h-3.5 transition-transform group-hover:translate-x-0.5" />
                </div>
              </a>

              {/* Portable Archive */}
              <a
                href="/downloads/codepilot-runtime-portable-win-x64.zip"
                download
                className="p-3.5 rounded-xl border border-[#272B36] bg-[#141720] hover:bg-[#1A1F2C] hover:border-zinc-700 transition-all flex flex-col justify-between group cursor-pointer"
              >
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                      <FileArchive className="w-4 h-4 text-zinc-400" />
                      Portable Archive (ZIP)
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 font-mono">
                      ~21.3 MB
                    </span>
                  </div>
                  <p className="text-[11px] text-zinc-400 mt-1.5">
                    No installation required. Unzip anywhere and execute start-runtime.bat.
                  </p>
                </div>
                <div className="mt-3 flex items-center gap-1 text-xs font-semibold text-zinc-400 group-hover:text-zinc-200">
                  <span>Download .zip</span>
                  <ArrowRight className="w-3.5 h-3.5 transition-transform group-hover:translate-x-0.5" />
                </div>
              </a>
            </div>

            {/* macOS & Linux script helper */}
            <div className="pl-8 pt-1">
              <div className="p-3 rounded-xl border border-white/[0.08] bg-[#0A0C10] flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <Terminal className="w-4 h-4 text-emerald-400" />
                  <span className="text-zinc-300">macOS / Linux setup script:</span>
                </div>
                <a
                  href="/downloads/codepilot-runtime-setup.sh"
                  download
                  className="text-blue-400 hover:text-blue-300 flex items-center gap-1 text-xs font-medium"
                >
                  <span>codepilot-runtime-setup.sh</span>
                  <Download className="w-3 h-3" />
                </a>
              </div>
            </div>
          </div>

          {/* Step 2: Docker Verification */}
          <div className="space-y-3 pt-2 border-t border-white/[0.06]">
            <div className="flex items-center gap-2">
              <span className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-600/20 text-blue-400 border border-blue-500/30 text-xs font-bold">
                2
              </span>
              <h3 className="text-sm font-semibold text-white">Docker Engine Status</h3>
            </div>

            <div className="pl-8 space-y-2 text-xs">
              {isDockerOk ? (
                <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center gap-2.5 text-emerald-300">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                  <span>
                    Docker Engine is running locally ({health?.docker_version}). Isolated sandbox execution ready.
                  </span>
                </div>
              ) : isLive ? (
                <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-start justify-between gap-3 text-rose-300">
                  <div className="flex items-start gap-2">
                    <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                    <div>
                      <p className="font-semibold">Docker Daemon Offline</p>
                      <p className="text-rose-300/80 mt-0.5">
                        The local runtime is running, but Docker Desktop is not open. Please launch Docker Desktop.
                      </p>
                    </div>
                  </div>
                  <a
                    href="https://www.docker.com/products/docker-desktop/"
                    target="_blank"
                    rel="noreferrer"
                    className="px-2.5 py-1 rounded bg-rose-500/20 text-rose-200 hover:bg-rose-500/30 text-xs font-medium whitespace-nowrap inline-flex items-center gap-1"
                  >
                    <span>Get Docker</span>
                    <ExternalLink className="w-3 h-3" />
                  </a>
                </div>
              ) : (
                <p className="text-zinc-500">
                  Launch the local runtime installer in Step 1 to automatically detect your local Docker status.
                </p>
              )}
            </div>
          </div>

          {/* Step 3: Language Execution Images */}
          {isDockerOk && (
            <div className="space-y-3 pt-2 border-t border-white/[0.06]">
              <div className="flex items-center gap-2">
                <span className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-600/20 text-blue-400 border border-blue-500/30 text-xs font-bold">
                  3
                </span>
                <h3 className="text-sm font-semibold text-white">Language Environments</h3>
              </div>

              <div className="pl-8 space-y-2">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                  {[
                    { lang: "Python 3.12", tag: "python:3.12-slim" },
                    { lang: "Java 21", tag: "eclipse-temurin:21-jdk" },
                    { lang: "C++ (GCC 14)", tag: "gcc:14" },
                  ].map(({ lang, tag }) => {
                    const isInstalled = status?.languages?.images?.[tag]?.installed ?? true;
                    const isPulling = pullingImage === tag;

                    return (
                      <div
                        key={tag}
                        className="p-3 rounded-xl bg-[#0D0F16] border border-white/[0.08] flex flex-col justify-between"
                      >
                        <div>
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-medium text-white">{lang}</span>
                            {isInstalled ? (
                              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                            ) : (
                              <AlertCircle className="w-3.5 h-3.5 text-amber-400" />
                            )}
                          </div>
                          <p className="text-[10px] font-mono text-zinc-500 mt-1 truncate">{tag}</p>
                        </div>

                        <div className="mt-2.5 pt-2 border-t border-white/[0.04]">
                          {isInstalled ? (
                            <span className="text-[11px] text-emerald-400 font-medium">Ready</span>
                          ) : (
                            <button
                              onClick={() => handlePullImage(tag)}
                              disabled={isPulling}
                              className="text-[11px] text-blue-400 hover:text-blue-300 font-medium inline-flex items-center gap-1"
                            >
                              {isPulling ? (
                                <>
                                  <RefreshCw className="w-3 h-3 animate-spin" />
                                  <span>Pulling...</span>
                                </>
                              ) : (
                                <>
                                  <Download className="w-3 h-3" />
                                  <span>Pull Image</span>
                                </>
                              )}
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {pullMessage && (
                  <p className="text-[11px] text-zinc-400 font-mono mt-1">{pullMessage}</p>
                )}
              </div>
            </div>
          )}

          {/* Step 4: Security Pairing */}
          <div className="space-y-3 pt-2 border-t border-white/[0.06]">
            <div className="flex items-center gap-2">
              <span className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-600/20 text-blue-400 border border-blue-500/30 text-xs font-bold">
                {isDockerOk ? "4" : "3"}
              </span>
              <h3 className="text-sm font-semibold text-white">Browser Security Pairing</h3>
            </div>

            <div className="pl-8 space-y-3 text-xs">
              <p className="text-zinc-400">
                To protect against unauthorized web requests, CodePilot browser tabs authenticate
                with your local runtime using a one-time 6-digit cryptographic pairing code.
              </p>

              {isPaired ? (
                <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-between">
                  <div className="flex items-center gap-2 text-emerald-300">
                    <ShieldCheck className="w-4 h-4 text-emerald-400" />
                    <span>Browser is securely authenticated with your local runtime.</span>
                  </div>
                  <button
                    onClick={handleDisconnect}
                    className="px-2.5 py-1 rounded bg-[#181C25] hover:bg-[#202533] text-zinc-400 hover:text-zinc-200 border border-white/[0.08] text-xs transition-colors"
                  >
                    Disconnect
                  </button>
                </div>
              ) : isLive ? (
                <form onSubmit={handlePairSubmit} className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      type="text"
                      maxLength={10}
                      placeholder="Enter 6-digit code (e.g. 123456)"
                      value={pairingCode}
                      onChange={(e) => setPairingCode(e.target.value)}
                      className="px-3 py-1.5 rounded-lg bg-[#080A10] border border-white/[0.12] focus:border-blue-500 text-white font-mono text-sm tracking-wider w-56 focus:outline-none"
                    />
                    <button
                      type="submit"
                      disabled={isPairing || !pairingCode.trim()}
                      className="px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium text-xs disabled:opacity-50 transition-colors inline-flex items-center gap-1.5 cursor-pointer"
                    >
                      {isPairing ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : null}
                      <span>Confirm Pairing</span>
                    </button>
                    <button
                      type="button"
                      onClick={handleRequestNewCode}
                      className="px-3 py-1.5 rounded-lg bg-[#181C25] hover:bg-[#202533] text-zinc-300 text-xs border border-white/[0.08] transition-colors"
                    >
                      Get Code
                    </button>
                  </div>

                  {pairingError && (
                    <div className="p-2.5 rounded-lg bg-rose-500/10 border border-rose-500/25 text-rose-300 text-xs">
                      {pairingError}
                    </div>
                  )}
                </form>
              ) : (
                <p className="text-zinc-500">
                  Start the runtime installer first to enable browser pairing.
                </p>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-3.5 border-t border-[#272B36] bg-[#0A0C10] flex items-center justify-between">
          <div className="flex items-center gap-2 text-[11px] text-zinc-500">
            <Lock className="w-3.5 h-3.5 text-zinc-400" />
            <span>Private Network Access (RFC 1918) Guarded</span>
          </div>

          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg bg-[#181C25] hover:bg-[#202533] text-zinc-200 border border-white/[0.08] text-xs font-medium transition-colors cursor-pointer"
          >
            {isPaired ? "Start Coding" : "Close"}
          </button>
        </div>
      </div>
    </div>
  );
}

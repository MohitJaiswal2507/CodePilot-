"use client";

import React, { useState } from "react";
import { AlertCircle, Check, Clock, Copy, RefreshCw, Terminal, Trash2 } from "lucide-react";
import { ExecutionResult } from "@/services/api";
import {
  ExecutionErrorState,
  LANGUAGE_LABELS,
  SupportedLanguage,
  formatDurationMs,
  getExecutionStatusMeta,
} from "@/lib/sandbox";

interface ExecutionConsoleProps {
  language: SupportedLanguage;
  isRunning: boolean;
  executionResult: ExecutionResult | null;
  executionError: ExecutionErrorState | null;
  onClearConsole: () => void;
}

export function ExecutionConsole({
  language,
  isRunning,
  executionResult,
  executionError,
  onClearConsole,
}: ExecutionConsoleProps) {
  const [copied, setCopied] = useState(false);
  const statusMeta = executionResult ? getExecutionStatusMeta(executionResult) : null;
  const StatusIcon = statusMeta?.icon;

  const handleCopyOutput = () => {
    const text = [
      executionResult?.compilation_error,
      executionResult?.stdout,
      executionResult?.stderr,
    ]
      .filter(Boolean)
      .join("\n");
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="rounded-xl border border-[#272B36] bg-[#111319] overflow-hidden flex flex-col">
      {/* Console Header */}
      <div className="px-4 py-3 border-b border-[#272B36] bg-[#0d0f17] flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-emerald-400" />
            <h2 className="text-xs font-semibold text-[#F4F4F5]">Execution Console</h2>
          </div>

          {isRunning && (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-[#3B82F6]/10 text-[#60A5FA] border border-[#3B82F6]/30">
              <RefreshCw className="w-3 h-3 animate-spin" />
              Running
            </span>
          )}

          {!isRunning && statusMeta && StatusIcon && (
            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${statusMeta.classes}`}
            >
              <StatusIcon className="w-3 h-3" />
              {statusMeta.label}
            </span>
          )}

          {!isRunning && !executionResult && executionError && (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold border bg-red-500/10 text-red-400 border-red-500/30">
              <AlertCircle className="w-3 h-3" />
              {executionError.title}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2.5">
          {!isRunning && executionResult && (
            <div className="flex flex-wrap items-center gap-2 text-[11px] font-mono text-[#A1A1AA]">
              {executionResult.compile_duration_ms !== null && (
                <span className="px-2 py-0.5 rounded bg-[#181C25] border border-white/[0.08]">
                  Compile: {formatDurationMs(executionResult.compile_duration_ms)}
                </span>
              )}
              <span className="px-2 py-0.5 rounded bg-[#181C25] border border-white/[0.08] flex items-center gap-1">
                <Clock className="w-3 h-3 text-[#71717A]" />
                {formatDurationMs(executionResult.duration_ms)}
              </span>
              {executionResult.exit_code !== null && (
                <span className="px-2 py-0.5 rounded bg-[#181C25] border border-white/[0.08]">
                  Exit: {executionResult.exit_code}
                </span>
              )}
            </div>
          )}

          {!isRunning && executionResult && (executionResult.stdout || executionResult.stderr || executionResult.compilation_error) && (
            <button
              type="button"
              onClick={handleCopyOutput}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#181C25] hover:bg-[#202533] border border-white/[0.08] hover:border-white/[0.16] text-[11px] text-[#A1A1AA] hover:text-[#F4F4F5] transition-colors cursor-pointer"
              title="Copy console output to clipboard"
            >
              {copied ? (
                <>
                  <Check className="w-3 h-3 text-emerald-400" />
                  <span>Copied</span>
                </>
              ) : (
                <>
                  <Copy className="w-3 h-3" />
                  <span>Copy</span>
                </>
              )}
            </button>
          )}

          <button
            type="button"
            onClick={onClearConsole}
            disabled={isRunning || (!executionResult && !executionError)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#181C25] hover:bg-[#202533] border border-white/[0.08] hover:border-white/[0.16] text-[11px] text-[#A1A1AA] hover:text-[#F4F4F5] disabled:opacity-40 transition-colors cursor-pointer disabled:cursor-not-allowed"
            title="Clear console output"
          >
            <Trash2 className="w-3 h-3" />
            <span>Clear Console</span>
          </button>
        </div>
      </div>

      {/* Console Body */}
      <div className="p-4 flex-1 min-h-[168px] max-h-[340px] overflow-y-auto space-y-3 bg-[#080A10]">
        {/* Running State */}
        {isRunning && (
          <div className="py-10 flex flex-col items-center justify-center text-center space-y-2">
            <RefreshCw className="w-5 h-5 text-emerald-400 animate-spin" />
            <p className="text-xs font-medium text-[#F4F4F5]">
              Executing {LANGUAGE_LABELS[language]} code in sandbox...
            </p>
            <p className="text-[11px] text-[#71717A]">
              Wait for execution to complete before submitting another run.
            </p>
          </div>
        )}

        {/* API / Auth / Rate-limit / Availability Error State */}
        {!isRunning && executionError && (!executionResult || executionError.statusCode) && (
          <div className="p-3.5 rounded-lg bg-red-500/10 border border-red-500/25 flex items-start gap-3 text-xs text-red-200">
            <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <p className="font-semibold text-red-300">
                {executionError.title}
                {executionError.statusCode ? ` (HTTP ${executionError.statusCode})` : ""}
              </p>
              <p className="text-red-200/90 leading-relaxed">{executionError.message}</p>
            </div>
          </div>
        )}

        {/* Structured Sandbox Result */}
        {!isRunning && executionResult && statusMeta && (
          <div className="space-y-3">
            {statusMeta.notice && StatusIcon && (() => {
              const isWarning =
                executionResult.status === "timeout" ||
                executionResult.status === "compilation_timeout" ||
                executionResult.status === "output_limit_exceeded";
              return (
                <div
                  className={`p-3 rounded-lg border flex items-start gap-2.5 text-xs ${
                    isWarning
                      ? "bg-amber-500/10 border-amber-500/25 text-amber-200"
                      : "bg-red-500/10 border-red-500/25 text-red-200"
                  }`}
                >
                  <StatusIcon
                    className={`w-4 h-4 shrink-0 mt-0.5 ${
                      isWarning ? "text-amber-400" : "text-red-400"
                    }`}
                  />
                  <div className="space-y-0.5">
                    <p className="font-medium">{statusMeta.notice}</p>
                    {executionResult.truncated && (
                      <p className="text-[11px] opacity-85">
                        Output was truncated to stay within the 64 KB console limit.
                      </p>
                    )}
                  </div>
                </div>
              );
            })()}

            {executionResult.compilation_error && (
              <div className="space-y-1.5">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-red-400">
                  Compilation Error
                </span>
                <pre className="p-3 rounded-lg bg-[#080A10] border border-red-500/25 font-mono text-xs text-red-300 whitespace-pre-wrap break-words overflow-x-auto leading-relaxed">
                  {executionResult.compilation_error}
                </pre>
              </div>
            )}

            {executionResult.stdout && (
              <div className="space-y-1.5">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-[#A1A1AA]">
                  Standard Output
                </span>
                <pre className="p-3 rounded-lg bg-[#080A10] border border-white/[0.08] font-mono text-xs text-emerald-300 whitespace-pre-wrap break-words overflow-x-auto leading-relaxed">
                  {executionResult.stdout}
                </pre>
              </div>
            )}

            {executionResult.stderr && (
              <div className="space-y-1.5">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-red-400">
                  Standard Error
                </span>
                <pre className="p-3 rounded-lg bg-[#080A10] border border-red-500/25 font-mono text-xs text-red-300 whitespace-pre-wrap break-words overflow-x-auto leading-relaxed">
                  {executionResult.stderr}
                </pre>
              </div>
            )}

            {executionResult.status === "success" &&
              !executionResult.stdout &&
              !executionResult.stderr && (
                <p className="text-xs text-[#A1A1AA] font-mono py-2">
                  Program exited cleanly (exit code 0) with no output.
                </p>
              )}
          </div>
        )}

        {/* Empty Initial State */}
        {!isRunning && !executionResult && !executionError && (
          <div className="py-10 flex flex-col items-center justify-center text-center space-y-1.5">
            <Terminal className="w-5 h-5 text-[#71717A]" />
            <p className="text-xs text-[#A1A1AA]">
              Click <span className="text-emerald-400 font-semibold">&ldquo;Run Code&rdquo;</span> to execute your code and view stdout, stderr, compiler diagnostics, and runtime duration.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}


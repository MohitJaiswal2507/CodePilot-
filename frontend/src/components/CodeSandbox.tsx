"use client";

import React, { useRef, useState } from "react";
import Editor from "@monaco-editor/react";
import {
  FileCode,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Terminal,
  Trash2,
} from "lucide-react";
import { ExecutionResult, runCode } from "@/services/api";
import { ExecutionConsole } from "@/components/sandbox/ExecutionConsole";
import {
  ExecutionErrorState,
  LANGUAGE_LABELS,
  MONACO_LANG_MAP,
  SANDBOX_SAMPLE_PROGRAMS,
  SandboxSampleProgram,
  SupportedLanguage,
  mapSandboxApiError,
} from "@/lib/sandbox";
import { buildMonacoOptions, getEditorSettings } from "@/lib/editorSettings";

const LANGUAGES: SupportedLanguage[] = ["python", "java", "cpp"];

export function CodeSandbox() {
  const [editorSettings] = useState(() => getEditorSettings());
  const [language, setLanguage] = useState<SupportedLanguage>(editorSettings.defaultLanguage);
  const [code, setCode] = useState<string>(
    SANDBOX_SAMPLE_PROGRAMS[editorSettings.defaultLanguage][0].code
  );
  const [stdinInput, setStdinInput] = useState<string>(
    SANDBOX_SAMPLE_PROGRAMS[editorSettings.defaultLanguage][0].stdin ?? ""
  );
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [executionResult, setExecutionResult] = useState<ExecutionResult | null>(null);
  const [executionError, setExecutionError] = useState<ExecutionErrorState | null>(null);

  const inFlightRef = useRef<boolean>(false);

  const stdinByteLength = new TextEncoder().encode(stdinInput).length;

  const handleLanguageChange = (newLang: SupportedLanguage) => {
    if (isRunning || newLang === language) return;
    const defaultSample = SANDBOX_SAMPLE_PROGRAMS[newLang][0];
    setLanguage(newLang);
    setCode(defaultSample.code);
    setStdinInput(defaultSample.stdin ?? "");
    setExecutionResult(null);
    setExecutionError(null);
  };

  const handleLoadSample = (sample: SandboxSampleProgram) => {
    if (isRunning) return;
    setCode(sample.code);
    setStdinInput(sample.stdin ?? "");
    setExecutionResult(null);
    setExecutionError(null);
  };

  const handleClear = () => {
    if (isRunning) return;
    setCode("");
    setExecutionError(null);
  };

  const handleReset = () => {
    if (isRunning) return;
    const defaultSample = SANDBOX_SAMPLE_PROGRAMS[language][0];
    setCode(defaultSample.code);
    setStdinInput(defaultSample.stdin ?? "");
    setExecutionResult(null);
    setExecutionError(null);
  };

  const handleClearConsole = () => {
    if (isRunning) return;
    setExecutionResult(null);
    setExecutionError(null);
  };

  const handleRunCode = async () => {
    if (isRunning || inFlightRef.current) return;

    if (!code.trim()) {
      setExecutionResult(null);
      setExecutionError({
        title: "Validation Error",
        message: "Please enter some code in the editor before running.",
        statusCode: 422,
      });
      return;
    }

    inFlightRef.current = true;
    setIsRunning(true);
    setExecutionError(null);
    setExecutionResult(null);

    try {
      const result = await runCode({
        code,
        language,
        stdin: stdinInput.length > 0 ? stdinInput : null,
      });
      setExecutionResult(result);
    } catch (err: unknown) {
      const mapped = mapSandboxApiError(err);
      if (mapped.executionResult) {
        setExecutionResult(mapped.executionResult);
      }
      setExecutionError(mapped.error);
    } finally {
      inFlightRef.current = false;
      setIsRunning(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Workspace Header & Action Bar */}
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 p-5 rounded-xl border border-[#272B36] bg-[#111319]">
        <div className="flex items-start sm:items-center gap-3.5">
          <div className="p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 shrink-0">
            <Terminal className="w-5 h-5" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-base font-bold text-white tracking-tight">
                Code Execution Sandbox
              </h1>
              <span className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                <ShieldCheck className="w-3 h-3" />
                Docker Isolated
              </span>
            </div>
            <p className="text-xs text-zinc-400 mt-0.5">
              Run Python, Java, and C++ programs in an isolated container with custom stdin, compiler diagnostics, and resource limits.
            </p>
          </div>
        </div>

        {/* Language Selector & Primary Controls */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Language Selector Tabs */}
          <div className="flex items-center gap-1.5 p-1 rounded-xl bg-[#080A10] border border-white/[0.08]">
            {LANGUAGES.map((lang) => (
              <button
                key={lang}
                type="button"
                onClick={() => handleLanguageChange(lang)}
                disabled={isRunning}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${
                  language === lang
                    ? "bg-blue-600 text-white shadow-sm shadow-blue-900/40"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                {LANGUAGE_LABELS[lang]}
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={handleReset}
            disabled={isRunning}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#181C25] hover:bg-[#202533] border border-white/[0.08] hover:border-white/[0.16] text-xs text-zinc-300 hover:text-white transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            title="Reset to default sample for current language"
          >
            <RotateCcw className="w-3.5 h-3.5 text-zinc-400" />
            <span>Reset</span>
          </button>

          <button
            type="button"
            onClick={handleClear}
            disabled={!code || isRunning}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-[#181C25] hover:bg-[#202533] border border-white/[0.08] hover:border-white/[0.16] text-xs text-zinc-400 hover:text-zinc-200 disabled:opacity-40 transition-colors cursor-pointer disabled:cursor-not-allowed"
            title="Clear editor"
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>Clear</span>
          </button>

          <button
            type="button"
            onClick={handleRunCode}
            disabled={isRunning || !code.trim()}
            className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-xs disabled:opacity-50 transition-all shadow-md shadow-emerald-950/40 cursor-pointer disabled:cursor-not-allowed"
            title="Execute code in isolated Docker sandbox"
          >
            {isRunning ? (
              <>
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                <span>Running...</span>
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>Run Code</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Large Monaco Editor Panel */}
      <div className="rounded-xl border border-[#272B36] bg-[#111319] overflow-hidden flex flex-col">
        {/* Sample Programs Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 border-b border-[#272B36] bg-[#0d0f17]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-medium text-zinc-500">
              {LANGUAGE_LABELS[language]} Samples:
            </span>
            <div className="flex flex-wrap gap-1.5">
              {SANDBOX_SAMPLE_PROGRAMS[language].map((sample, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => handleLoadSample(sample)}
                  disabled={isRunning}
                  title={sample.description}
                  className="text-[11px] px-2.5 py-1 rounded-lg bg-[#181C25] hover:bg-[#202533] text-zinc-300 border border-white/[0.08] hover:text-white hover:border-white/[0.16] transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {sample.title}
                </button>
              ))}
            </div>
          </div>

          <span className="text-[11px] font-mono text-zinc-400 px-2 py-0.5 rounded-md bg-[#080A10] border border-white/[0.08]">
            {language === "python" ? "main.py" : language === "java" ? "Main.java" : "main.cpp"}
          </span>
        </div>

        {/* Monaco Editor Container */}
        <div className="h-[480px] w-full relative bg-[#080A10]">
          <Editor
            height="100%"
            language={MONACO_LANG_MAP[language]}
            theme="vs-dark"
            value={code}
            onChange={(val) => setCode(val || "")}
            options={buildMonacoOptions(editorSettings, { readOnly: isRunning })}
          />
        </div>

        {/* Editor Footer */}
        <div className="px-4 py-2 bg-[#0d0f17] border-t border-white/[0.08] flex items-center justify-between text-[11px] text-zinc-500">
          <div className="flex items-center gap-3">
            <span className="font-mono text-zinc-400">{code.length} characters</span>
            <span>•</span>
            <span className="font-mono text-zinc-400">{code.split("\n").length} lines</span>
          </div>
          <div className="flex items-center gap-1.5 text-zinc-400">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            <span>Isolated Container • Network Disabled • Server Limits</span>
          </div>
        </div>
      </div>

      {/* Sandbox Execution Workspace: Standard Input & Console Output */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Standard Input (stdin) Panel (4 cols) */}
        <div className="lg:col-span-4 rounded-xl border border-[#272B36] bg-[#111319] overflow-hidden flex flex-col">
          <div className="px-4 py-3 border-b border-[#272B36] bg-[#0d0f17] flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <FileCode className="w-4 h-4 text-[#3B82F6]" />
              <h2 className="text-xs font-semibold text-white">Standard Input (stdin)</h2>
            </div>
            {stdinInput.length > 0 && (
              <button
                type="button"
                onClick={() => setStdinInput("")}
                disabled={isRunning}
                className="text-[11px] text-zinc-400 hover:text-zinc-200 disabled:opacity-40 transition-colors cursor-pointer disabled:cursor-not-allowed"
              >
                Clear input
              </button>
            )}
          </div>

          <div className="p-3 flex-1 flex flex-col">
            <textarea
              value={stdinInput}
              onChange={(e) => setStdinInput(e.target.value)}
              disabled={isRunning}
              placeholder="Optional program input passed via stdin..."
              rows={5}
              aria-label="Standard input"
              className="w-full flex-1 min-h-[128px] rounded-xl bg-[#080A10] border border-white/[0.08] focus:border-[#3B82F6] focus:outline-none focus:ring-1 focus:ring-[#3B82F6]/50 p-3 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 resize-y disabled:opacity-60"
            />
          </div>

          <div className="px-4 py-2 bg-[#0d0f17] border-t border-white/[0.08] flex items-center justify-between text-[11px] text-zinc-500">
            <span
              className={`font-mono ${
                stdinByteLength > 65536 ? "text-rose-400 font-bold" : "text-zinc-400"
              }`}
            >
              {stdinByteLength.toLocaleString()} / 65,536 bytes
            </span>
            <span>Passed via standard input</span>
          </div>
        </div>

        {/* Execution Console Output Panel (8 cols) */}
        <div className="lg:col-span-8">
          <ExecutionConsole
            language={language}
            isRunning={isRunning}
            executionResult={executionResult}
            executionError={executionError}
            onClearConsole={handleClearConsole}
          />
        </div>
      </div>
    </div>
  );
}

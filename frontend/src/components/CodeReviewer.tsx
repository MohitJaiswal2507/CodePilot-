"use client";

import React, { useState, useEffect } from "react";
import Editor from "@monaco-editor/react";
import {
  Code2,
  Play,
  Trash2,
  Copy,
  Check,
  AlertTriangle,
  AlertCircle,
  CheckCircle2,
  Clock,
  Zap,
  RefreshCw,
  Sparkles,
  Layers,
  ShieldCheck,
  FileCode,
  History,
  XCircle,
  HelpCircle,
  ChevronRight,
  Info,
  Terminal,
} from "lucide-react";
import {
  submitCodeReview,
  fetchCodeReviewHistory,
  fetchCodeReviewDetail,
  deleteCodeReview,
  runCode,
  SandboxApiError,
  ExecutionResult,
  CodeReviewResult,
  CodeReviewResponse,
  CodeReviewHistoryItem,
} from "@/services/api";

type SupportedLanguage = "python" | "java" | "cpp";

interface SampleCode {
  title: string;
  code: string;
  description: string;
}

const SAMPLE_CODES: Record<SupportedLanguage, SampleCode[]> = {
  python: [
    {
      title: "Binary Search (Buggy Off-by-One)",
      description: "Infinite loop condition & missing edge-case check",
      code: `def binary_search(arr, target):
    left = 0
    right = len(arr)  # Bug: should be len(arr) - 1 for inclusive indexing
    
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid  # Bug: should be mid - 1 to avoid infinite loop
            
    return -1`,
    },
    {
      title: "Two Sum (Quadratic O(N^2))",
      description: "Unnecessary nested loop that can be optimized to O(N)",
      code: `def two_sum(nums, target):
    # Quadratic brute force approach
    n = len(nums)
    for i in range(n):
        for j in range(i + 1, n):
            if nums[i] + nums[j] == target:
                return [i, j]
    return []`,
    },
    {
      title: "Recursive Fibonacci (Exponential O(2^N))",
      description: "Exponential recursion without memoization",
      code: `def fibonacci(n):
    if n <= 0:
        return 0
    if n == 1:
        return 1
    return fibonacci(n - 1) + fibonacci(n - 2)`,
    },
  ],
  java: [
    {
      title: "String Palindrome Check (Buggy)",
      description: "String comparison using == instead of .equals()",
      code: `public class PalindromeCheck {
    public static boolean isPalindrome(String s) {
        if (s == null) return false;
        String clean = s.toLowerCase().replaceAll("[^a-zA-Z0-9]", "");
        String reversed = new StringBuilder(clean).reverse().toString();
        // Bug: uses reference equality instead of content equality
        return clean == reversed;
    }
}`,
    },
    {
      title: "Array Max Finder",
      description: "Unchecked empty array causing ArrayIndexOutOfBoundsException",
      code: `public class ArrayUtils {
    public static int findMax(int[] arr) {
        // Bug: no validation for empty or null array
        int max = arr[0];
        for (int i = 1; i < arr.length; i++) {
            if (arr[i] > max) {
                max = arr[i];
            }
        }
        return max;
    }
}`,
    },
  ],
  cpp: [
    {
      title: "Memory Leak & Raw Pointer",
      description: "Dynamically allocated buffer without delete[]",
      code: `#include <iostream>
#include <vector>

void processData(int size) {
    // Memory leak: allocated on heap with new[] but never deleted
    int* buffer = new int[size];
    for (int i = 0; i < size; ++i) {
        buffer[i] = i * 2;
    }
    std::cout << "Processed " << size << " elements." << std::endl;
    // Missing delete[] buffer;
}`,
    },
    {
      title: "Vector Subscript Out of Range",
      description: "Loop bounds off by one accessing vec[vec.size()]",
      code: `#include <vector>
#include <numeric>

long long sumElements(const std::vector<int>& vec) {
    long long total = 0;
    // Bug: loop condition <= vec.size() causes out-of-bounds access
    for (size_t i = 0; i <= vec.size(); ++i) {
        total += vec[i];
    }
    return total;
}`,
    },
  ],
};

const MONACO_LANG_MAP: Record<SupportedLanguage, string> = {
  python: "python",
  java: "java",
  cpp: "cpp",
};

export function CodeReviewer() {
  const [language, setLanguage] = useState<SupportedLanguage>("python");
  const [code, setCode] = useState<string>(SAMPLE_CODES.python[0].code);
  const [stdinInput, setStdinInput] = useState<string>("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [reviewResult, setReviewResult] = useState<CodeReviewResult | null>(null);
  const [executionResult, setExecutionResult] = useState<ExecutionResult | null>(null);
  const [executionError, setExecutionError] = useState<{
    title: string;
    message: string;
    statusCode?: number;
  } | null>(null);
  const [activeReviewId, setActiveReviewId] = useState<string | null>(null);
  const [copiedCode, setCopiedCode] = useState(false);
  const [activeTab, setActiveTab] = useState<"overview" | "issues" | "complexity" | "edge_cases" | "corrected">("overview");

  // History state
  const [history, setHistory] = useState<CodeReviewHistoryItem[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [showHistoryDrawer, setShowHistoryDrawer] = useState(false);

  // Load history on mount
  useEffect(() => {
    loadHistory();
  }, []);

  const loadHistory = async () => {
    setIsLoadingHistory(true);
    try {
      const data = await fetchCodeReviewHistory(15, 0);
      setHistory(data.reviews || []);
    } catch (err) {
      console.debug("Failed to load review history:", err);
    } finally {
      setIsLoadingHistory(false);
    }
  };

  const handleLanguageChange = (newLang: SupportedLanguage) => {
    setLanguage(newLang);
    // Suggest sample for the new language
    if (SAMPLE_CODES[newLang] && SAMPLE_CODES[newLang].length > 0) {
      setCode(SAMPLE_CODES[newLang][0].code);
    }
  };

  const handleLoadSample = (sample: SampleCode) => {
    setCode(sample.code);
    setErrorMessage(null);
  };

  const handleClear = () => {
    setCode("");
    setErrorMessage(null);
  };

  const handleClearConsole = () => {
    if (isRunning) return;
    setExecutionResult(null);
    setExecutionError(null);
  };

  const handleRunCode = async () => {
    if (isRunning) return;
    const trimmed = code.trim();
    if (!trimmed) {
      setExecutionResult(null);
      setExecutionError({
        title: "Validation Error",
        message: "Please enter some code in the editor before running.",
        statusCode: 422,
      });
      return;
    }

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
      if (err instanceof SandboxApiError) {
        if (err.executionResult) {
          setExecutionResult(err.executionResult);
        }
        const titleMap: Record<number, string> = {
          401: "Authentication Required",
          422: "Validation Error",
          429: "Rate or Concurrency Limit Reached",
          503: "Sandbox Unavailable",
        };
        setExecutionError({
          title: titleMap[err.statusCode] || "Execution Request Failed",
          message: err.message,
          statusCode: err.statusCode,
        });
      } else {
        const msg = err instanceof Error ? err.message : "Failed to execute code. Please try again.";
        setExecutionError({
          title: "Execution Request Failed",
          message: msg,
        });
      }
    } finally {
      setIsRunning(false);
    }
  };

  const handleSubmitReview = async () => {
    const trimmed = code.trim();
    if (!trimmed) {
      setErrorMessage("Please enter some code to submit for review.");
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      const response: CodeReviewResponse = await submitCodeReview({
        code: trimmed,
        language,
      });

      setReviewResult(response.review);
      setActiveReviewId(response.id);
      setActiveTab("overview");
      // Refresh history
      loadHistory();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to review code. Please try again.";
      setErrorMessage(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSelectHistoryItem = async (item: CodeReviewHistoryItem) => {
    try {
      const detail = await fetchCodeReviewDetail(item.id);
      setReviewResult(detail.review);
      setActiveReviewId(detail.id);
      setCode(detail.submitted_code);
      setLanguage(detail.language as SupportedLanguage);
      setShowHistoryDrawer(false);
      setActiveTab("overview");
    } catch (err) {
      console.error("Failed to load review detail:", err);
    }
  };

  const handleDeleteHistoryItem = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await deleteCodeReview(id);
      setHistory((prev) => prev.filter((item) => item.id !== id));
      if (activeReviewId === id) {
        setReviewResult(null);
        setActiveReviewId(null);
      }
    } catch (err) {
      console.error("Failed to delete review:", err);
    }
  };

  const handleCopyCorrected = () => {
    if (!reviewResult?.corrected_code) return;
    navigator.clipboard.writeText(reviewResult.corrected_code);
    setCopiedCode(true);
    setTimeout(() => setCopiedCode(false), 2000);
  };

  const getAssessmentBadge = (assessment: string, score: number) => {
    switch (assessment) {
      case "excellent":
        return {
          label: "Excellent",
          bg: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
          icon: CheckCircle2,
        };
      case "good":
        return {
          label: "Good",
          bg: "bg-blue-500/10 text-blue-300 border-blue-500/30",
          icon: CheckCircle2,
        };
      case "needs_improvement":
        return {
          label: "Needs Improvement",
          bg: "bg-amber-500/10 text-amber-300 border-amber-500/30",
          icon: AlertTriangle,
        };
      case "critical_bugs":
      case "problematic":
      default:
        return {
          label: assessment === "critical_bugs" ? "Critical Bugs" : "Problematic",
          bg: "bg-rose-500/10 text-rose-300 border-rose-500/30",
          icon: XCircle,
        };
    }
  };

  const getSeverityPill = (severity: string) => {
    switch (severity) {
      case "critical":
        return "bg-rose-500/15 text-rose-300 border-rose-500/30";
      case "high":
        return "bg-orange-500/15 text-orange-300 border-orange-500/30";
      case "medium":
        return "bg-amber-500/15 text-amber-300 border-amber-500/30";
      case "low":
      default:
        return "bg-blue-500/15 text-blue-300 border-blue-500/30";
    }
  };

  const formatDurationMs = (ms: number) => {
    if (ms >= 1000) {
      return `${(ms / 1000).toFixed(2)} s`;
    }
    return `${Math.round(ms * 10) / 10} ms`;
  };

  const getExecutionStatusMeta = (res: ExecutionResult) => {
    switch (res.status) {
      case "success":
        return {
          label: "Success",
          classes: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
          icon: CheckCircle2,
          notice: null,
        };
      case "compilation_error":
        return {
          label: "Compilation Error",
          classes: "bg-rose-500/10 text-rose-300 border-rose-500/30",
          icon: XCircle,
          notice: "Compilation failed before program execution started.",
        };
      case "compilation_timeout":
        return {
          label: "Compilation Timeout",
          classes: "bg-amber-500/10 text-amber-300 border-amber-500/30",
          icon: Clock,
          notice: "Compilation exceeded the server compile time limit and was stopped.",
        };
      case "runtime_error":
        return {
          label: "Runtime Error",
          classes: "bg-rose-500/10 text-rose-300 border-rose-500/30",
          icon: AlertCircle,
          notice: "Program exited with a non-zero status code.",
        };
      case "timeout":
        return {
          label: "Time Limit Exceeded",
          classes: "bg-amber-500/10 text-amber-300 border-amber-500/30",
          icon: Clock,
          notice: "Execution exceeded the allowed runtime limit and was terminated.",
        };
      case "output_limit_exceeded":
        return {
          label: "Output Limit Exceeded",
          classes: "bg-amber-500/10 text-amber-300 border-amber-500/30",
          icon: AlertTriangle,
          notice: "Program output exceeded the 64 KB buffer limit and was truncated.",
        };
      case "validation_error":
        return {
          label: "Validation Error",
          classes: "bg-rose-500/10 text-rose-300 border-rose-500/30",
          icon: AlertCircle,
          notice: "Input did not meet server execution constraints.",
        };
      case "infrastructure_error":
      default:
        return {
          label: "Sandbox Unavailable",
          classes: "bg-rose-500/10 text-rose-300 border-rose-500/30",
          icon: AlertTriangle,
          notice: "Code execution sandbox infrastructure is currently unavailable.",
        };
    }
  };

  const stdinByteLength = new TextEncoder().encode(stdinInput).length;

  return (
    <div className="space-y-6">
      {/* Top Banner / Workspace Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 p-5 rounded-xl border border-slate-800/80 bg-[#0d121f]">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400">
            <Code2 className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-bold text-white tracking-tight">AI Code Reviewer</h1>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-950/50 text-cyan-300 border border-cyan-800/50">
                LangGraph Multi-Stage
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Deep static analysis, boundary edge-cases, Big-O complexity derivation & intent-preserving refactoring
            </p>
          </div>
        </div>

        {/* History Toggle Button */}
        <div className="flex items-center gap-2.5">
          <button
            onClick={() => setShowHistoryDrawer(!showHistoryDrawer)}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-900 border border-slate-800 hover:border-slate-700 text-xs text-slate-300 hover:text-white transition-colors cursor-pointer"
          >
            <History className="w-3.5 h-3.5 text-slate-400" />
            <span>Past Reviews</span>
            {history.length > 0 && (
              <span className="px-1.5 py-0.2 rounded-full bg-indigo-500/20 text-indigo-300 font-mono text-[10px] border border-indigo-500/30">
                {history.length}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Main Split Grid: Editor (Left) & Results (Right) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Monaco Editor (7 cols) */}
        <div className="lg:col-span-6 flex flex-col space-y-4">
          <div className="rounded-xl border border-slate-800/80 bg-[#0d121f] overflow-hidden flex flex-col flex-1">
            {/* Editor Toolbar */}
            <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b border-slate-800/80 bg-[#090d16]">
              {/* Language Selector */}
              <div className="flex items-center gap-1.5 p-1 rounded-lg bg-slate-900 border border-slate-800">
                {(["python", "java", "cpp"] as SupportedLanguage[]).map((lang) => (
                  <button
                    key={lang}
                    onClick={() => handleLanguageChange(lang)}
                    disabled={isRunning}
                    className={`px-2.5 py-1 rounded text-xs font-medium transition-colors cursor-pointer disabled:opacity-50 ${
                      language === lang
                        ? "bg-indigo-600 text-white shadow-sm"
                        : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {lang === "python" ? "Python" : lang === "java" ? "Java" : "C++"}
                  </button>
                ))}
              </div>

              {/* Sample Code Dropdown / Buttons */}
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-slate-500">Samples:</span>
                <div className="flex gap-1.5">
                  {SAMPLE_CODES[language].map((sample, idx) => (
                    <button
                      key={idx}
                      onClick={() => handleLoadSample(sample)}
                      disabled={isRunning}
                      title={sample.description}
                      className="text-[11px] px-2 py-1 rounded bg-slate-800/60 hover:bg-slate-800 text-slate-300 border border-slate-700/60 hover:text-white transition-colors cursor-pointer disabled:opacity-50"
                    >
                      {sample.title.split(" ")[0]}
                    </button>
                  ))}
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center gap-2">
                <button
                  onClick={handleClear}
                  disabled={!code || isSubmitting || isRunning}
                  className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-400 hover:text-slate-200 text-xs disabled:opacity-40 transition-colors cursor-pointer"
                  title="Clear editor"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  <span>Clear</span>
                </button>

                <button
                  onClick={handleRunCode}
                  disabled={isRunning || !code.trim()}
                  className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-xs disabled:opacity-50 transition-colors shadow-lg shadow-emerald-950/40 cursor-pointer"
                  title="Execute code in isolated sandbox"
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

                <button
                  onClick={handleSubmitReview}
                  disabled={isSubmitting || !code.trim()}
                  className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs disabled:opacity-50 transition-colors shadow-lg shadow-indigo-950/40 cursor-pointer"
                >
                  {isSubmitting ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>Reviewing...</span>
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-3.5 h-3.5" />
                      <span>Review Code</span>
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* Monaco Editor Container */}
            <div className="h-[520px] w-full relative">
              <Editor
                height="100%"
                language={MONACO_LANG_MAP[language]}
                theme="vs-dark"
                value={code}
                onChange={(val) => setCode(val || "")}
                options={{
                  fontSize: 13,
                  fontFamily: "'Fira Code', 'JetBrains Mono', Consolas, monospace",
                  minimap: { enabled: false },
                  scrollBeyondLastLine: false,
                  lineNumbers: "on",
                  roundedSelection: false,
                  automaticLayout: true,
                  padding: { top: 12, bottom: 12 },
                  tabSize: 4,
                  renderLineHighlight: "all",
                  overviewRulerLanes: 0,
                  hideCursorInOverviewRuler: true,
                }}
              />
            </div>

            {/* Editor Footer Status */}
            <div className="px-4 py-2 bg-[#090d16] border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-500">
              <div className="flex items-center gap-3">
                <span className="font-mono">{code.length} characters</span>
                <span>•</span>
                <span className="font-mono">{code.split("\n").length} lines</span>
              </div>
              <div className="flex items-center gap-1.5 text-slate-400">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                <span>Isolated Sandbox Execution &amp; Static Analysis</span>
              </div>
            </div>
          </div>

          {/* Error Banner if any */}
          {errorMessage && (
            <div className="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-start gap-3 text-rose-300 text-xs">
              <AlertCircle className="w-4 h-4 shrink-0 text-rose-400 mt-0.5" />
              <div>
                <p className="font-semibold">Review Error</p>
                <p className="mt-0.5 text-rose-300/90">{errorMessage}</p>
              </div>
            </div>
          )}
        </div>

        {/* Right Column: Review Results Panel (6 cols) */}
        <div className="lg:col-span-6 flex flex-col space-y-4">
          {/* If no review yet and not submitting */}
          {!reviewResult && !isSubmitting && (
            <div className="rounded-xl border border-dashed border-slate-800 bg-[#0d121f]/50 p-12 flex flex-col items-center justify-center text-center space-y-3 h-[580px]">
              <div className="w-12 h-12 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 flex items-center justify-center">
                <Sparkles className="w-6 h-6" />
              </div>
              <h3 className="text-sm font-semibold text-white">Awaiting Code Submission</h3>
              <p className="text-xs text-slate-400 max-w-sm leading-relaxed">
                Choose Python, Java, or C++, paste your algorithm or function in the Monaco editor, and click{" "}
                <span className="text-indigo-300 font-semibold">&ldquo;Review Code&rdquo;</span> to run multi-agent static and algorithmic validation.
              </p>
              <div className="pt-2 flex flex-wrap gap-2 justify-center">
                <span className="text-[10px] px-2.5 py-1 rounded bg-slate-900 border border-slate-800 text-slate-400 font-mono">
                  Python AST syntax check
                </span>
                <span className="text-[10px] px-2.5 py-1 rounded bg-slate-900 border border-slate-800 text-slate-400 font-mono">
                  Big-O proof
                </span>
                <span className="text-[10px] px-2.5 py-1 rounded bg-slate-900 border border-slate-800 text-slate-400 font-mono">
                  6-factor edge cases
                </span>
              </div>
            </div>
          )}

          {/* Loading State Spinner Card */}
          {isSubmitting && (
            <div className="rounded-xl border border-slate-800/80 bg-[#0d121f] p-12 flex flex-col items-center justify-center text-center space-y-4 h-[580px]">
              <div className="relative">
                <div className="w-14 h-14 rounded-2xl bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400 animate-pulse">
                  <Layers className="w-7 h-7" />
                </div>
                <div className="absolute -inset-1 rounded-2xl bg-indigo-500/10 blur animate-spin" />
              </div>
              <div className="space-y-1">
                <h3 className="text-sm font-semibold text-white">Orchestrating Review Pipeline</h3>
                <p className="text-xs text-slate-400 max-w-sm">
                  LangGraph executing nodes: Static AST check → Gemini Code Inspector → Boundary edge-cases → Big-O complexity derivation...
                </p>
              </div>
              <div className="flex items-center gap-2 text-[11px] text-indigo-400 font-mono">
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                <span>Processing source code</span>
              </div>
            </div>
          )}

          {/* Completed Review Panel */}
          {reviewResult && !isSubmitting && (
            <div className="rounded-xl border border-slate-800/80 bg-[#0d121f] flex flex-col flex-1 overflow-hidden h-[580px]">
              {/* Header: Score & Overall Assessment */}
              <div className="px-5 py-4 border-b border-slate-800/80 bg-[#090d16] flex items-center justify-between">
                <div className="flex items-center gap-3">
                  {/* Quality Score Circle Badge */}
                  <div className="flex items-center justify-center w-11 h-11 rounded-xl bg-slate-900 border border-slate-800 font-mono font-bold text-lg text-white">
                    <span className={reviewResult.quality_score >= 8 ? "text-emerald-400" : reviewResult.quality_score >= 5 ? "text-amber-400" : "text-rose-400"}>
                      {reviewResult.quality_score}
                    </span>
                    <span className="text-[10px] text-slate-500 font-normal">/10</span>
                  </div>

                  <div>
                    {(() => {
                      const badge = getAssessmentBadge(reviewResult.overall_assessment, reviewResult.quality_score);
                      const BadgeIcon = badge.icon;
                      return (
                        <div className="flex items-center gap-2">
                          <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${badge.bg}`}>
                            <BadgeIcon className="w-3 h-3" />
                            {badge.label}
                          </span>
                        </div>
                      );
                    })()}
                    <p className="text-[11px] text-slate-400 mt-1 line-clamp-1">{reviewResult.summary}</p>
                  </div>
                </div>

                {/* Sub-Badges: Time & Space Quick Preview */}
                <div className="hidden sm:flex items-center gap-2">
                  <div className="px-2.5 py-1 rounded bg-slate-900 border border-slate-800 text-right">
                    <span className="text-[10px] text-slate-500 block">Time</span>
                    <span className="text-xs font-mono font-semibold text-cyan-400">{reviewResult.complexity.time_complexity}</span>
                  </div>
                  <div className="px-2.5 py-1 rounded bg-slate-900 border border-slate-800 text-right">
                    <span className="text-[10px] text-slate-500 block">Space</span>
                    <span className="text-xs font-mono font-semibold text-emerald-400">{reviewResult.complexity.space_complexity}</span>
                  </div>
                </div>
              </div>

              {/* Navigation Tabs for Results */}
              <div className="flex items-center border-b border-slate-800/80 bg-[#070b13] px-3 overflow-x-auto">
                <button
                  onClick={() => setActiveTab("overview")}
                  className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors cursor-pointer whitespace-nowrap ${
                    activeTab === "overview"
                      ? "border-indigo-500 text-indigo-300"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  Overview & Quality
                </button>
                <button
                  onClick={() => setActiveTab("issues")}
                  className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${
                    activeTab === "issues"
                      ? "border-indigo-500 text-indigo-300"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <span>Detected Issues</span>
                  <span className="px-1.5 py-0.2 rounded-full bg-slate-800 text-slate-300 font-mono text-[10px]">
                    {reviewResult.detected_issues.length}
                  </span>
                </button>
                <button
                  onClick={() => setActiveTab("complexity")}
                  className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors cursor-pointer whitespace-nowrap ${
                    activeTab === "complexity"
                      ? "border-indigo-500 text-indigo-300"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  Complexity Proof
                </button>
                <button
                  onClick={() => setActiveTab("edge_cases")}
                  className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors cursor-pointer whitespace-nowrap ${
                    activeTab === "edge_cases"
                      ? "border-indigo-500 text-indigo-300"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  Edge Cases ({reviewResult.edge_cases.length})
                </button>
                {reviewResult.corrected_code && (
                  <button
                    onClick={() => setActiveTab("corrected")}
                    className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${
                      activeTab === "corrected"
                        ? "border-indigo-500 text-indigo-300"
                        : "border-transparent text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <Sparkles className="w-3 h-3 text-indigo-400" />
                    <span>Corrected Code</span>
                  </button>
                )}
              </div>

              {/* Tab Contents: Scrollable */}
              <div className="flex-1 overflow-y-auto p-5 space-y-4">
                {/* 1. OVERVIEW TAB */}
                {activeTab === "overview" && (
                  <div className="space-y-4">
                    {/* Executive Summary */}
                    <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2">
                      <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
                        <Info className="w-4 h-4 text-cyan-400" />
                        <span>Executive Summary</span>
                      </div>
                      <p className="text-xs text-slate-300 leading-relaxed">{reviewResult.summary}</p>
                    </div>

                    {/* Static Verification Note */}
                    {reviewResult.static_analysis_notes && (
                      <div className="p-3.5 rounded-xl bg-slate-900/40 border border-slate-800/80 flex items-start gap-2.5 text-xs text-slate-400">
                        <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                        <div>
                          <span className="font-semibold text-slate-300">Static AST Inspection:</span>{" "}
                          <span>{reviewResult.static_analysis_notes}</span>
                        </div>
                      </div>
                    )}

                    {/* Improvement Suggestions */}
                    {reviewResult.improvement_suggestions.length > 0 && (
                      <div className="space-y-2">
                        <h4 className="text-xs font-semibold text-white uppercase tracking-wider text-[11px] text-slate-400">
                          Recommended Improvements
                        </h4>
                        <div className="space-y-1.5">
                          {reviewResult.improvement_suggestions.map((sug, i) => (
                            <div key={i} className="flex items-start gap-2.5 p-2.5 rounded-lg bg-slate-900/40 border border-slate-800/60 text-xs text-slate-300">
                              <ChevronRight className="w-3.5 h-3.5 text-indigo-400 shrink-0 mt-0.5" />
                              <span>{sug}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* 2. DETECTED ISSUES TAB */}
                {activeTab === "issues" && (
                  <div className="space-y-3">
                    {reviewResult.detected_issues.length === 0 ? (
                      <div className="p-8 text-center text-slate-400 text-xs">
                        <CheckCircle2 className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
                        <p className="text-white font-medium">No major bugs detected!</p>
                        <p className="text-slate-500 mt-1">Code conforms to standard algorithmic safety guidelines.</p>
                      </div>
                    ) : (
                      reviewResult.detected_issues.map((issue, idx) => (
                        <div
                          key={idx}
                          className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${getSeverityPill(issue.severity)}`}>
                                {issue.severity}
                              </span>
                              <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-400 text-[10px] font-mono">
                                {issue.type}
                              </span>
                            </div>
                            {issue.line_number && (
                              <span className="text-[11px] font-mono text-slate-400">
                                Line {issue.line_number}
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-slate-200 font-medium">{issue.message}</p>
                          {issue.suggestion && (
                            <div className="p-2 rounded bg-indigo-950/20 border border-indigo-500/20 text-xs text-indigo-300 flex items-start gap-2">
                              <Zap className="w-3.5 h-3.5 text-indigo-400 shrink-0 mt-0.5" />
                              <span>{issue.suggestion}</span>
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                )}

                {/* 3. COMPLEXITY ANALYSIS TAB */}
                {activeTab === "complexity" && (
                  <div className="space-y-4">
                    {/* Time Complexity Card */}
                    <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-xs font-semibold text-cyan-300">
                          <Clock className="w-4 h-4 text-cyan-400" />
                          <span>Time Complexity</span>
                        </div>
                        <span className="px-2.5 py-0.5 rounded-lg bg-cyan-950/60 border border-cyan-800/60 font-mono font-bold text-sm text-cyan-300">
                          {reviewResult.complexity.time_complexity}
                        </span>
                      </div>
                      <p className="text-xs text-slate-300 leading-relaxed pl-6">
                        {reviewResult.complexity.time_reasoning}
                      </p>
                    </div>

                    {/* Space Complexity Card */}
                    <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-xs font-semibold text-emerald-300">
                          <Layers className="w-4 h-4 text-emerald-400" />
                          <span>Auxiliary Space Complexity</span>
                        </div>
                        <span className="px-2.5 py-0.5 rounded-lg bg-emerald-950/60 border border-emerald-800/60 font-mono font-bold text-sm text-emerald-300">
                          {reviewResult.complexity.space_complexity}
                        </span>
                      </div>
                      <p className="text-xs text-slate-300 leading-relaxed pl-6">
                        {reviewResult.complexity.space_reasoning}
                      </p>
                    </div>
                  </div>
                )}

                {/* 4. EDGE CASES TAB */}
                {activeTab === "edge_cases" && (
                  <div className="space-y-3">
                    {reviewResult.edge_cases.map((ec, idx) => (
                      <div
                        key={idx}
                        className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 space-y-1.5"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-white">{ec.category}</span>
                          <span
                            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold ${
                              ec.handled
                                ? "bg-emerald-500/10 text-emerald-300 border border-emerald-500/20"
                                : "bg-rose-500/10 text-rose-300 border border-rose-500/20"
                            }`}
                          >
                            {ec.handled ? (
                              <>
                                <Check className="w-3 h-3" /> Handled
                              </>
                            ) : (
                              <>
                                <XCircle className="w-3 h-3" /> Unhandled Risk
                              </>
                            )}
                          </span>
                        </div>
                        <p className="text-xs text-slate-300">
                          <span className="text-slate-500">Scenario:</span> {ec.scenario}
                        </p>
                        <p className="text-xs text-slate-400">
                          <span className="text-slate-500">Predicted Behavior:</span> {ec.behavior}
                        </p>
                      </div>
                    ))}
                  </div>
                )}

                {/* 5. CORRECTED CODE TAB */}
                {activeTab === "corrected" && reviewResult.corrected_code && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-400">Intent-preserving corrected refactoring:</span>
                      <button
                        onClick={handleCopyCorrected}
                        className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 transition-colors cursor-pointer"
                      >
                        {copiedCode ? (
                          <>
                            <Check className="w-3 h-3 text-emerald-400" />
                            <span>Copied</span>
                          </>
                        ) : (
                          <>
                            <Copy className="w-3 h-3" />
                            <span>Copy Code</span>
                          </>
                        )}
                      </button>
                    </div>

                    <div className="rounded-lg bg-[#070b13] border border-slate-800 p-3 font-mono text-xs text-indigo-300 overflow-x-auto">
                      <pre className="leading-relaxed">{reviewResult.corrected_code}</pre>
                    </div>

                    {reviewResult.explanation_of_changes && (
                      <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 text-xs text-slate-300 space-y-1">
                        <span className="font-semibold text-white">Explanation of Changes:</span>
                        <p className="leading-relaxed text-slate-300">{reviewResult.explanation_of_changes}</p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Sandbox Execution Workspace: Standard Input & Console Output */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Standard Input (stdin) Panel (4 cols) */}
        <div className="lg:col-span-4 rounded-xl border border-slate-800/80 bg-[#0d121f] overflow-hidden flex flex-col">
          <div className="px-4 py-3 border-b border-slate-800/80 bg-[#090d16] flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <FileCode className="w-4 h-4 text-cyan-400" />
              <h2 className="text-xs font-semibold text-white">Standard Input (stdin)</h2>
            </div>
            {stdinInput.length > 0 && (
              <button
                onClick={() => setStdinInput("")}
                disabled={isRunning}
                className="text-[11px] text-slate-400 hover:text-slate-200 disabled:opacity-40 transition-colors cursor-pointer"
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
              className="w-full flex-1 min-h-[128px] rounded-lg bg-[#070b13] border border-slate-800 focus:border-emerald-500/50 focus:outline-none p-3 font-mono text-xs text-slate-200 placeholder:text-slate-600 resize-y disabled:opacity-60"
            />
          </div>

          <div className="px-4 py-2 bg-[#090d16] border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-500">
            <span className={`font-mono ${stdinByteLength > 65536 ? "text-rose-400" : ""}`}>
              {stdinByteLength.toLocaleString()} / 65,536 bytes
            </span>
            <span>Passed separately from source</span>
          </div>
        </div>

        {/* Execution Console Output Panel (8 cols) */}
        <div className="lg:col-span-8 rounded-xl border border-slate-800/80 bg-[#0d121f] overflow-hidden flex flex-col">
          {/* Console Header */}
          <div className="px-4 py-3 border-b border-slate-800/80 bg-[#090d16] flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2.5">
              <div className="flex items-center gap-2">
                <Terminal className="w-4 h-4 text-emerald-400" />
                <h2 className="text-xs font-semibold text-white">Execution Console</h2>
              </div>

              {isRunning && (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-cyan-500/10 text-cyan-300 border border-cyan-500/30">
                  <RefreshCw className="w-3 h-3 animate-spin" />
                  Running
                </span>
              )}

              {!isRunning && executionResult && (() => {
                const meta = getExecutionStatusMeta(executionResult);
                const StatusIcon = meta.icon;
                return (
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${meta.classes}`}>
                    <StatusIcon className="w-3 h-3" />
                    {meta.label}
                  </span>
                );
              })()}

              {!isRunning && !executionResult && executionError && (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold border bg-rose-500/10 text-rose-300 border-rose-500/30">
                  <AlertCircle className="w-3 h-3" />
                  {executionError.title}
                </span>
              )}
            </div>

            <div className="flex items-center gap-3">
              {!isRunning && executionResult && (
                <div className="flex flex-wrap items-center gap-2 text-[11px] font-mono text-slate-400">
                  {executionResult.compile_duration_ms !== null && (
                    <span className="px-2 py-0.5 rounded bg-slate-900 border border-slate-800">
                      Compile: {formatDurationMs(executionResult.compile_duration_ms)}
                    </span>
                  )}
                  <span className="px-2 py-0.5 rounded bg-slate-900 border border-slate-800 flex items-center gap-1">
                    <Clock className="w-3 h-3 text-slate-500" />
                    {formatDurationMs(executionResult.duration_ms)}
                  </span>
                  {executionResult.exit_code !== null && (
                    <span className="px-2 py-0.5 rounded bg-slate-900 border border-slate-800">
                      Exit: {executionResult.exit_code}
                    </span>
                  )}
                </div>
              )}

              <button
                onClick={handleClearConsole}
                disabled={isRunning || (!executionResult && !executionError)}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-900 border border-slate-800 hover:border-slate-700 text-[11px] text-slate-400 hover:text-slate-200 disabled:opacity-40 transition-colors cursor-pointer"
                title="Clear console output"
              >
                <Trash2 className="w-3 h-3" />
                <span>Clear Console</span>
              </button>
            </div>
          </div>

          {/* Console Body */}
          <div className="p-4 flex-1 min-h-[168px] max-h-[340px] overflow-y-auto space-y-3 bg-[#070b13]">
            {/* Loading State */}
            {isRunning && (
              <div className="py-10 flex flex-col items-center justify-center text-center space-y-2">
                <RefreshCw className="w-5 h-5 text-emerald-400 animate-spin" />
                <p className="text-xs font-medium text-slate-200">
                  Executing {language === "cpp" ? "C++" : language === "java" ? "Java" : "Python"} code in sandbox...
                </p>
                <p className="text-[11px] text-slate-500">
                  Wait for execution to complete before submitting another run.
                </p>
              </div>
            )}

            {/* API / Auth / Rate-limit Error State without ExecutionResult */}
            {!isRunning && !executionResult && executionError && (
              <div className="p-3.5 rounded-lg bg-rose-500/10 border border-rose-500/25 flex items-start gap-3 text-xs text-rose-200">
                <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <p className="font-semibold text-rose-300">{executionError.title}</p>
                  <p className="text-rose-200/90 leading-relaxed">{executionError.message}</p>
                </div>
              </div>
            )}

            {/* Structured Sandbox Result */}
            {!isRunning && executionResult && (
              <div className="space-y-3">
                {(() => {
                  const meta = getExecutionStatusMeta(executionResult);
                  if (!meta.notice) return null;
                  const NoticeIcon = meta.icon;
                  const isWarning =
                    executionResult.status === "timeout" ||
                    executionResult.status === "compilation_timeout" ||
                    executionResult.status === "output_limit_exceeded";
                  return (
                    <div
                      className={`p-3 rounded-lg border flex items-start gap-2.5 text-xs ${
                        isWarning
                          ? "bg-amber-500/10 border-amber-500/25 text-amber-200"
                          : "bg-rose-500/10 border-rose-500/25 text-rose-200"
                      }`}
                    >
                      <NoticeIcon className={`w-4 h-4 shrink-0 mt-0.5 ${isWarning ? "text-amber-400" : "text-rose-400"}`} />
                      <div className="space-y-0.5">
                        <p className="font-medium">{meta.notice}</p>
                        {executionResult.truncated && (
                          <p className="text-[11px] opacity-85">
                            Output was truncated to stay within the 64 KB console limit.
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })()}

                {/* Compilation Error Diagnostics */}
                {executionResult.compilation_error && (
                  <div className="space-y-1.5">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-rose-400">
                      Compilation Error
                    </span>
                    <pre className="p-3 rounded-lg bg-[#0b101b] border border-rose-500/25 font-mono text-xs text-rose-300 whitespace-pre-wrap break-words overflow-x-auto leading-relaxed">
                      {executionResult.compilation_error}
                    </pre>
                  </div>
                )}

                {/* Standard Output */}
                {executionResult.stdout && (
                  <div className="space-y-1.5">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                      Standard Output
                    </span>
                    <pre className="p-3 rounded-lg bg-[#0b101b] border border-slate-800 font-mono text-xs text-emerald-300 whitespace-pre-wrap break-words overflow-x-auto leading-relaxed">
                      {executionResult.stdout}
                    </pre>
                  </div>
                )}

                {/* Standard Error */}
                {executionResult.stderr && (
                  <div className="space-y-1.5">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-rose-400">
                      Standard Error
                    </span>
                    <pre className="p-3 rounded-lg bg-[#0b101b] border border-rose-500/25 font-mono text-xs text-rose-300 whitespace-pre-wrap break-words overflow-x-auto leading-relaxed">
                      {executionResult.stderr}
                    </pre>
                  </div>
                )}

                {/* Empty output for clean success */}
                {executionResult.status === "success" &&
                  !executionResult.stdout &&
                  !executionResult.stderr && (
                    <p className="text-xs text-slate-400 font-mono py-2">
                      Program exited cleanly (exit code 0) with no output.
                    </p>
                  )}
              </div>
            )}

            {/* Empty Initial State */}
            {!isRunning && !executionResult && !executionError && (
              <div className="py-10 flex flex-col items-center justify-center text-center space-y-1.5">
                <Terminal className="w-5 h-5 text-slate-600" />
                <p className="text-xs text-slate-400">
                  Click <span className="text-emerald-400 font-semibold">&ldquo;Run Code&rdquo;</span> to execute your code and view stdout, stderr, compiler diagnostics, and runtime duration.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Slide-out Review History Drawer */}
      {showHistoryDrawer && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-sm animate-in fade-in">
          <div className="w-full max-w-md bg-[#0d121f] border-l border-slate-800 h-full p-6 flex flex-col justify-between shadow-2xl">
            <div className="space-y-4">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <div className="flex items-center gap-2">
                  <History className="w-4 h-4 text-cyan-400" />
                  <h3 className="text-sm font-bold text-white">Review History</h3>
                </div>
                <button
                  onClick={() => setShowHistoryDrawer(false)}
                  className="text-xs text-slate-400 hover:text-white"
                >
                  Close
                </button>
              </div>

              {isLoadingHistory ? (
                <div className="py-12 text-center text-slate-400 text-xs flex items-center justify-center gap-2">
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Loading past reviews...</span>
                </div>
              ) : history.length === 0 ? (
                <div className="py-12 text-center text-slate-400 text-xs">
                  <p>No code reviews found in your account.</p>
                  <p className="text-slate-500 mt-1">Submit your first code review above!</p>
                </div>
              ) : (
                <div className="space-y-2.5 overflow-y-auto max-h-[75vh] pr-1">
                  {history.map((item) => (
                    <div
                      key={item.id}
                      onClick={() => handleSelectHistoryItem(item)}
                      className={`p-3 rounded-xl border transition-all cursor-pointer ${
                        activeReviewId === item.id
                          ? "bg-indigo-950/20 border-indigo-500/40"
                          : "bg-slate-900/60 border-slate-800/80 hover:border-slate-700"
                      }`}
                    >
                      <div className="flex items-center justify-between text-xs mb-1.5">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[10px] font-bold px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 uppercase">
                            {item.language}
                          </span>
                          <span className="text-[11px] font-semibold text-white">
                            Score: {item.quality_score}/10
                          </span>
                        </div>
                        <button
                          onClick={(e) => handleDeleteHistoryItem(e, item.id)}
                          className="text-slate-500 hover:text-rose-400 p-1 transition-colors"
                          title="Delete review"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>

                      <p className="text-xs text-slate-300 font-mono truncate">{item.code_snippet}</p>
                      <p className="text-[11px] text-slate-400 mt-1 line-clamp-1">{item.summary}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="pt-4 border-t border-slate-800">
              <button
                onClick={() => setShowHistoryDrawer(false)}
                className="w-full py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 transition-colors"
              >
                Close Drawer
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


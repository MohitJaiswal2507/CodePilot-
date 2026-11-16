"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import Editor, { OnMount } from "@monaco-editor/react";
import {
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
  X,
  ChevronRight,
  Info,
} from "lucide-react";
import {
  submitCodeReview,
  fetchCodeReviewHistory,
  fetchCodeReviewDetail,
  deleteCodeReview,
  ExecutionResult,
  CodeReviewResult,
  CodeReviewResponse,
  CodeReviewHistoryItem,
} from "@/services/api";
import { ExecutionConsole } from "@/components/sandbox/ExecutionConsole";
import {
  ExecutionErrorState,
  MONACO_LANG_MAP,
  SupportedLanguage,
  mapSandboxApiError,
} from "@/lib/sandbox";
import { buildMonacoOptions, getEditorSettings } from "@/lib/editorSettings";
import { useLocalRuntime } from "@/hooks/useLocalRuntime";

interface SampleCode {
  title: string;
  code: string;
  description: string;
  stdin?: string;
}

const SAMPLE_CODES: Record<SupportedLanguage, SampleCode[]> = {
  python: [
    {
      title: "Binary Search (Buggy Off-by-One)",
      description: "Infinite loop condition & missing edge-case check",
      stdin: "7",
      code: `import sys

def binary_search(arr, target):
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
            
    return -1

if __name__ == "__main__":
    nums = [1, 3, 5, 7, 9, 11, 13]
    stdin_target = sys.stdin.read().strip()
    target = int(stdin_target) if stdin_target.isdigit() else 7

    print(f"Sorted array: {nums}")
    print(f"Searching for target: {target}")
    result = binary_search(nums, target)
    print(f"Target found at index: {result}")`,
    },
    {
      title: "Two Sum (Quadratic O(N^2))",
      description: "Unnecessary nested loop that can be optimized to O(N)",
      stdin: "",
      code: `def two_sum(nums, target):
    # Quadratic brute force approach: O(N^2)
    n = len(nums)
    for i in range(n):
        for j in range(i + 1, n):
            if nums[i] + nums[j] == target:
                return [i, j]
    return []

if __name__ == "__main__":
    numbers = [2, 7, 11, 15]
    target = 9
    print(f"Array: {numbers}, Target: {target}")
    indices = two_sum(numbers, target)
    print(f"Indices: {indices}")`,
    },
    {
      title: "Recursive Fibonacci (Exponential O(2^N))",
      description: "Exponential recursion without memoization",
      stdin: "",
      code: `def fibonacci(n):
    # Exponential recursion: O(2^N) without memoization
    if n <= 0:
        return 0
    if n == 1:
        return 1
    return fibonacci(n - 1) + fibonacci(n - 2)

if __name__ == "__main__":
    n = 8
    print(f"Calculating Fibonacci({n}) using naive recursion...")
    result = fibonacci(n)
    print(f"Fibonacci({n}) = {result}")`,
    },
  ],
  java: [
    {
      title: "String Palindrome Check (Buggy)",
      description: "String comparison using == instead of .equals()",
      stdin: "Racecar",
      code: `import java.util.Scanner;

public class PalindromeCheck {
    public static boolean isPalindrome(String s) {
        if (s == null) return false;
        String clean = s.toLowerCase().replaceAll("[^a-zA-Z0-9]", "");
        String reversed = new StringBuilder(clean).reverse().toString();
        // Bug: uses reference equality (==) instead of content equality (.equals())
        return clean == reversed;
    }

    public static void main(String[] args) {
        Scanner scanner = new Scanner(System.in);
        String input = scanner.hasNextLine() ? scanner.nextLine().trim() : "";
        if (input.isEmpty()) {
            input = "Racecar";
        }
        boolean result = isPalindrome(input);
        System.out.println("Testing palindrome: \\"" + input + "\\"");
        System.out.println("Result: " + result);
        if (!result) {
            System.out.println("Notice: Comparison returned false because == checks reference identity, not string value!");
        }
    }
}`,
    },
    {
      title: "Array Max Finder",
      description: "Unchecked empty array causing ArrayIndexOutOfBoundsException",
      stdin: "5\\n3 7 2 9 5",
      code: `import java.util.Arrays;
import java.util.Scanner;

public class ArrayUtils {
    public static int findMax(int[] arr) {
        // Bug: no validation for null or empty array (arr[0] throws on empty array)
        int max = arr[0];
        for (int i = 1; i < arr.length; i++) {
            if (arr[i] > max) {
                max = arr[i];
            }
        }
        return max;
    }

    public static void main(String[] args) {
        Scanner scanner = new Scanner(System.in);
        int[] numbers;
        if (scanner.hasNextInt()) {
            int n = scanner.nextInt();
            numbers = new int[n];
            for (int i = 0; i < n; i++) {
                numbers[i] = scanner.nextInt();
            }
        } else {
            numbers = new int[]{3, 7, 2, 9, 5};
        }

        System.out.println("Input array: " + Arrays.toString(numbers));
        int maxVal = findMax(numbers);
        System.out.println("Max element: " + maxVal);
    }
}`,
    },
  ],
  cpp: [
    {
      title: "Memory Leak & Raw Pointer",
      description: "Dynamically allocated buffer without delete[]",
      stdin: "5",
      code: `#include <iostream>
#include <vector>

void processData(int size) {
    // Memory leak: allocated on heap with new[] but never deleted
    int* buffer = new int[size];
    for (int i = 0; i < size; ++i) {
        buffer[i] = (i + 1) * 10;
    }
    std::cout << "Allocated and processed " << size << " integers in buffer." << std::endl;
    std::cout << "Buffer contents: ";
    for (int i = 0; i < size; ++i) {
        std::cout << buffer[i] << " ";
    }
    std::cout << std::endl;
    // Missing: delete[] buffer;
}

int main() {
    int count = 5;
    if (std::cin >> count) {
        // Read buffer size from standard input if provided
    }
    std::cout << "Starting memory test with size = " << count << std::endl;
    processData(count);
    std::cout << "Execution complete (raw heap memory leaked)." << std::endl;
    return 0;
}`,
    },
    {
      title: "Vector Subscript Out of Range",
      description: "Loop bounds off by one accessing vec[vec.size()]",
      stdin: "",
      code: `#include <iostream>
#include <vector>
#include <numeric>

long long sumElements(const std::vector<int>& vec) {
    long long total = 0;
    // Bug: loop condition <= vec.size() causes out-of-bounds access at index vec.size()
    for (size_t i = 0; i <= vec.size(); ++i) {
        total += vec[i];
    }
    return total;
}

int main() {
    std::vector<int> numbers = {10, 20, 30, 40, 50};
    std::cout << "Vector elements (" << numbers.size() << " items): ";
    for (int num : numbers) {
        std::cout << num << " ";
    }
    std::cout << std::endl;

    std::cout << "Summing vector with boundary loop..." << std::endl;
    long long total = sumElements(numbers);
    std::cout << "Computed total: " << total << std::endl;
    return 0;
}`,
    },
  ],
};

function isAbortError(err: unknown): boolean {
  return (
    (err instanceof DOMException && err.name === "AbortError") ||
    (err instanceof Error && err.name === "AbortError")
  );
}

function isSupportedLanguage(lang: string): lang is SupportedLanguage {
  return lang === "python" || lang === "java" || lang === "cpp";
}

export function CodeReviewer() {
  const [editorSettings] = useState(() => getEditorSettings());
  const [language, setLanguage] = useState<SupportedLanguage>(editorSettings.defaultLanguage);
  const [code, setCode] = useState<string>(SAMPLE_CODES[editorSettings.defaultLanguage][0].code);
  const [stdinInput, setStdinInput] = useState<string>(
    SAMPLE_CODES[editorSettings.defaultLanguage][0].stdin ?? ""
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [reviewResult, setReviewResult] = useState<CodeReviewResult | null>(null);
  const [executionResult, setExecutionResult] = useState<ExecutionResult | null>(null);
  const [executionError, setExecutionError] = useState<ExecutionErrorState | null>(null);
  const [activeReviewId, setActiveReviewId] = useState<string | null>(null);
  const [copiedCode, setCopiedCode] = useState(false);
  const [activeTab, setActiveTab] = useState<"overview" | "issues" | "complexity" | "edge_cases" | "corrected">("overview");

  const { execute: executeRuntime, isPaired: isLocalPaired } = useLocalRuntime();

  // History state
  const [history, setHistory] = useState<CodeReviewHistoryItem[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyActionError, setHistoryActionError] = useState<string | null>(null);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [deletingIds, setDeletingIds] = useState<Set<string>>(() => new Set());
  const [showHistoryDrawer, setShowHistoryDrawer] = useState(false);

  // Lifecycle & concurrency refs
  const isMountedRef = useRef(true);
  const copyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reviewAbortRef = useRef<AbortController | null>(null);
  const detailAbortRef = useRef<AbortController | null>(null);
  const historyAbortRef = useRef<AbortController | null>(null);
  const reviewRequestIdRef = useRef(0);
  const detailRequestIdRef = useRef(0);
  const historyRequestIdRef = useRef(0);
  const deletedIdsRef = useRef<Set<string>>(new Set());
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);

  const handleEditorDidMount: OnMount = useCallback((editor) => {
    editorRef.current = editor;
    setTimeout(() => {
      editor.layout();
    }, 50);
  }, []);

  useEffect(() => {
    const handleResize = () => {
      if (editorRef.current) {
        editorRef.current.layout?.();
      }
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const invalidateActiveReview = useCallback(() => {
    reviewRequestIdRef.current += 1;
    if (reviewAbortRef.current) {
      reviewAbortRef.current.abort();
      reviewAbortRef.current = null;
    }
    if (isMountedRef.current) {
      setIsSubmitting(false);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    historyRequestIdRef.current += 1;
    const requestId = historyRequestIdRef.current;

    if (historyAbortRef.current) {
      historyAbortRef.current.abort();
    }
    const controller = new AbortController();
    historyAbortRef.current = controller;

    if (isMountedRef.current) {
      setIsLoadingHistory(true);
      setHistoryError(null);
    }

    try {
      const data = await fetchCodeReviewHistory(15, 0, { signal: controller.signal });
      if (!isMountedRef.current || requestId !== historyRequestIdRef.current) {
        return;
      }
      const filtered = (data.reviews || []).filter(
        (item) => !deletedIdsRef.current.has(item.id)
      );
      setHistory(filtered);
    } catch (err: unknown) {
      if (isAbortError(err)) {
        return;
      }
      if (isMountedRef.current && requestId === historyRequestIdRef.current) {
        const msg = err instanceof Error ? err.message : "Failed to load review history.";
        setHistoryError(msg);
      }
    } finally {
      if (historyAbortRef.current === controller) {
        historyAbortRef.current = null;
      }
      if (isMountedRef.current && requestId === historyRequestIdRef.current) {
        setIsLoadingHistory(false);
      }
    }
  }, []);

  // Load history on mount & abort all pending reviewer requests/timers on unmount
  useEffect(() => {
    isMountedRef.current = true;
    loadHistory();

    return () => {
      isMountedRef.current = false;
      if (reviewAbortRef.current) {
        reviewAbortRef.current.abort();
        reviewAbortRef.current = null;
      }
      if (detailAbortRef.current) {
        detailAbortRef.current.abort();
        detailAbortRef.current = null;
      }
      if (historyAbortRef.current) {
        historyAbortRef.current.abort();
        historyAbortRef.current = null;
      }
      if (copyTimeoutRef.current) {
        clearTimeout(copyTimeoutRef.current);
        copyTimeoutRef.current = null;
      }
    };
  }, [loadHistory]);

  // Lock body scroll and register Escape listener for review history drawer
  useEffect(() => {
    if (!showHistoryDrawer) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setShowHistoryDrawer(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = originalOverflow;
    };
  }, [showHistoryDrawer]);

  const handleLanguageChange = (newLang: SupportedLanguage) => {
    invalidateActiveReview();
    setLanguage(newLang);
    setErrorMessage(null);
    // Suggest sample for the new language
    if (SAMPLE_CODES[newLang] && SAMPLE_CODES[newLang].length > 0) {
      setCode(SAMPLE_CODES[newLang][0].code);
      setStdinInput(SAMPLE_CODES[newLang][0].stdin ?? "");
    }
  };

  const handleLoadSample = (sample: SampleCode) => {
    invalidateActiveReview();
    setCode(sample.code);
    setStdinInput(sample.stdin ?? "");
    setErrorMessage(null);
  };

  const handleClear = () => {
    invalidateActiveReview();
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
      const { result } = await executeRuntime({
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
      setIsRunning(false);
    }
  };

  const handleCancelReview = () => {
    invalidateActiveReview();
  };

  const handleSubmitReview = async () => {
    if (isSubmitting) return;
    const trimmed = code.trim();
    if (!trimmed) {
      setErrorMessage("Please enter some code to submit for review.");
      return;
    }
    if (trimmed.length < 2) {
      setErrorMessage("Please enter at least 2 characters of code before submitting for review.");
      return;
    }
    if (trimmed.length > 50000) {
      setErrorMessage("Code exceeds the 50,000-character limit for AI code review.");
      return;
    }

    reviewRequestIdRef.current += 1;
    const requestId = reviewRequestIdRef.current;

    if (reviewAbortRef.current) {
      reviewAbortRef.current.abort();
    }
    const controller = new AbortController();
    reviewAbortRef.current = controller;

    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      const response: CodeReviewResponse = await submitCodeReview(
        {
          code: trimmed,
          language,
        },
        { signal: controller.signal }
      );

      if (!isMountedRef.current || requestId !== reviewRequestIdRef.current) {
        return;
      }

      setReviewResult(response.review);
      setActiveReviewId(response.id);
      setActiveTab("overview");
      // Refresh history
      loadHistory();
    } catch (err: unknown) {
      if (isAbortError(err)) {
        return;
      }
      if (isMountedRef.current && requestId === reviewRequestIdRef.current) {
        const msg = err instanceof Error ? err.message : "Failed to review code. Please try again.";
        setErrorMessage(msg);
      }
    } finally {
      if (reviewAbortRef.current === controller) {
        reviewAbortRef.current = null;
      }
      if (isMountedRef.current && requestId === reviewRequestIdRef.current) {
        setIsSubmitting(false);
      }
    }
  };

  const handleSelectHistoryItem = async (item: CodeReviewHistoryItem) => {
    invalidateActiveReview();
    detailRequestIdRef.current += 1;
    const requestId = detailRequestIdRef.current;

    if (detailAbortRef.current) {
      detailAbortRef.current.abort();
    }
    const controller = new AbortController();
    detailAbortRef.current = controller;

    setIsLoadingDetail(true);
    setHistoryActionError(null);

    try {
      const detail = await fetchCodeReviewDetail(item.id, { signal: controller.signal });
      if (!isMountedRef.current || requestId !== detailRequestIdRef.current) {
        return;
      }
      setReviewResult(detail.review);
      setActiveReviewId(detail.id);
      setCode(detail.submitted_code);
      if (isSupportedLanguage(detail.language)) {
        setLanguage(detail.language);
      }
      setErrorMessage(null);
      setShowHistoryDrawer(false);
      setActiveTab("overview");
    } catch (err: unknown) {
      if (isAbortError(err)) {
        return;
      }
      if (isMountedRef.current && requestId === detailRequestIdRef.current) {
        const msg = err instanceof Error ? err.message : "Failed to load review details.";
        setHistoryActionError(msg);
      }
    } finally {
      if (detailAbortRef.current === controller) {
        detailAbortRef.current = null;
      }
      if (isMountedRef.current && requestId === detailRequestIdRef.current) {
        setIsLoadingDetail(false);
      }
    }
  };

  const handleDeleteHistoryItem = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (deletingIds.has(id)) return;

    deletedIdsRef.current.add(id);
    setDeletingIds((prev) => new Set(prev).add(id));
    setHistoryActionError(null);

    try {
      await deleteCodeReview(id);
      if (!isMountedRef.current) {
        return;
      }
      setHistory((prev) => prev.filter((item) => item.id !== id));
      if (activeReviewId === id) {
        setReviewResult(null);
        setActiveReviewId(null);
      }
    } catch (err: unknown) {
      deletedIdsRef.current.delete(id);
      if (isMountedRef.current) {
        const msg = err instanceof Error ? err.message : "Failed to delete review.";
        setHistoryActionError(msg);
      }
    } finally {
      if (isMountedRef.current) {
        setDeletingIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      }
    }
  };

  const handleCopyCorrected = () => {
    if (!reviewResult?.corrected_code) return;
    navigator.clipboard.writeText(reviewResult.corrected_code);
    setCopiedCode(true);
    if (copyTimeoutRef.current) {
      clearTimeout(copyTimeoutRef.current);
    }
    copyTimeoutRef.current = setTimeout(() => {
      copyTimeoutRef.current = null;
      if (isMountedRef.current) {
        setCopiedCode(false);
      }
    }, 2000);
  };

  const getAssessmentBadge = (assessment: string) => {
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

  const stdinByteLength = new TextEncoder().encode(stdinInput).length;

  return (
    <div className="flex-1 flex flex-col min-h-0 h-full lg:h-[calc(100vh-5rem)] lg:max-h-[calc(100vh-5rem)] lg:grid lg:grid-rows-reviewer-layout gap-3">
      {/* Top row: Editor (Left ~55%) & Results (Right ~45%) */}
      <div className="grid grid-cols-1 lg:grid-cols-reviewer-top gap-3.5 items-stretch min-h-0">
        {/* Left Column: Monaco Editor (~55%) */}
        <div className="min-w-0 flex flex-col h-full min-h-0">
          <div className="rounded-xl border border-[#272B36] bg-[#111319] overflow-hidden flex flex-col flex-1 h-full min-h-0">
            {/* Editor Toolbar */}
            <div className="border-b border-[#272B36] bg-[#0d0f17] px-3.5 py-2 flex flex-col gap-2 shrink-0">
              {/* Row 1: Samples & File Badge */}
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-[11px] font-medium text-zinc-500 shrink-0">
                    {language === "python" ? "Python" : language === "java" ? "Java" : "C++"} Samples:
                  </span>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {SAMPLE_CODES[language].map((sample, idx) => (
                      <button
                        key={idx}
                        onClick={() => handleLoadSample(sample)}
                        disabled={isRunning || isSubmitting}
                        title={sample.description}
                        className="text-[11px] px-2 py-0.5 rounded-md bg-[#181C25] hover:bg-[#202533] text-zinc-300 border border-white/[0.08] hover:text-white hover:border-white/[0.16] transition-colors cursor-pointer disabled:opacity-50"
                      >
                        {sample.title.split("(")[0].trim().split(" ").slice(0, 2).join(" ")}
                      </button>
                    ))}
                  </div>
                </div>

                <span className="text-xs font-mono text-zinc-400 px-2 py-0.5 rounded-md bg-[#080A10] border border-white/[0.08]">
                  {language === "python" ? "main.py" : language === "java" ? "Main.java" : "main.cpp"}
                </span>
              </div>

              {/* Row 2: Language Selector on Left & Action Buttons on Right */}
              <div className="flex items-center justify-between gap-2 pt-1 border-t border-white/[0.04]">
                {/* Language Selector Pills */}
                <div className="flex items-center gap-1 p-0.5 rounded-lg bg-[#080A10] border border-white/[0.08]">
                  {(["python", "java", "cpp"] as SupportedLanguage[]).map((lang) => (
                    <button
                      key={lang}
                      onClick={() => handleLanguageChange(lang)}
                      disabled={isRunning || isSubmitting}
                      className={`px-2 py-0.5 rounded-md text-xs font-medium transition-all cursor-pointer disabled:opacity-50 ${
                        language === lang
                          ? "bg-blue-600 text-white shadow-sm shadow-blue-900/40"
                          : "text-zinc-400 hover:text-zinc-200"
                      }`}
                    >
                      {lang === "python" ? "Python" : lang === "java" ? "Java" : "C++"}
                    </button>
                  ))}
                </div>

                {/* Action Buttons: Past Reviews, Clear, Run Code, Review Code */}
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => setShowHistoryDrawer(!showHistoryDrawer)}
                    className="flex items-center gap-1 px-2 py-1 rounded-lg bg-[#181C25] hover:bg-[#202533] border border-white/[0.08] hover:border-white/[0.16] text-xs text-zinc-300 hover:text-white transition-all shadow-sm cursor-pointer"
                    title="View past code reviews"
                  >
                    <History className="w-3.5 h-3.5 text-zinc-400" />
                    <span className="hidden sm:inline">Past Reviews</span>
                    {history.length > 0 && (
                      <span className="px-1.5 py-0.2 rounded-full bg-[#181C25] text-[#3B82F6] font-mono text-[10px] border border-[#3B82F6]/30">
                        {history.length}
                      </span>
                    )}
                  </button>

                  <button
                    onClick={handleClear}
                    disabled={!code || isSubmitting || isRunning}
                    className="flex items-center gap-1 px-2 py-1 rounded-lg bg-[#181C25] hover:bg-[#202533] border border-white/[0.08] hover:border-white/[0.16] text-xs text-zinc-400 hover:text-zinc-200 disabled:opacity-40 transition-colors cursor-pointer disabled:cursor-not-allowed"
                    title="Clear editor"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>Clear</span>
                  </button>

                  <button
                    onClick={handleRunCode}
                    disabled={isRunning || !code.trim()}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-xs disabled:opacity-50 transition-all shadow-md shadow-emerald-950/40 cursor-pointer disabled:cursor-not-allowed"
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
                    className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium text-xs disabled:opacity-50 transition-all shadow-md shadow-blue-900/40 cursor-pointer disabled:cursor-not-allowed"
                    title="Submit code for multi-agent review"
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

                  {isSubmitting && (
                    <button
                      onClick={handleCancelReview}
                      className="flex items-center gap-1 px-2 py-1 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/20 text-rose-300 font-medium text-xs transition-colors cursor-pointer"
                      title="Cancel in-progress code review"
                    >
                      <XCircle className="w-3.5 h-3.5 text-rose-400" />
                      <span>Cancel</span>
                    </button>
                  )}
                </div>
              </div>
            </div>

            {/* Monaco Editor Container */}
            <div className="flex-1 min-h-[160px] w-full relative bg-[#080A10]">
              <Editor
                height="100%"
                width="100%"
                language={MONACO_LANG_MAP[language]}
                theme="vs-dark"
                value={code}
                onChange={(val) => setCode(val || "")}
                onMount={handleEditorDidMount}
                options={buildMonacoOptions(editorSettings)}
              />
            </div>

            {/* Editor Footer Status */}
            <div className="px-3.5 py-1.5 bg-[#0d0f17] border-t border-white/[0.08] flex items-center justify-between text-[11px] text-zinc-500 shrink-0">
              <div className="flex items-center gap-3">
                <span className="font-mono text-zinc-400">{code.length} characters</span>
                <span>•</span>
                <span className="font-mono text-zinc-400">{code.split("\n").length} lines</span>
              </div>
              <div className="flex items-center gap-2 text-zinc-400">
                {isLocalPaired ? (
                  <span className="inline-flex items-center gap-1.5 text-[11px] text-emerald-400 font-medium">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    Local Docker Execution
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-[11px] text-zinc-400">
                    <ShieldCheck className="w-3.5 h-3.5 text-blue-400" />
                    Isolated Sandbox Execution
                  </span>
                )}
                <span>•</span>
                <span>Static Analysis</span>
              </div>
            </div>
          </div>

          {/* Error Banner if any */}
          {errorMessage && (
            <div className="mt-2 p-3 rounded-xl bg-rose-500/10 border border-rose-500/25 flex items-start gap-3 text-rose-300 text-xs shrink-0">
              <AlertCircle className="w-4 h-4 shrink-0 text-rose-400 mt-0.5" />
              <div>
                <p className="font-semibold">Review Error</p>
                <p className="mt-0.5 text-rose-300/90">{errorMessage}</p>
              </div>
            </div>
          )}
        </div>

        {/* Right Column: Review Results Panel (~45%) */}
        <div className="min-w-0 flex flex-col h-full min-h-0">
          {/* If no review yet and not submitting */}
          {!reviewResult && !isSubmitting && (
            <div className="rounded-xl border border-dashed border-white/[0.10] bg-[#111319]/40 p-6 flex flex-col items-center justify-center text-center space-y-3 h-full min-h-0 flex-1">
              <div className="w-9 h-9 rounded-xl bg-blue-500/10 border border-blue-500/20 text-[#3B82F6] flex items-center justify-center shadow-inner">
                <Sparkles className="w-4 h-4" />
              </div>
              <div className="space-y-0.5">
                <h3 className="text-sm font-semibold text-zinc-100">Ready to Analyze</h3>
                <p className="text-xs text-zinc-400">Your code insights will appear here.</p>
              </div>
              <div className="pt-1 flex flex-wrap items-center justify-center gap-2">
                <span className="inline-flex items-center px-2.5 py-0.5 rounded-md bg-[#181C25] border border-white/[0.06] text-[11px] text-zinc-400 font-medium">
                  Code Quality
                </span>
                <span className="inline-flex items-center px-2.5 py-0.5 rounded-md bg-[#181C25] border border-white/[0.06] text-[11px] text-zinc-400 font-medium">
                  Complexity Analysis
                </span>
                <span className="inline-flex items-center px-2.5 py-0.5 rounded-md bg-[#181C25] border border-white/[0.06] text-[11px] text-zinc-400 font-medium">
                  Edge Case Detection
                </span>
              </div>
            </div>
          )}

          {/* Loading State Spinner Card */}
          {isSubmitting && (
            <div className="rounded-xl border border-white/[0.08] bg-[#111319] p-6 flex flex-col items-center justify-center text-center space-y-3 h-full min-h-0 flex-1">
              <div className="relative">
                <div className="w-14 h-14 rounded-xl bg-[#3B82F6]/15 border border-[#3B82F6]/30 flex items-center justify-center text-[#3B82F6] animate-pulse">
                  <Layers className="w-7 h-7" />
                </div>
                <div className="absolute -inset-1 rounded-xl bg-[#3B82F6]/10 blur animate-spin" />
              </div>
              <div className="space-y-1">
                <h3 className="text-sm font-semibold text-white">Orchestrating Review Pipeline</h3>
                <p className="text-xs text-zinc-400 max-w-sm">
                  LangGraph executing nodes: Static AST check → Gemini Code Inspector → Boundary edge-cases → Big-O complexity derivation...
                </p>
              </div>
              <div className="flex items-center gap-2 text-[11px] text-[#3B82F6] font-mono">
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                <span>Processing source code</span>
              </div>
            </div>
          )}

          {/* Completed Review Panel */}
          {reviewResult && !isSubmitting && (
            <div className="rounded-xl border border-[#272B36] bg-[#111319] flex flex-col flex-1 overflow-hidden h-full min-h-0">
              {/* Header: Score & Overall Assessment */}
              <div className="px-4 py-2.5 border-b border-[#272B36] bg-[#0d0f17] flex items-center justify-between shrink-0">
                <div className="flex items-center gap-3">
                  {/* Quality Score Circle Badge */}
                  <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-[#181C25] border border-white/[0.10] font-mono font-bold text-base text-white">
                    <span className={reviewResult.quality_score >= 8 ? "text-emerald-400" : reviewResult.quality_score >= 5 ? "text-amber-400" : "text-rose-400"}>
                      {reviewResult.quality_score}
                    </span>
                    <span className="text-[10px] text-zinc-500 font-normal">/10</span>
                  </div>

                  <div>
                    {(() => {
                      const badge = getAssessmentBadge(reviewResult.overall_assessment);
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
                    <p className="text-[11px] text-zinc-400 mt-0.5 line-clamp-1">{reviewResult.summary}</p>
                  </div>
                </div>

                {/* Sub-Badges: Time & Space Quick Preview */}
                <div className="hidden sm:flex items-center gap-2">
                  <div className="px-2.5 py-0.5 rounded-lg bg-[#181C25] border border-white/[0.08] text-right">
                    <span className="text-[10px] text-zinc-500 block">Time</span>
                    <span className="text-xs font-mono font-semibold text-[#3B82F6]">{reviewResult.complexity.time_complexity}</span>
                  </div>
                  <div className="px-2.5 py-0.5 rounded-lg bg-[#181C25] border border-white/[0.08] text-right">
                    <span className="text-[10px] text-zinc-500 block">Space</span>
                    <span className="text-xs font-mono font-semibold text-emerald-400">{reviewResult.complexity.space_complexity}</span>
                  </div>
                </div>
              </div>

              {/* Navigation Tabs for Results */}
              <div className="flex items-center border-b border-white/[0.08] bg-[#080A10] px-3 overflow-x-auto">
                <button
                  onClick={() => setActiveTab("overview")}
                  className={`px-3 py-1.5 text-xs font-medium border-b-2 transition-colors cursor-pointer whitespace-nowrap ${
                    activeTab === "overview"
                      ? "border-[#3B82F6] text-[#3B82F6] font-semibold"
                      : "border-transparent text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  Overview &amp; Quality
                </button>
                <button
                  onClick={() => setActiveTab("issues")}
                  className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${
                    activeTab === "issues"
                      ? "border-[#3B82F6] text-[#3B82F6] font-semibold"
                      : "border-transparent text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  <span>Detected Issues</span>
                  <span className="px-1.5 py-0.2 rounded-full bg-[#181C25] text-zinc-300 font-mono text-[10px] border border-white/[0.08]">
                    {reviewResult.detected_issues.length}
                  </span>
                </button>
                <button
                  onClick={() => setActiveTab("complexity")}
                  className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors cursor-pointer whitespace-nowrap ${
                    activeTab === "complexity"
                      ? "border-[#3B82F6] text-[#3B82F6] font-semibold"
                      : "border-transparent text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  Estimated Complexity
                </button>
                <button
                  onClick={() => setActiveTab("edge_cases")}
                  className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors cursor-pointer whitespace-nowrap ${
                    activeTab === "edge_cases"
                      ? "border-[#3B82F6] text-[#3B82F6] font-semibold"
                      : "border-transparent text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  Edge Cases ({reviewResult.edge_cases.length})
                </button>
                {reviewResult.corrected_code && (
                  <button
                    onClick={() => setActiveTab("corrected")}
                    className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${
                      activeTab === "corrected"
                        ? "border-[#3B82F6] text-[#3B82F6] font-semibold"
                        : "border-transparent text-zinc-400 hover:text-zinc-200"
                    }`}
                  >
                    <Sparkles className="w-3 h-3 text-[#3B82F6]" />
                    <span>Corrected Code</span>
                  </button>
                )}
              </div>

              {/* Tab Contents: Scrollable */}
              <div className="flex-1 min-h-0 overflow-y-auto p-5 space-y-4">
                {/* 1. OVERVIEW TAB */}
                {activeTab === "overview" && (
                  <div className="space-y-4">
                    {/* Executive Summary */}
                    <div className="p-4 rounded-xl bg-[#181C25]/80 border border-white/[0.08] space-y-2">
                      <div className="flex items-center gap-2 text-xs font-semibold text-zinc-300">
                        <Info className="w-4 h-4 text-[#3B82F6]" />
                        <span>Executive Summary</span>
                      </div>
                      <p className="text-xs text-zinc-300 leading-relaxed">{reviewResult.summary}</p>
                    </div>

                    {/* Static Verification Note */}
                    {reviewResult.static_analysis_notes && (
                      <div className="p-3.5 rounded-xl bg-[#181C25]/50 border border-white/[0.08] flex items-start gap-2.5 text-xs text-zinc-400">
                        <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                        <div>
                          <span className="font-semibold text-zinc-300">Static Code Inspection:</span>{" "}
                          <span>{reviewResult.static_analysis_notes}</span>
                        </div>
                      </div>
                    )}

                    {/* Improvement Suggestions */}
                    {reviewResult.improvement_suggestions.length > 0 && (
                      <div className="space-y-2">
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-[11px] text-zinc-400">
                          Recommended Improvements
                        </h4>
                        <div className="space-y-1.5">
                          {reviewResult.improvement_suggestions.map((sug, i) => (
                            <div key={i} className="flex items-start gap-2.5 p-2.5 rounded-lg bg-[#181C25]/60 border border-white/[0.08] text-xs text-zinc-300">
                              <ChevronRight className="w-3.5 h-3.5 text-[#3B82F6] shrink-0 mt-0.5" />
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
                      <div className="p-8 text-center text-zinc-400 text-xs">
                        <CheckCircle2 className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
                        <p className="text-white font-medium">No major bugs detected!</p>
                        <p className="text-zinc-500 mt-1">Code conforms to standard algorithmic safety guidelines.</p>
                      </div>
                    ) : (
                      reviewResult.detected_issues.map((issue, idx) => (
                        <div
                          key={idx}
                          className="p-3.5 rounded-xl bg-[#181C25]/80 border border-white/[0.08] space-y-2"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${getSeverityPill(issue.severity)}`}>
                                {issue.severity}
                              </span>
                              <span className="px-2 py-0.5 rounded bg-[#080A10] text-zinc-400 text-[10px] font-mono border border-white/[0.06]">
                                {issue.type}
                              </span>
                            </div>
                            {issue.line_number && (
                              <span className="text-[11px] font-mono text-zinc-400">
                                Line {issue.line_number}
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-zinc-200 font-medium">{issue.message}</p>
                          {issue.suggestion && (
                            <div className="p-2 rounded-lg bg-[#3B82F6]/10 border border-[#3B82F6]/20 text-xs text-[#93C5FD] flex items-start gap-2">
                              <Zap className="w-3.5 h-3.5 text-[#3B82F6] shrink-0 mt-0.5" />
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
                    <div className="p-4 rounded-xl bg-[#181C25]/80 border border-white/[0.08] space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-xs font-semibold text-[#93C5FD]">
                          <Clock className="w-4 h-4 text-[#3B82F6]" />
                          <span>Time Complexity</span>
                        </div>
                        <span className="px-2.5 py-0.5 rounded-lg bg-[#3B82F6]/10 border border-[#3B82F6]/30 font-mono font-bold text-sm text-[#93C5FD]">
                          {reviewResult.complexity.time_complexity}
                        </span>
                      </div>
                      <p className="text-xs text-zinc-300 leading-relaxed pl-6">
                        {reviewResult.complexity.time_reasoning}
                      </p>
                    </div>

                    {/* Space Complexity Card */}
                    <div className="p-4 rounded-xl bg-[#181C25]/80 border border-white/[0.08] space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-xs font-semibold text-emerald-300">
                          <Layers className="w-4 h-4 text-emerald-400" />
                          <span>Auxiliary Space Complexity</span>
                        </div>
                        <span className="px-2.5 py-0.5 rounded-lg bg-emerald-950/60 border border-emerald-800/60 font-mono font-bold text-sm text-emerald-300">
                          {reviewResult.complexity.space_complexity}
                        </span>
                      </div>
                      <p className="text-xs text-zinc-300 leading-relaxed pl-6">
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
                        className="p-3.5 rounded-xl bg-[#181C25]/80 border border-white/[0.08] space-y-1.5"
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
                        <p className="text-xs text-zinc-300">
                          <span className="text-zinc-500">Scenario:</span> {ec.scenario}
                        </p>
                        <p className="text-xs text-zinc-400">
                          <span className="text-zinc-500">Predicted Behavior:</span> {ec.behavior}
                        </p>
                      </div>
                    ))}
                  </div>
                )}

                {/* 5. CORRECTED CODE TAB */}
                {activeTab === "corrected" && reviewResult.corrected_code && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-zinc-400">Intent-preserving corrected refactoring:</span>
                      <button
                        onClick={handleCopyCorrected}
                        className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#181C25] hover:bg-[#202533] text-xs text-zinc-200 border border-white/[0.08] transition-colors cursor-pointer"
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

                    <div className="rounded-xl bg-[#080A10] border border-white/[0.08] p-3 font-mono text-xs text-zinc-200 overflow-x-auto">
                      <pre className="leading-relaxed">{reviewResult.corrected_code}</pre>
                    </div>

                    {reviewResult.explanation_of_changes && (
                      <div className="p-3.5 rounded-xl bg-[#181C25]/80 border border-white/[0.08] text-xs text-zinc-300 space-y-1">
                        <span className="font-semibold text-white">Explanation of Changes:</span>
                        <p className="leading-relaxed text-zinc-300">{reviewResult.explanation_of_changes}</p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Bottom row: Standard Input (~30%) & Execution Console (~70%) */}
      <div className="grid grid-cols-1 lg:grid-cols-reviewer-bottom gap-3.5 items-stretch min-h-0">
        {/* Standard Input (stdin) Panel (~30%) */}
        <div className="min-w-0 flex flex-col h-full min-h-0">
          <div className="rounded-xl border border-[#272B36] bg-[#111319] overflow-hidden flex flex-col h-full min-h-0 flex-1">
            <div className="px-3.5 py-2 border-b border-[#272B36] bg-[#0d0f17] flex items-center justify-between gap-2 shrink-0">
              <div className="flex items-center gap-2">
                <FileCode className="w-4 h-4 text-[#3B82F6]" />
                <h2 className="text-xs font-semibold text-white">Standard Input (stdin)</h2>
              </div>
              {stdinInput.length > 0 && (
                <button
                  onClick={() => setStdinInput("")}
                  disabled={isRunning}
                  className="text-[11px] text-zinc-400 hover:text-zinc-200 disabled:opacity-40 transition-colors cursor-pointer"
                >
                  Clear input
                </button>
              )}
            </div>

            <div className="p-2.5 flex-1 min-h-0 flex flex-col">
              <textarea
                value={stdinInput}
                onChange={(e) => setStdinInput(e.target.value)}
                disabled={isRunning}
                placeholder="Optional program input passed via stdin..."
                rows={4}
                aria-label="Standard input"
                className="w-full flex-1 h-full min-h-0 rounded-lg bg-[#080A10] border border-white/[0.08] focus:border-[#3B82F6] focus:outline-none focus:ring-1 focus:ring-[#3B82F6]/50 p-2.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 resize-none disabled:opacity-60"
              />
            </div>

            <div className="px-3.5 py-1.5 bg-[#0d0f17] border-t border-white/[0.08] flex items-center justify-between text-[11px] text-zinc-500 shrink-0">
              <span className={`font-mono ${stdinByteLength > 65536 ? "text-rose-400" : "text-zinc-400"}`}>
                {stdinByteLength.toLocaleString()} / 65,536 bytes
              </span>
              <span>Passed separately from source</span>
            </div>
          </div>
        </div>

        {/* Execution Console Output Panel (~70%) */}
        <div className="min-w-0 flex flex-col h-full min-h-0">
          <ExecutionConsole
            language={language}
            isRunning={isRunning}
            executionResult={executionResult}
            executionError={executionError}
            onClearConsole={handleClearConsole}
          />
        </div>
      </div>

      {/* Slide-out Review History Drawer */}
      {showHistoryDrawer && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Past Code Reviews"
          className="fixed inset-0 z-50 flex justify-end bg-black/70 backdrop-blur-sm animate-in fade-in"
        >
          <div className="w-full max-w-md bg-[#111319] border-l border-white/[0.12] h-full p-6 flex flex-col justify-between shadow-2xl">
            <div className="space-y-4">
              <div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
                <div className="flex items-center gap-2">
                  <History className="w-4 h-4 text-[#3B82F6]" />
                  <h3 className="text-sm font-bold text-white">Review History</h3>
                </div>
                <button
                  onClick={() => setShowHistoryDrawer(false)}
                  aria-label="Close past reviews drawer"
                  className="p-1 rounded-lg text-zinc-400 hover:text-white hover:bg-white/[0.06] transition-colors cursor-pointer"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {historyActionError && (
                <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 flex items-start gap-2 text-xs text-rose-300">
                  <AlertCircle className="w-4 h-4 shrink-0 text-rose-400 mt-0.5" />
                  <span>{historyActionError}</span>
                </div>
              )}

              {isLoadingHistory ? (
                <div className="py-12 text-center text-zinc-400 text-xs flex items-center justify-center gap-2">
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Loading past reviews...</span>
                </div>
              ) : historyError ? (
                <div className="py-10 px-4 text-center space-y-3 rounded-xl bg-rose-500/10 border border-rose-500/20">
                  <AlertCircle className="w-5 h-5 text-rose-400 mx-auto" />
                  <p className="text-xs text-rose-200">{historyError}</p>
                  <button
                    onClick={loadHistory}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#181C25] hover:bg-[#202533] text-xs text-zinc-200 border border-white/[0.08] transition-colors cursor-pointer"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                    <span>Retry</span>
                  </button>
                </div>
              ) : history.length === 0 ? (
                <div className="py-12 text-center text-zinc-400 text-xs">
                  <p>No code reviews found in your account.</p>
                  <p className="text-zinc-500 mt-1">Submit your first code review above!</p>
                </div>
              ) : (
                <div className="space-y-2.5 overflow-y-auto max-h-[75vh] pr-1">
                  {history.map((item) => {
                    const isDeleting = deletingIds.has(item.id);
                    return (
                      <div
                        key={item.id}
                        onClick={() => {
                          if (!isDeleting) handleSelectHistoryItem(item);
                        }}
                        className={`p-3 rounded-xl border transition-all ${
                          isDeleting || isLoadingDetail ? "opacity-70" : "cursor-pointer"
                        } ${
                          activeReviewId === item.id
                            ? "bg-[#3B82F6]/10 border-[#3B82F6]/50"
                            : "bg-[#181C25]/80 border-white/[0.08] hover:border-[#3B82F6]/40"
                        }`}
                      >
                        <div className="flex items-center justify-between text-xs mb-1.5">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-[10px] font-bold px-1.5 py-0.5 rounded bg-[#080A10] text-zinc-300 uppercase border border-white/[0.08]">
                              {item.language}
                            </span>
                            <span className="text-[11px] font-semibold text-white">
                              Score: {item.quality_score}/10
                            </span>
                          </div>
                          <button
                            onClick={(e) => handleDeleteHistoryItem(e, item.id)}
                            disabled={isDeleting}
                            className="text-zinc-500 hover:text-rose-400 disabled:opacity-40 p-1 transition-colors cursor-pointer disabled:cursor-not-allowed"
                            title={isDeleting ? "Deleting..." : "Delete review"}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>

                        <p className="text-xs text-zinc-300 font-mono truncate">{item.code_snippet}</p>
                        <p className="text-[11px] text-zinc-400 mt-1 line-clamp-1">{item.summary}</p>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="pt-4 border-t border-white/[0.08]">
              <button
                onClick={() => setShowHistoryDrawer(false)}
                className="w-full py-2 rounded-xl bg-[#181C25] hover:bg-[#202533] border border-white/[0.08] text-xs text-zinc-300 hover:text-white transition-colors cursor-pointer"
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


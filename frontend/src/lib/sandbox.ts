import type { ComponentType } from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Clock,
  XCircle,
} from "lucide-react";
import { ExecutionResult, SandboxApiError } from "@/services/api";

export type SupportedLanguage = "python" | "java" | "cpp";

export interface SandboxSampleProgram {
  title: string;
  description: string;
  code: string;
  stdin?: string;
}

export interface ExecutionErrorState {
  title: string;
  message: string;
  statusCode?: number;
}

export const MONACO_LANG_MAP: Record<SupportedLanguage, string> = {
  python: "python",
  java: "java",
  cpp: "cpp",
};

export const LANGUAGE_LABELS: Record<SupportedLanguage, string> = {
  python: "Python",
  java: "Java",
  cpp: "C++",
};

export const DEFAULT_MONACO_OPTIONS = {
  fontSize: 13,
  fontFamily: "'Fira Code', 'JetBrains Mono', Consolas, monospace",
  minimap: { enabled: false },
  scrollBeyondLastLine: false,
  lineNumbers: "on" as const,
  roundedSelection: false,
  automaticLayout: true,
  padding: { top: 12, bottom: 12 },
  tabSize: 4,
  renderLineHighlight: "all" as const,
  overviewRulerLanes: 0,
  hideCursorInOverviewRuler: true,
};

export const SANDBOX_SAMPLE_PROGRAMS: Record<SupportedLanguage, SandboxSampleProgram[]> = {
  python: [
    {
      title: "Hello & Stdin",
      description: "Reads optional name from stdin and prints greeting",
      stdin: "CodePilot",
      code: `import sys

name = sys.stdin.read().strip() or "Developer"
print(f"Hello, {name}! Welcome to the CodePilot Python sandbox.")
`,
    },
    {
      title: "Binary Search",
      description: "Runs binary search on a sorted list",
      code: `def binary_search(arr, target):
    left, right = 0, len(arr) - 1
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        if arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1

nums = [2, 5, 8, 12, 16, 23, 38, 56, 72, 91]
for target in [23, 42]:
    idx = binary_search(nums, target)
    print(f"Target {target} -> index {idx}")
`,
    },
    {
      title: "Fibonacci DP",
      description: "Computes Fibonacci numbers using O(n) dynamic programming",
      code: `def fibonacci(n: int) -> list[int]:
    if n <= 0:
        return []
    seq = [0, 1]
    for _ in range(2, n):
        seq.append(seq[-1] + seq[-2])
    return seq[:n]

print("First 10 Fibonacci numbers:", fibonacci(10))
`,
    },
  ],
  java: [
    {
      title: "Hello & Stdin",
      description: "Reads optional input line from stdin in Java",
      stdin: "CodePilot",
      code: `import java.util.Scanner;

public class Main {
    public static void main(String[] args) {
        Scanner scanner = new Scanner(System.in);
        String name = scanner.hasNextLine() ? scanner.nextLine().trim() : "";
        if (name.isEmpty()) {
            name = "Developer";
        }
        System.out.println("Hello, " + name + "! Welcome to the CodePilot Java sandbox.");
    }
}
`,
    },
    {
      title: "Two Sum",
      description: "Finds indices of two numbers adding up to a target",
      code: `import java.util.HashMap;
import java.util.Map;

public class Main {
    public static int[] twoSum(int[] nums, int target) {
        Map<Integer, Integer> seen = new HashMap<>();
        for (int i = 0; i < nums.length; i++) {
            int need = target - nums[i];
            if (seen.containsKey(need)) {
                return new int[] { seen.get(need), i };
            }
            seen.put(nums[i], i);
        }
        return new int[] {};
    }

    public static void main(String[] args) {
        int[] result = twoSum(new int[] { 2, 7, 11, 15 }, 9);
        System.out.println("Indices: [" + result[0] + ", " + result[1] + "]");
    }
}
`,
    },
  ],
  cpp: [
    {
      title: "Hello & Stdin",
      description: "Reads optional input line from stdin in C++",
      stdin: "CodePilot",
      code: `#include <iostream>
#include <string>

int main() {
    std::string name;
    std::getline(std::cin, name);
    if (name.empty()) {
        name = "Developer";
    }
    std::cout << "Hello, " << name << "! Welcome to the CodePilot C++ sandbox." << std::endl;
    return 0;
}
`,
    },
    {
      title: "Vector Sort & Sum",
      description: "Sorts a vector and computes prefix sum using STL",
      code: `#include <algorithm>
#include <iostream>
#include <numeric>
#include <vector>

int main() {
    std::vector<int> nums = {38, 12, 72, 5, 23, 16};
    std::sort(nums.begin(), nums.end());

    std::cout << "Sorted: ";
    for (int n : nums) {
        std::cout << n << " ";
    }
    std::cout << std::endl;

    int total = std::accumulate(nums.begin(), nums.end(), 0);
    std::cout << "Sum: " << total << std::endl;
    return 0;
}
`,
    },
  ],
};

export function formatDurationMs(ms: number): string {
  if (ms >= 1000) {
    return `${(ms / 1000).toFixed(2)} s`;
  }
  return `${Math.round(ms * 10) / 10} ms`;
}

export interface ExecutionStatusMeta {
  label: string;
  classes: string;
  icon: ComponentType<{ className?: string }>;
  notice: string | null;
}

export function getExecutionStatusMeta(res: ExecutionResult): ExecutionStatusMeta {
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
}

export function mapSandboxApiError(err: unknown): {
  error: ExecutionErrorState;
  executionResult?: ExecutionResult;
} {
  if (err instanceof SandboxApiError) {
    const titleMap: Record<number, string> = {
      401: "Authentication Required",
      422: "Validation Error",
      429: "Rate or Concurrency Limit Reached",
      503: "Sandbox Unavailable",
    };
    return {
      error: {
        title: titleMap[err.statusCode] || "Execution Request Failed",
        message: err.message,
        statusCode: err.statusCode,
      },
      executionResult: err.executionResult,
    };
  }

  const msg = err instanceof Error ? err.message : "Failed to execute code. Please try again.";
  return {
    error: {
      title: "Execution Request Failed",
      message: msg,
    },
  };
}


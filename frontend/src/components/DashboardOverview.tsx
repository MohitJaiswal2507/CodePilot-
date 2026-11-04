"use client";

import React, { useState } from "react";
import { 
  BookOpen, 
  Code2, 
  Terminal, 
  CheckCircle2, 
  ArrowRight, 
  Layers, 
  Sparkles,
  Server,
  Send,
  ShieldAlert
} from "lucide-react";

export function DashboardOverview({ onNavigate }: { onNavigate: (tab: string) => void }) {
  const [tutorQuery, setTutorQuery] = useState("");
  const [reviewCode] = useState(
    `def binary_search(arr, target):\n    left, right = 0, len(arr) - 1\n    while left <= right:\n        mid = (left + right) // 2\n        if arr[mid] == target:\n            return mid\n        elif arr[mid] < target:\n            left = mid + 1\n        else:\n            right = mid - 1\n    return -1`
  );

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12">
      {/* Welcome Banner */}
      <div className="relative overflow-hidden rounded-xl border border-slate-800 bg-gradient-to-r from-slate-900/90 via-[#0d1322] to-slate-900/90 p-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1.5">
            <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 text-xs font-medium">
              <Sparkles className="w-3 h-3" /> Intelligent Developer Copilot
            </div>
            <h2 className="text-xl font-bold text-white tracking-tight">
              CodePilot AI — Learning & Automated Code Review
            </h2>
            <p className="text-xs text-slate-400 max-w-2xl leading-relaxed">
              Curriculum-grounded computer science learning, automated multi-language code review,
              and isolated test execution in a single unified platform.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => onNavigate("ai-tutor")}
              className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-sm transition-colors flex items-center gap-2"
            >
              <BookOpen className="w-3.5 h-3.5" />
              <span>Explore AI Tutor</span>
            </button>
            <button
              onClick={() => onNavigate("code-review")}
              className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-semibold transition-colors flex items-center gap-2"
            >
              <Code2 className="w-3.5 h-3.5" />
              <span>Review Code</span>
            </button>
          </div>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-4 rounded-xl border border-slate-800/80 bg-slate-900/40">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Backend Service</span>
            <div className="w-7 h-7 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
              <Server className="w-3.5 h-3.5" />
            </div>
          </div>
          <div className="mt-3">
            <p className="text-xl font-bold text-white">FastAPI Engine</p>
            <p className="text-[11px] text-emerald-400 mt-0.5 flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" /> Live & Responding
            </p>
          </div>
        </div>

        <div className="p-4 rounded-xl border border-slate-800/80 bg-slate-900/40">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Curriculum Grounding</span>
            <div className="w-7 h-7 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
              <BookOpen className="w-3.5 h-3.5" />
            </div>
          </div>
          <div className="mt-3">
            <p className="text-xl font-bold text-white">Syllabus Q&A</p>
            <p className="text-[11px] text-slate-400 mt-0.5">Strict citation verification</p>
          </div>
        </div>

        <div className="p-4 rounded-xl border border-slate-800/80 bg-slate-900/40">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Automated Review</span>
            <div className="w-7 h-7 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400">
              <Code2 className="w-3.5 h-3.5" />
            </div>
          </div>
          <div className="mt-3">
            <p className="text-xl font-bold text-white">Python, Java, C++</p>
            <p className="text-[11px] text-slate-400 mt-0.5">Complexity & bug detection</p>
          </div>
        </div>

        <div className="p-4 rounded-xl border border-slate-800/80 bg-slate-900/40">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Execution Sandbox</span>
            <div className="w-7 h-7 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
              <Terminal className="w-3.5 h-3.5" />
            </div>
          </div>
          <div className="mt-3">
            <p className="text-xl font-bold text-white">Secure Runtime</p>
            <p className="text-[11px] text-slate-400 mt-0.5">Isolated test runner</p>
          </div>
        </div>
      </div>

      {/* Main Grid: AI Tutor & Code Review Previews */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* AI Tutor Section */}
        <div className="rounded-xl border border-slate-800/80 bg-[#0d121f] p-5 flex flex-col justify-between">
          <div className="space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
              <div className="flex items-center gap-2.5">
                <div className="w-7 h-7 rounded bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
                  <BookOpen className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">AI Learning Tutor</h3>
                  <p className="text-[11px] text-slate-400">Curriculum-grounded syllabus Q&A</p>
                </div>
              </div>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-indigo-300 border border-slate-700">
                Syllabus Citations
              </span>
            </div>

            {/* Interaction Box */}
            <div className="space-y-3">
              <div className="p-3 rounded-lg bg-slate-900/80 border border-slate-800/80 text-xs space-y-1.5">
                <div className="flex items-center justify-between text-slate-400 text-[10px]">
                  <span className="font-semibold text-indigo-400">Sample Query</span>
                  <span>Course Material: Data Structures & Algorithms</span>
                </div>
                <p className="text-slate-300">
                  &ldquo;Explain the difference between an AVL Tree and a Red-Black Tree in terms of worst-case lookup vs insertion rotations.&rdquo;
                </p>
              </div>

              <div className="p-3.5 rounded-lg bg-indigo-950/20 border border-indigo-800/40 text-xs space-y-2">
                <div className="flex items-center gap-2 text-indigo-300 font-medium text-[11px]">
                  <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
                  <span>Grounding Standard:</span>
                </div>
                <p className="text-slate-400 text-[11px] leading-relaxed">
                  Every response includes exact textbook citations
                  <span className="text-indigo-300 font-mono text-[10px] ml-1">
                    [Doc: Trees_Unit3.pdf, Page: 42]
                  </span>
                  and contextual check questions to verify conceptual understanding.
                </p>
              </div>
            </div>
          </div>

          <div className="mt-5 pt-3 border-t border-slate-800/80">
            <div className="relative flex items-center">
              <input
                type="text"
                value={tutorQuery}
                onChange={(e) => setTutorQuery(e.target.value)}
                placeholder="Ask a computer science concept or algorithm question..."
                className="w-full bg-slate-900/60 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-300 placeholder-slate-500 focus:outline-none focus:border-indigo-500/50"
              />
              <button
                onClick={() => onNavigate("ai-tutor")}
                className="absolute right-1.5 p-1.5 rounded-md bg-indigo-600 hover:bg-indigo-500 text-white transition-colors"
                title="Send query to AI Tutor"
              >
                <Send className="w-3 h-3" />
              </button>
            </div>
          </div>
        </div>

        {/* Code Reviewer Section */}
        <div className="rounded-xl border border-slate-800/80 bg-[#0d121f] p-5 flex flex-col justify-between">
          <div className="space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
              <div className="flex items-center gap-2.5">
                <div className="w-7 h-7 rounded bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400">
                  <Code2 className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">AI Code Reviewer</h3>
                  <p className="text-[11px] text-slate-400">Multi-language static & asymptotic analysis</p>
                </div>
              </div>
              <div className="flex gap-1 text-[10px] font-mono">
                <span className="px-1.5 py-0.5 rounded bg-cyan-950/40 text-cyan-300 border border-cyan-800/40">Python</span>
                <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">Java</span>
                <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">C++</span>
              </div>
            </div>

            {/* Code Snippet Box */}
            <div className="rounded-lg bg-[#070b13] border border-slate-800/90 p-3 font-mono text-[11px] text-slate-300 space-y-1 overflow-x-auto">
              <div className="text-slate-400 text-[10px] pb-1 border-b border-slate-800 flex justify-between">
                <span>binary_search.py</span>
                <span className="text-emerald-400 font-mono">Target Complexity: O(log N)</span>
              </div>
              <pre className="pt-2 text-indigo-300/90 leading-relaxed font-mono">
                {reviewCode}
              </pre>
            </div>

            {/* Review Badges */}
            <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800/60 flex items-center justify-between text-xs">
              <div className="flex items-center gap-3">
                <span className="text-[11px] text-slate-400">Time:</span>
                <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono text-[10px]">
                  O(log N)
                </span>
                <span className="text-[11px] text-slate-400">Space:</span>
                <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono text-[10px]">
                  O(1)
                </span>
              </div>
              <span className="text-[10px] text-slate-400 font-mono">Asymptotic Proof Engine</span>
            </div>
          </div>

          <div className="mt-5 pt-3 border-t border-slate-800/80">
            <button
              onClick={() => onNavigate("code-review")}
              className="w-full py-2 rounded-lg bg-slate-800/60 hover:bg-slate-800 text-slate-300 text-xs font-medium transition-colors flex items-center justify-center gap-2 border border-slate-700/60"
            >
              <span>Open Code Reviewer</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Recent Activity & System Status */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Activity Timeline */}
        <div className="lg:col-span-2 rounded-xl border border-slate-800/80 bg-[#0d121f] p-5">
          <div className="flex items-center justify-between mb-4 pb-2 border-b border-slate-800/80">
            <h3 className="text-xs font-semibold text-white uppercase tracking-wider">
              Recent Platform Activity
            </h3>
            <span className="text-[10px] text-emerald-400 font-medium">All Systems Operational</span>
          </div>

          <div className="space-y-4">
            <div className="flex items-start gap-3">
              <div className="w-2 h-2 rounded-full bg-emerald-400 mt-1.5 shrink-0" />
              <div className="space-y-0.5">
                <p className="text-xs font-medium text-slate-200">
                  Core API Gateway Connected
                </p>
                <p className="text-[11px] text-slate-400">
                  FastAPI service synchronized with Next.js client with active CORS and health telemetry.
                </p>
                <span className="text-[10px] text-slate-400 font-mono">Active</span>
              </div>
            </div>

            <div className="flex items-start gap-3">
              <div className="w-2 h-2 rounded-full bg-indigo-400 mt-1.5 shrink-0" />
              <div className="space-y-0.5">
                <p className="text-xs font-medium text-slate-300">
                  Health Telemetry Verified
                </p>
                <p className="text-[11px] text-slate-400">
                  Real-time latency monitoring and service status ping operational.
                </p>
                <span className="text-[10px] text-slate-400 font-mono">Live</span>
              </div>
            </div>

            <div className="flex items-start gap-3">
              <div className="w-2 h-2 rounded-full bg-slate-600 mt-1.5 shrink-0" />
              <div className="space-y-0.5">
                <p className="text-xs font-medium text-slate-300">
                  Curriculum & Code Analysis Services
                </p>
                <p className="text-[11px] text-slate-400">
                  Interactive learning assistant and multi-language review pipelines configured.
                </p>
                <span className="text-[10px] text-slate-400 font-mono">Configured</span>
              </div>
            </div>
          </div>
        </div>

        {/* System Diagnostics */}
        <div className="rounded-xl border border-slate-800/80 bg-[#0d121f] p-5">
          <div className="flex items-center justify-between mb-4 pb-2 border-b border-slate-800/80">
            <h3 className="text-xs font-semibold text-white uppercase tracking-wider">
              System Status
            </h3>
            <Layers className="w-3.5 h-3.5 text-slate-400" />
          </div>

          <div className="space-y-3 text-xs">
            <div className="flex justify-between py-1.5 border-b border-slate-800/60">
              <span className="text-slate-400">Web Client</span>
              <span className="font-mono text-slate-200">Next.js 15 / React 19</span>
            </div>
            <div className="flex justify-between py-1.5 border-b border-slate-800/60">
              <span className="text-slate-400">API Server</span>
              <span className="font-mono text-slate-200">FastAPI / Python 3.13</span>
            </div>
            <div className="flex justify-between py-1.5 border-b border-slate-800/60">
              <span className="text-slate-400">Design System</span>
              <span className="font-mono text-slate-200">Tailwind CSS</span>
            </div>
            <div className="flex justify-between py-1.5 border-b border-slate-800/60">
              <span className="text-slate-400">Data Validation</span>
              <span className="font-mono text-slate-200">Pydantic v2</span>
            </div>
            <div className="flex justify-between py-1.5">
              <span className="text-slate-400">CORS Policy</span>
              <span className="font-mono text-emerald-400">Active (localhost:3000)</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

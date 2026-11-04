"use client";

import React, { useState } from "react";
import { Sidebar } from "@/components/Sidebar";
import { Header } from "@/components/Header";
import { DashboardOverview } from "@/components/DashboardOverview";
import { BookOpen, Code2, Terminal, ShieldCheck, Settings as SettingsIcon } from "lucide-react";

export default function Home() {
  const [currentTab, setCurrentTab] = useState<string>("dashboard");

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#090d16]">
      {/* Sidebar Navigation */}
      <Sidebar currentTab={currentTab} onSelectTab={setCurrentTab} />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <Header currentTab={currentTab} />

        <main className="flex-1 overflow-y-auto p-8">
          {currentTab === "dashboard" && (
            <DashboardOverview onNavigate={(tab) => setCurrentTab(tab)} />
          )}

          {currentTab === "ai-tutor" && (
            <div className="max-w-4xl mx-auto rounded-xl border border-slate-800 bg-[#0d121f] p-8 text-center space-y-4">
              <div className="w-12 h-12 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 flex items-center justify-center mx-auto">
                <BookOpen className="w-6 h-6" />
              </div>
              <h2 className="text-lg font-bold text-white">AI Learning Tutor</h2>
              <p className="text-xs text-slate-400 max-w-md mx-auto leading-relaxed">
                Curriculum-grounded question answering and concept explanations backed by syllabus citations and zero-hallucination guardrails.
              </p>
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-slate-800 text-[11px] text-slate-300 border border-slate-700">
                Coming Soon
              </div>
            </div>
          )}

          {currentTab === "code-review" && (
            <div className="max-w-4xl mx-auto rounded-xl border border-slate-800 bg-[#0d121f] p-8 text-center space-y-4">
              <div className="w-12 h-12 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 flex items-center justify-center mx-auto">
                <Code2 className="w-6 h-6" />
              </div>
              <h2 className="text-lg font-bold text-white">AI Code Reviewer</h2>
              <p className="text-xs text-slate-400 max-w-md mx-auto leading-relaxed">
                Multi-dimensional static and algorithmic review with Big-O time and space complexity derivation and refactoring diffs.
              </p>
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-slate-800 text-[11px] text-slate-300 border border-slate-700">
                Coming Soon
              </div>
            </div>
          )}

          {currentTab === "sandbox" && (
            <div className="max-w-4xl mx-auto rounded-xl border border-slate-800 bg-[#0d121f] p-8 text-center space-y-4">
              <div className="w-12 h-12 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400 flex items-center justify-center mx-auto">
                <Terminal className="w-6 h-6" />
              </div>
              <h2 className="text-lg font-bold text-white">Code Execution Sandbox</h2>
              <p className="text-xs text-slate-400 max-w-md mx-auto leading-relaxed">
                Secure containerized code runner with memory limits, CPU quotas, and zero network access for safe compilation and test execution.
              </p>
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-slate-800 text-[11px] text-slate-300 border border-slate-700">
                Coming Soon
              </div>
            </div>
          )}

          {currentTab === "guardrails" && (
            <div className="max-w-4xl mx-auto rounded-xl border border-slate-800 bg-[#0d121f] p-8 text-center space-y-4">
              <div className="w-12 h-12 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center mx-auto">
                <ShieldCheck className="w-6 h-6" />
              </div>
              <h2 className="text-lg font-bold text-white">AI Safety & Guardrails</h2>
              <p className="text-xs text-slate-400 max-w-md mx-auto leading-relaxed">
                Input sanitization, prompt injection resistance, strict schema verification, and execution quotas.
              </p>
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-slate-800 text-[11px] text-slate-300 border border-slate-700">
                Active Protection Policies
              </div>
            </div>
          )}

          {currentTab === "settings" && (
            <div className="max-w-4xl mx-auto rounded-xl border border-slate-800 bg-[#0d121f] p-8 text-center space-y-4">
              <div className="w-12 h-12 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400 flex items-center justify-center mx-auto">
                <SettingsIcon className="w-6 h-6" />
              </div>
              <h2 className="text-lg font-bold text-white">System Settings</h2>
              <p className="text-xs text-slate-400 max-w-md mx-auto leading-relaxed">
                Environment variables, API endpoints, and platform configurations.
              </p>
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-slate-800 text-[11px] text-slate-300 border border-slate-700">
                Environment Configured
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

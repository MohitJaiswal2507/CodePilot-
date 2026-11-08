"use client";

import React, { useState, useEffect } from "react";
import { Sidebar } from "@/components/Sidebar";
import { Header } from "@/components/Header";
import { DashboardOverview } from "@/components/DashboardOverview";
import { AITutor } from "@/components/AITutor";
import { CodeReviewer } from "@/components/CodeReviewer";
import { Code2, Terminal, ShieldCheck, Settings as SettingsIcon } from "lucide-react";
import { authClient } from "@/lib/auth/client";
import { setApiAuthToken } from "@/services/api";

export default function Home() {
  const [currentTab, setCurrentTab] = useState<string>("dashboard");

  useEffect(() => {
    if (typeof window !== "undefined") {
      const savedTab = localStorage.getItem("codepilot_active_tab");
      if (savedTab) {
        setCurrentTab(savedTab);
      }
    }

    // Prime the API auth token from current active session
    async function syncSessionToken() {
      try {
        const sessionRes = await authClient.getSession();
        if (sessionRes?.data?.session?.token) {
          setApiAuthToken(sessionRes.data.session.token);
        }
      } catch (err) {
        // Fallback or dev mode handling
      }
    }
    syncSessionToken();
  }, []);

  const handleSelectTab = (tab: string) => {
    setCurrentTab(tab);
    if (typeof window !== "undefined") {
      localStorage.setItem("codepilot_active_tab", tab);
    }
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#090d16]">
      {/* Sidebar Navigation */}
      <Sidebar currentTab={currentTab} onSelectTab={handleSelectTab} />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <Header currentTab={currentTab} />

        <main className="flex-1 overflow-y-auto p-8">
          {currentTab === "dashboard" && (
            <DashboardOverview onNavigate={handleSelectTab} />
          )}

          {currentTab === "ai-tutor" && (
            <AITutor />
          )}

          {currentTab === "code-review" && (
            <CodeReviewer />
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

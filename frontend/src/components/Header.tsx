"use client";

import React from "react";
import { Terminal, Shield, BookMarked, Github } from "lucide-react";
import { HealthBadge } from "./HealthBadge";

interface HeaderProps {
  currentTab: string;
}

export function Header({ currentTab }: HeaderProps) {
  const titles: Record<string, { title: string; subtitle: string }> = {
    dashboard: {
      title: "System Overview",
      subtitle: "CodePilot AI Full-Stack Platform Status & Diagnostics",
    },
    "ai-tutor": {
      title: "AI Learning Tutor",
      subtitle: "Curriculum-grounded question answering and concept explanations",
    },
    "code-review": {
      title: "AI Code Reviewer",
      subtitle: "Multi-language static, algorithmic, and complexity analysis",
    },
    sandbox: {
      title: "Isolated Code Sandbox",
      subtitle: "Secure containerized code execution environment",
    },
    guardrails: {
      title: "Safety & Guardrails",
      subtitle: "Prompt injection resistance and policy enforcement",
    },
    settings: {
      title: "Settings & Configuration",
      subtitle: "API keys, model parameters, and environment settings",
    },
  };

  const current = titles[currentTab] || titles.dashboard;

  return (
    <header className="h-16 border-b border-slate-800/80 bg-[#0b0f19]/80 backdrop-blur-sm px-8 flex items-center justify-between shrink-0">
      <div>
        <h1 className="text-sm font-semibold text-white tracking-tight">{current.title}</h1>
        <p className="text-[11px] text-slate-400">{current.subtitle}</p>
      </div>

      <div className="flex items-center gap-4">
        {/* Backend Health Status Badge */}
        <HealthBadge />

        <div className="h-4 w-px bg-slate-800" />

        {/* GitHub Link */}
        <a
          href="https://github.com/MohitJaiswal2507/CodePilot-"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white px-2.5 py-1.5 rounded-lg border border-slate-800 hover:border-slate-700 bg-slate-900/40 transition-colors"
        >
          <Github className="w-3.5 h-3.5" />
          <span>Repository</span>
        </a>
      </div>
    </header>
  );
}


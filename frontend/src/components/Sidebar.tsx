"use client";

import React from "react";
import { 
  LayoutDashboard, 
  BookOpen, 
  Code2, 
  Terminal, 
  ShieldCheck, 
  Cpu, 
  Settings,
  Sparkles
} from "lucide-react";

interface SidebarProps {
  currentTab: string;
  onSelectTab: (tab: string) => void;
}

export function Sidebar({ currentTab, onSelectTab }: SidebarProps) {
  const navItems = [
    { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    { id: "ai-tutor", label: "AI Learning Tutor", icon: BookOpen },
    { id: "code-review", label: "Code Reviewer", icon: Code2 },
    { id: "sandbox", label: "Code Execution", icon: Terminal },
    { id: "guardrails", label: "AI Guardrails", icon: ShieldCheck },
    { id: "settings", label: "Settings", icon: Settings },
  ];

  return (
    <aside className="w-64 bg-[#0d121f] border-r border-slate-800/80 flex flex-col justify-between shrink-0 select-none">
      {/* Brand Header */}
      <div>
        <div className="h-16 flex items-center px-6 border-b border-slate-800/80 gap-3">
          <div className="w-9 h-9 rounded-lg bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
            <Cpu className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-semibold tracking-tight text-white text-base">CodePilot</span>
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                AI
              </span>
            </div>
            <p className="text-[11px] text-slate-400">Learning & Review Copilot</p>
          </div>
        </div>

        {/* Navigation Items */}
        <div className="px-3 py-4 space-y-1">
          <p className="px-3 text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-2">
            Navigation
          </p>
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = currentTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => onSelectTab(item.id)}
                className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-xs font-medium transition-colors ${
                  isActive
                    ? "bg-indigo-600/15 text-indigo-300 border border-indigo-500/20"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/40"
                }`}
              >
                <div className="flex items-center gap-3">
                  <Icon className={`w-4 h-4 ${isActive ? "text-indigo-400" : "text-slate-400"}`} />
                  <span>{item.label}</span>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* User Profile Footer */}
      <div className="p-4 border-t border-slate-800/80 space-y-3">
        <div className="p-2.5 rounded-lg bg-slate-900/60 border border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-xs font-semibold text-slate-200">
              MJ
            </div>
            <div>
              <p className="text-xs font-medium text-slate-200">Mohit Jaiswal</p>
              <p className="text-[10px] text-slate-400">Developer Workspace</p>
            </div>
          </div>
          <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700/60">
            <Sparkles className="w-2.5 h-2.5 text-indigo-400" /> Pro
          </span>
        </div>
      </div>
    </aside>
  );
}

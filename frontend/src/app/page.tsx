"use client";

import React, { useState, useEffect, useCallback } from "react";
import { Sidebar } from "@/components/Sidebar";
import { Header } from "@/components/Header";
import { DashboardOverview } from "@/components/DashboardOverview";
import { AITutor } from "@/components/AITutor";
import { CodeReviewer } from "@/components/CodeReviewer";
import { CodeSandbox } from "@/components/CodeSandbox";
import { Settings } from "@/components/Settings";
import { authClient } from "@/lib/auth/client";
import { AppTab, isAppTab } from "@/lib/navigation";
import { setApiAuthToken } from "@/services/api";

const SIDEBAR_COLLAPSED_KEY = "codepilot_sidebar_collapsed";

const TAB_TITLES: Record<AppTab, string> = {
  dashboard: "Dashboard — CodePilot AI",
  "ai-tutor": "AI Tutor — CodePilot AI",
  "code-review": "Code Reviewer — CodePilot AI",
  sandbox: "Code Sandbox — CodePilot AI",
  settings: "Settings — CodePilot AI",
};

export default function Home() {
  const [currentTab, setCurrentTab] = useState<AppTab>("dashboard");
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState<boolean>(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const urlParams = new URLSearchParams(window.location.search);
      const queryTab = urlParams.get("tab");
      if (isAppTab(queryTab)) {
        setCurrentTab(queryTab);
      } else {
        const savedTab = localStorage.getItem("codepilot_active_tab");
        if (isAppTab(savedTab)) {
          setCurrentTab(savedTab);
        }
      }
      const savedCollapsed = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
      if (savedCollapsed === "true") {
        setSidebarCollapsed(true);
      }
    }

    // Prime the API auth token from current active session
    async function syncSessionToken() {
      try {
        const sessionRes = await authClient.getSession();
        if (sessionRes?.data?.session?.token) {
          setApiAuthToken(sessionRes.data.session.token);
        }
      } catch {
        // Fallback or dev mode handling
      }
    }
    syncSessionToken();
  }, []);

  useEffect(() => {
    if (typeof document !== "undefined") {
      document.title = TAB_TITLES[currentTab] || "CodePilot AI";
    }
  }, [currentTab]);

  const handleSelectTab = useCallback((tab: AppTab | string) => {
    const nextTab: AppTab = isAppTab(tab) ? tab : "dashboard";
    setCurrentTab(nextTab);
    if (typeof window !== "undefined") {
      localStorage.setItem("codepilot_active_tab", nextTab);
    }
  }, []);

  const handleToggleCollapse = useCallback(() => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      if (typeof window !== "undefined") {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
      }
      return next;
    });
  }, []);

  const handleCloseMobileMenu = useCallback(() => {
    setMobileMenuOpen(false);
  }, []);

  return (
    <div className="relative flex h-screen w-full overflow-hidden bg-[#080A10]">
      {/* Sidebar Navigation (Desktop collapsible + Mobile drawer) */}
      <div className="relative z-20 flex shrink-0">
        <Sidebar
          currentTab={currentTab}
          onSelectTab={handleSelectTab}
          collapsed={sidebarCollapsed}
          onToggleCollapse={handleToggleCollapse}
          mobileOpen={mobileMenuOpen}
          onCloseMobile={handleCloseMobileMenu}
        />
      </div>

      {/* Main Content Area */}
      <div className="relative z-10 flex-1 flex flex-col min-w-0 overflow-hidden">
        <Header
          currentTab={currentTab}
          onSelectTab={handleSelectTab}
          mobileMenuOpen={mobileMenuOpen}
          onOpenMobileMenu={() => setMobileMenuOpen(true)}
        />

        <main
          className={`flex-1 overflow-y-auto px-4 sm:px-6 lg:px-8 ${
            currentTab === "sandbox" || currentTab === "code-review"
              ? "py-3 sm:py-3.5 lg:py-3.5"
              : "py-5 sm:py-6 lg:py-7"
          }`}
        >
          <div key={currentTab} className="max-w-7xl mx-auto animate-cp-fade-up">
            {currentTab === "dashboard" && (
              <DashboardOverview onNavigate={handleSelectTab} />
            )}

            {currentTab === "ai-tutor" && <AITutor />}

            {currentTab === "code-review" && <CodeReviewer />}

            {currentTab === "sandbox" && <CodeSandbox />}

            {currentTab === "settings" && <Settings />}
          </div>
        </main>
      </div>
    </div>
  );
}

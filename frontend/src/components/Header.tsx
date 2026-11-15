"use client";

import React from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, Github, LogOut, Menu, Settings as SettingsIcon } from "lucide-react";
import { authClient } from "@/lib/auth/client";
import { performSignOut } from "@/lib/auth/signOut";
import { AppTab, TAB_META } from "@/lib/navigation";
import { Dropdown, IconButton } from "@/components/ui";
import { HealthBadge } from "./HealthBadge";

interface HeaderProps {
  currentTab: AppTab;
  onSelectTab: (tab: AppTab) => void;
  mobileMenuOpen: boolean;
  onOpenMobileMenu: () => void;
}

export function Header({
  currentTab,
  onSelectTab,
  mobileMenuOpen,
  onOpenMobileMenu,
}: HeaderProps) {
  const router = useRouter();
  const current = TAB_META[currentTab] || TAB_META.dashboard;

  const sessionHook =
    typeof authClient?.useSession === "function"
      ? authClient.useSession()
      : { data: null, isPending: false };
  const user = sessionHook?.data?.user;
  const displayName = user?.name || "Account";
  const displayEmail = user?.email || undefined;
  const userInitial = (displayName.charAt(0) || "A").toUpperCase();

  return (
    <header className="h-14 bg-[#0D0F15] border-b border-[#272B36] px-4 sm:px-6 lg:px-8 flex items-center justify-between gap-3 shrink-0 z-30">
      <div className="flex items-center gap-3 min-w-0">
        {/* Mobile Drawer Trigger */}
        <div className="md:hidden">
          <IconButton
            label="Open navigation menu"
            variant="secondary"
            size="sm"
            aria-expanded={mobileMenuOpen}
            aria-controls="mobile-sidebar-drawer"
            onClick={onOpenMobileMenu}
          >
            <Menu className="w-4 h-4" />
          </IconButton>
        </div>

        <div className="min-w-0">
          <h1 className="text-sm font-semibold text-[#FAFAFA] tracking-tight truncate">
            {current.title}
          </h1>
          {current.subtitle ? (
            <p className="hidden sm:block text-[11px] text-[#71717A] truncate">
              {current.subtitle}
            </p>
          ) : null}
        </div>
      </div>

      <div className="flex items-center gap-2 sm:gap-3 shrink-0">
        <HealthBadge />

        <div className="hidden sm:block h-4 w-px bg-[#27272A]" aria-hidden="true" />

        <a
          href="https://github.com/MohitJaiswal2507/CodePilot-"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Open CodePilot GitHub repository"
          className="hidden sm:inline-flex items-center gap-1.5 h-8 px-2.5 rounded-md border border-[#27272A] hover:border-[#3F3F46] bg-[#111113] hover:bg-[#18181B] text-xs text-[#A1A1AA] hover:text-[#FAFAFA] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3B82F6]"
        >
          <Github className="w-3.5 h-3.5" aria-hidden="true" />
          <span className="hidden lg:inline">Repository</span>
        </a>

        <Dropdown
          align="right"
          menuLabel="Account menu"
          trigger={
            <button
              type="button"
              className="inline-flex items-center gap-2 h-8 px-2 rounded-md border border-[#27272A] hover:border-[#3F3F46] bg-[#111113] hover:bg-[#18181B] text-xs text-[#FAFAFA] transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3B82F6]"
            >
              <span className="w-5 h-5 rounded-full bg-[#18181B] border border-[#27272A] flex items-center justify-center text-[10px] font-semibold text-[#FAFAFA]">
                {userInitial}
              </span>
              <span className="hidden md:inline max-w-[120px] truncate text-[#A1A1AA]">
                {displayName}
              </span>
              <ChevronDown className="w-3.5 h-3.5 text-[#71717A]" aria-hidden="true" />
            </button>
          }
          items={[
            {
              id: "settings",
              label: "Settings",
              description: displayEmail,
              icon: <SettingsIcon className="w-3.5 h-3.5 text-[#A1A1AA]" />,
              onSelect: () => onSelectTab("settings"),
            },
            {
              id: "sign-out",
              label: "Sign Out",
              danger: true,
              icon: <LogOut className="w-3.5 h-3.5" />,
              onSelect: () => {
                performSignOut(router).catch((err) => {
                  console.error("Sign out failed:", err);
                });
              },
            },
          ]}
        />
      </div>
    </header>
  );
}

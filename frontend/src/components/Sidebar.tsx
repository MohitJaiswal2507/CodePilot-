"use client";

import React, { useEffect, useRef, useState } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import {
  BookOpen,
  Code2,
  LayoutDashboard,
  Loader2,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Terminal,
  X,
} from "lucide-react";
import { authClient } from "@/lib/auth/client";
import { performSignOut } from "@/lib/auth/signOut";
import { AppTab, NAV_ITEMS, NavItemConfig } from "@/lib/navigation";
import { cn } from "@/lib/cn";
import { IconButton, Tooltip } from "@/components/ui";

const TAB_ICONS: Record<AppTab, React.ComponentType<{ className?: string }>> = {
  dashboard: LayoutDashboard,
  "ai-tutor": BookOpen,
  "code-review": Code2,
  sandbox: Terminal,
  settings: Settings,
};

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

interface SidebarProps {
  currentTab: AppTab;
  onSelectTab: (tab: AppTab) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export function Sidebar({
  currentTab,
  onSelectTab,
  collapsed,
  onToggleCollapse,
  mobileOpen,
  onCloseMobile,
}: SidebarProps) {
  const router = useRouter();
  const [isSigningOut, setIsSigningOut] = useState(false);
  const mobileDrawerRef = useRef<HTMLDivElement>(null);

  const sessionHook =
    typeof authClient?.useSession === "function"
      ? authClient.useSession()
      : { data: null, isPending: false };
  const user = sessionHook?.data?.user;
  const isPending = sessionHook?.isPending;

  const displayName = user?.name || "Workspace User";
  const displayEmail = user?.email || "";
  const userInitial = (displayName.charAt(0) || "U").toUpperCase();

  // Mobile drawer accessibility: focus trap, Escape, body scroll lock, focus restoration
  useEffect(() => {
    if (!mobileOpen) return;

    const previouslyFocused = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    requestAnimationFrame(() => {
      mobileDrawerRef.current?.focus();
    });

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCloseMobile();
        return;
      }

      if (e.key === "Tab" && mobileDrawerRef.current) {
        const focusables = Array.from(
          mobileDrawerRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
        ).filter((el) => !el.hasAttribute("disabled"));

        if (focusables.length === 0) {
          e.preventDefault();
          mobileDrawerRef.current.focus();
          return;
        }

        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const active = document.activeElement as HTMLElement | null;

        if (e.shiftKey) {
          if (
            !active ||
            active === mobileDrawerRef.current ||
            active === first ||
            !mobileDrawerRef.current.contains(active)
          ) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (
            !active ||
            active === last ||
            !mobileDrawerRef.current.contains(active)
          ) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus?.();
    };
  }, [mobileOpen, onCloseMobile]);

  const handleSignOut = async () => {
    setIsSigningOut(true);
    try {
      await performSignOut(router);
    } catch (err) {
      console.error("Sign out failed:", err);
      setIsSigningOut(false);
    }
  };

  const handleNavClick = (tab: AppTab) => {
    onSelectTab(tab);
    if (mobileOpen) {
      onCloseMobile();
    }
  };

  const workspaceItems = NAV_ITEMS.filter((item) => item.group === "workspace");
  const preferenceItems = NAV_ITEMS.filter((item) => item.group === "preferences");

  const renderNavGroup = (
    groupLabel: string,
    items: NavItemConfig[],
    isCompact: boolean
  ) => (
    <div className="space-y-1">
      {!isCompact && (
        <p className="px-2.5 pb-1 text-[10px] font-semibold uppercase tracking-wider text-[#71717A]">
          {groupLabel}
        </p>
      )}
      {isCompact && <div className="my-2 border-t border-[#27272A]" aria-hidden="true" />}

      {items.map((item) => {
        const Icon = TAB_ICONS[item.id];
        const isActive = currentTab === item.id;

        const button = (
          <button
            key={item.id}
            type="button"
            onClick={() => handleNavClick(item.id)}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "relative w-full flex items-center rounded-md text-xs font-medium transition-colors duration-150 cursor-pointer",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3B82F6]",
              isCompact ? "justify-center h-9 px-0" : "gap-2.5 h-9 px-2.5",
              isActive
                ? "bg-[#181C25] text-[#FAFAFA] border border-[#272B36]"
                : "text-[#A1A1AA] hover:text-[#FAFAFA] hover:bg-[#181C25]/50 border border-transparent"
            )}
          >
            {isActive && (
              <span
                aria-hidden="true"
                className="absolute left-0 top-1.5 bottom-1.5 w-[2.5px] rounded-r bg-[#3B82F6]"
              />
            )}
            <Icon
              className={cn(
                "w-4 h-4 shrink-0 transition-colors",
                isActive ? "text-[#3B82F6]" : "text-[#71717A]"
              )}
            />
            {!isCompact && <span className="truncate">{item.label}</span>}
          </button>
        );

        return isCompact ? (
          <Tooltip key={item.id} content={item.label} side="right" className="w-full flex justify-center">
            {button}
          </Tooltip>
        ) : (
          button
        );
      })}
    </div>
  );

  const renderSidebarBody = (isCompact: boolean, isMobileDrawer: boolean) => (
    <div className="flex flex-col justify-between h-full select-none">
      {/* Brand Header */}
      <div>
        <div
          className={cn(
            "h-14 flex items-center border-b border-[#27272A] shrink-0",
            isCompact ? "justify-center px-2" : "justify-between px-4"
          )}
        >
          {!isCompact && (
            <div className="flex items-center gap-2.5 min-w-0">
              <Image
                src="/codepilot-icon.svg"
                alt="CodePilot logo"
                width={28}
                height={28}
                priority
                className="w-7 h-7 rounded-lg object-contain shrink-0 shadow-md shadow-blue-500/10"
              />
              <span className="font-semibold tracking-tight text-[#F4F4F5] text-sm truncate">
                CodePilot
              </span>
            </div>
          )}

          {isMobileDrawer ? (
            <IconButton
              label="Close navigation menu"
              size="sm"
              onClick={onCloseMobile}
            >
              <X className="w-4 h-4" />
            </IconButton>
          ) : (
            <Tooltip
              content={isCompact ? "Expand sidebar" : "Collapse sidebar"}
              side="right"
            >
              <IconButton
                label={isCompact ? "Expand sidebar" : "Collapse sidebar"}
                size="sm"
                onClick={onToggleCollapse}
              >
                {isCompact ? (
                  <PanelLeftOpen className="w-4 h-4" />
                ) : (
                  <PanelLeftClose className="w-4 h-4" />
                )}
              </IconButton>
            </Tooltip>
          )}
        </div>

        {/* Navigation Groups */}
        <nav
          aria-label="Primary navigation"
          className={cn("py-4 space-y-5", isCompact ? "px-2" : "px-3")}
        >
          {renderNavGroup("Workspace", workspaceItems, isCompact)}
          {renderNavGroup("Preferences", preferenceItems, isCompact)}
        </nav>
      </div>

      {/* User Account & Sign Out Footer */}
      <div className={cn("border-t border-white/[0.08] space-y-2", isCompact ? "p-2" : "p-3")}>
        {!isCompact ? (
          <div className="px-2.5 py-2 rounded-md glass-subtle flex items-center gap-2.5 min-w-0">
            <div className="w-7 h-7 rounded-full bg-[#111113] border border-[#27272A] flex items-center justify-center text-xs font-semibold text-[#FAFAFA] shrink-0">
              {isPending ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin text-[#A1A1AA]" />
              ) : (
                userInitial
              )}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium text-[#FAFAFA] truncate">
                {isPending ? "Loading..." : displayName}
              </p>
              {displayEmail && (
                <p className="text-[11px] text-[#71717A] truncate" title={displayEmail}>
                  {displayEmail}
                </p>
              )}
            </div>
          </div>
        ) : (
          <Tooltip content={displayEmail ? `${displayName} (${displayEmail})` : displayName} side="right" className="w-full flex justify-center">
            <div
              tabIndex={0}
              className="w-8 h-8 rounded-full bg-[#18181B] border border-[#27272A] flex items-center justify-center text-xs font-semibold text-[#FAFAFA] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3B82F6]"
            >
              {isPending ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin text-[#A1A1AA]" />
              ) : (
                userInitial
              )}
            </div>
          </Tooltip>
        )}

        {isCompact ? (
          <Tooltip content="Sign Out" side="right" className="w-full flex justify-center">
            <IconButton
              label="Sign out"
              variant="danger"
              size="md"
              onClick={handleSignOut}
              isLoading={isSigningOut}
              className="w-9 h-9"
            >
              <LogOut className="w-4 h-4" />
            </IconButton>
          </Tooltip>
        ) : (
          <button
            type="button"
            onClick={handleSignOut}
            disabled={isSigningOut}
            className="w-full h-8 flex items-center justify-center gap-2 px-3 rounded-md text-xs font-medium text-[#A1A1AA] hover:text-red-400 hover:bg-red-500/10 border border-transparent hover:border-red-500/25 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3B82F6]"
          >
            {isSigningOut ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <LogOut className="w-3.5 h-3.5" />
            )}
            <span>{isSigningOut ? "Signing out..." : "Sign Out"}</span>
          </button>
        )}
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop & Tablet Collapsible Sidebar */}
      <aside
        aria-label="Workspace sidebar"
        className={cn(
          "hidden md:flex flex-col shrink-0 bg-[#0D0F15] border-r border-[#272B36] transition-[width] duration-200 ease-out motion-reduce:transition-none",
          collapsed ? "w-[68px]" : "w-60"
        )}
      >
        {renderSidebarBody(collapsed, false)}
      </aside>

      {/* Mobile Slide-in Navigation Drawer */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-50 md:hidden flex bg-black/70 backdrop-blur-sm"
          onClick={(e) => {
            if (e.target === e.currentTarget) onCloseMobile();
          }}
        >
          <div
            id="mobile-sidebar-drawer"
            ref={mobileDrawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation menu"
            tabIndex={-1}
            className="w-72 max-w-[85vw] h-full bg-[#111319] border-r border-[#272B36] outline-none"
          >
            {renderSidebarBody(false, true)}
          </div>
        </div>
      )}
    </>
  );
}

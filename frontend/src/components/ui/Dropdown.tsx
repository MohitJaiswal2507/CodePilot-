"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";

export interface DropdownItem {
  id: string;
  label: string;
  description?: string;
  icon?: React.ReactNode;
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
}

export interface DropdownProps {
  trigger: React.ReactElement<React.HTMLAttributes<HTMLElement>>;
  items: DropdownItem[];
  align?: "left" | "right";
  menuLabel?: string;
  className?: string;
}

export function Dropdown({
  trigger,
  items,
  align = "right",
  menuLabel = "Options",
  className,
}: DropdownProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const openedViaKeyboardRef = useRef(false);

  const focusTrigger = useCallback(() => {
    const triggerEl = containerRef.current?.querySelector<HTMLElement>(
      '[aria-haspopup="menu"]'
    );
    triggerEl?.focus();
  }, []);

  const closeMenu = useCallback(
    (restoreFocus: boolean) => {
      setOpen(false);
      if (restoreFocus) {
        requestAnimationFrame(() => focusTrigger());
      }
    },
    [focusTrigger]
  );

  useEffect(() => {
    if (!open) return;

    if (openedViaKeyboardRef.current) {
      const firstEnabledIdx = items.findIndex((item) => !item.disabled);
      if (firstEnabledIdx !== -1) {
        requestAnimationFrame(() => {
          itemRefs.current[firstEnabledIdx]?.focus();
        });
      }
    }

    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeMenu(true);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [open, items, closeMenu]);

  const moveFocus = (targetIndex: number) => {
    const enabledIndices = items
      .map((item, idx) => (item.disabled ? -1 : idx))
      .filter((idx) => idx !== -1);
    if (enabledIndices.length === 0) return;

    const clamped =
      ((targetIndex % enabledIndices.length) + enabledIndices.length) %
      enabledIndices.length;
    itemRefs.current[enabledIndices[clamped]]?.focus();
  };

  const handleMenuKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const enabledIndices = items
      .map((item, idx) => (item.disabled ? -1 : idx))
      .filter((idx) => idx !== -1);
    if (enabledIndices.length === 0) return;

    const currentEl = document.activeElement as HTMLButtonElement | null;
    const currentItemIdx = itemRefs.current.findIndex((el) => el === currentEl);
    const currentEnabledPos = enabledIndices.indexOf(currentItemIdx);

    if (e.key === "ArrowDown") {
      e.preventDefault();
      moveFocus(currentEnabledPos === -1 ? 0 : currentEnabledPos + 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      moveFocus(
        currentEnabledPos === -1
          ? enabledIndices.length - 1
          : currentEnabledPos - 1
      );
    } else if (e.key === "Home") {
      e.preventDefault();
      moveFocus(0);
    } else if (e.key === "End") {
      e.preventDefault();
      moveFocus(enabledIndices.length - 1);
    }
  };

  const triggerElement = React.isValidElement(trigger)
    ? React.cloneElement(trigger, {
        "aria-expanded": open,
        "aria-haspopup": "menu",
        onClick: (e: React.MouseEvent<HTMLElement>) => {
          trigger.props.onClick?.(e);
          if (!e.defaultPrevented) {
            openedViaKeyboardRef.current = e.detail === 0;
            setOpen((prev) => !prev);
          }
        },
        onKeyDown: (e: React.KeyboardEvent<HTMLElement>) => {
          trigger.props.onKeyDown?.(e);
          if (e.defaultPrevented) return;
          if (!open && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
            e.preventDefault();
            openedViaKeyboardRef.current = true;
            setOpen(true);
          }
        },
      })
    : trigger;

  return (
    <div ref={containerRef} className={cn("relative inline-flex", className)}>
      {triggerElement}

      {open && (
        <div
          role="menu"
          aria-label={menuLabel}
          onKeyDown={handleMenuKeyDown}
          className={cn(
            "absolute top-full mt-1.5 z-40 min-w-[196px] rounded-md glass-elevated p-1 animate-cp-dropdown",
            align === "right" ? "right-0" : "left-0"
          )}
        >
          {items.map((item, idx) => (
            <button
              key={item.id}
              ref={(el) => {
                itemRefs.current[idx] = el;
              }}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              onClick={() => {
                closeMenu(true);
                item.onSelect();
              }}
              className={cn(
                "w-full flex items-start gap-2.5 px-2.5 py-2 rounded-sm text-left text-xs transition-colors cursor-pointer",
                "focus-visible:outline-none focus-visible:bg-[#18181B]",
                "disabled:opacity-40 disabled:cursor-not-allowed",
                item.danger
                  ? "text-red-400 hover:bg-red-500/10"
                  : "text-[#FAFAFA] hover:bg-[#18181B]"
              )}
            >
              {item.icon && <span className="shrink-0 mt-0.5">{item.icon}</span>}
              <span className="min-w-0">
                <span className="block font-medium truncate">{item.label}</span>
                {item.description && (
                  <span className="block text-[11px] text-[#71717A] truncate">
                    {item.description}
                  </span>
                )}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

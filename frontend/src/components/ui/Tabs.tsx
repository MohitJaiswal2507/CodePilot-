"use client";

import React, { useRef } from "react";
import { cn } from "@/lib/cn";

export interface TabItem<T extends string = string> {
  id: T;
  label: string;
  icon?: React.ReactNode;
  badge?: React.ReactNode;
  disabled?: boolean;
}

export interface TabsProps<T extends string = string> {
  items: TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  variant?: "underline" | "pill";
  ariaLabel?: string;
  idPrefix?: string;
  className?: string;
}

export function Tabs<T extends string = string>({
  items,
  value,
  onChange,
  variant = "underline",
  ariaLabel = "Tabs",
  idPrefix,
  className,
}: TabsProps<T>) {
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const handleKeyDown = (e: React.KeyboardEvent, index: number) => {
    const enabledIndices = items
      .map((item, idx) => (item.disabled ? -1 : idx))
      .filter((idx) => idx !== -1);
    if (enabledIndices.length === 0) return;

    const currentPos = enabledIndices.indexOf(index);
    let nextIdx: number | null = null;

    if (e.key === "ArrowRight") {
      nextIdx = enabledIndices[(currentPos + 1) % enabledIndices.length];
    } else if (e.key === "ArrowLeft") {
      nextIdx =
        enabledIndices[
          (currentPos - 1 + enabledIndices.length) % enabledIndices.length
        ];
    } else if (e.key === "Home") {
      nextIdx = enabledIndices[0];
    } else if (e.key === "End") {
      nextIdx = enabledIndices[enabledIndices.length - 1];
    }

    if (nextIdx !== null) {
      e.preventDefault();
      onChange(items[nextIdx].id);
      tabRefs.current[nextIdx]?.focus();
    }
  };

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        variant === "underline"
          ? "flex items-center gap-1 border-b border-[#27272A] overflow-x-auto"
          : "inline-flex items-center gap-1 p-1 rounded-md bg-[#111113] border border-[#27272A]",
        className
      )}
    >
      {items.map((item, idx) => {
        const isActive = item.id === value;
        return (
          <button
            key={item.id}
            ref={(el) => {
              tabRefs.current[idx] = el;
            }}
            id={idPrefix ? `${idPrefix}-tab-${item.id}` : undefined}
            type="button"
            role="tab"
            aria-selected={isActive}
            aria-controls={idPrefix ? `${idPrefix}-panel-${item.id}` : undefined}
            tabIndex={isActive ? 0 : -1}
            disabled={item.disabled}
            onClick={() => onChange(item.id)}
            onKeyDown={(e) => handleKeyDown(e, idx)}
            className={cn(
              "inline-flex items-center gap-1.5 text-xs font-medium transition-colors whitespace-nowrap cursor-pointer",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3B82F6]",
              "disabled:opacity-40 disabled:cursor-not-allowed",
              variant === "underline"
                ? cn(
                    "px-3 py-2 border-b-2 -mb-px",
                    isActive
                      ? "border-[#3B82F6] text-[#FAFAFA]"
                      : "border-transparent text-[#A1A1AA] hover:text-[#FAFAFA]"
                  )
                : cn(
                    "px-2.5 py-1 rounded-sm",
                    isActive
                      ? "bg-[#18181B] text-[#FAFAFA] shadow-vercel-sm"
                      : "text-[#A1A1AA] hover:text-[#FAFAFA]"
                  )
            )}
          >
            {item.icon && <span className="shrink-0 inline-flex">{item.icon}</span>}
            <span>{item.label}</span>
            {item.badge}
          </button>
        );
      })}
    </div>
  );
}


import React from "react";
import { cn } from "@/lib/cn";

export type BadgeVariant =
  | "neutral"
  | "success"
  | "warning"
  | "danger"
  | "accent"
  | "ai"
  | "cyan";
export type BadgeSize = "sm" | "md";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  size?: BadgeSize;
  dot?: boolean;
}

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  neutral: "bg-[#181C25] text-[#A1A1AA] border-[#272B36]",
  success: "bg-emerald-500/10 text-emerald-400 border-emerald-500/25",
  warning: "bg-amber-500/10 text-amber-400 border-amber-500/25",
  danger: "bg-red-500/10 text-red-400 border-red-500/25",
  accent: "bg-[#3B82F6]/10 text-[#60A5FA] border-[#3B82F6]/30",
  ai: "bg-[#3B82F6]/15 text-[#93C5FD] border-[#3B82F6]/30",
  cyan: "bg-[#3B82F6]/10 text-[#93C5FD] border-[#3B82F6]/30",
};

const DOT_CLASSES: Record<BadgeVariant, string> = {
  neutral: "bg-[#71717A]",
  success: "bg-emerald-400",
  warning: "bg-amber-400",
  danger: "bg-red-400",
  accent: "bg-[#3B82F6]",
  ai: "bg-[#3B82F6]",
  cyan: "bg-[#3B82F6]",
};

const SIZE_CLASSES: Record<BadgeSize, string> = {
  sm: "px-2 py-0.5 text-[10px]",
  md: "px-2.5 py-0.5 text-[11px]",
};

export function Badge({
  variant = "neutral",
  size = "md",
  dot = false,
  className,
  children,
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border font-medium leading-tight whitespace-nowrap",
        VARIANT_CLASSES[variant],
        SIZE_CLASSES[size],
        className
      )}
      {...props}
    >
      {dot && (
        <span
          className={cn("h-1.5 w-1.5 rounded-full shrink-0", DOT_CLASSES[variant])}
          aria-hidden="true"
        />
      )}
      {children}
    </span>
  );
}


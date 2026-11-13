"use client";

import React from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

export type IconButtonVariant = "ghost" | "secondary" | "danger";
export type IconButtonSize = "sm" | "md";

export interface IconButtonProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "aria-label"> {
  label: string;
  variant?: IconButtonVariant;
  size?: IconButtonSize;
  isLoading?: boolean;
}

const VARIANT_CLASSES: Record<IconButtonVariant, string> = {
  ghost:
    "bg-transparent hover:bg-[#18181B] text-[#A1A1AA] hover:text-[#FAFAFA] border border-transparent",
  secondary:
    "bg-[#18181B] hover:bg-[#1F1F23] text-[#A1A1AA] hover:text-[#FAFAFA] border border-[#27272A] hover:border-[#3F3F46]",
  danger:
    "bg-transparent hover:bg-red-500/10 text-[#A1A1AA] hover:text-red-400 border border-transparent hover:border-red-500/30",
};

const SIZE_CLASSES: Record<IconButtonSize, string> = {
  sm: "h-7 w-7 rounded-md",
  md: "h-9 w-9 rounded-md",
};

export const IconButton = React.forwardRef<HTMLButtonElement, IconButtonProps>(
  function IconButton(
    {
      label,
      variant = "ghost",
      size = "md",
      isLoading = false,
      disabled,
      className,
      children,
      type = "button",
      title,
      ...props
    },
    ref
  ) {
    const isDisabled = disabled || isLoading;

    return (
      <button
        ref={ref}
        type={type}
        aria-label={label}
        title={title ?? label}
        disabled={isDisabled}
        aria-busy={isLoading || undefined}
        className={cn(
          "inline-flex items-center justify-center transition-colors cursor-pointer shrink-0",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3B82F6] focus-visible:ring-offset-2 focus-visible:ring-offset-[#09090B]",
          "disabled:opacity-50 disabled:cursor-not-allowed",
          VARIANT_CLASSES[variant],
          SIZE_CLASSES[size],
          className
        )}
        {...props}
      >
        {isLoading ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
        ) : (
          children
        )}
      </button>
    );
  }
);


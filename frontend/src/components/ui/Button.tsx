"use client";

import React from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  isLoading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "bg-[#3B82F6] hover:bg-[#2563EB] text-[#FAFAFA] border border-transparent shadow-vercel-sm",
  secondary:
    "bg-[#181C25] hover:bg-[#1E2330] text-[#F4F4F5] border border-[#272B36] hover:border-[#373D4D]",
  ghost:
    "bg-transparent hover:bg-[#181C25] text-[#A1A1AA] hover:text-[#F4F4F5] border border-transparent",
  danger:
    "bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30 hover:border-red-500/50",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-xs gap-1.5 rounded-md",
  md: "h-9 px-3.5 text-xs gap-2 rounded-md",
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    {
      variant = "primary",
      size = "md",
      isLoading = false,
      disabled,
      leftIcon,
      rightIcon,
      className,
      children,
      type = "button",
      ...props
    },
    ref
  ) {
    const isDisabled = disabled || isLoading;

    return (
      <button
        ref={ref}
        type={type}
        disabled={isDisabled}
        aria-busy={isLoading || undefined}
        className={cn(
          "inline-flex items-center justify-center font-medium transition-all duration-150 active:scale-[0.98] motion-reduce:active:scale-100 select-none cursor-pointer",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3B82F6] focus-visible:ring-offset-2 focus-visible:ring-offset-[#09090B]",
          "disabled:opacity-50 disabled:cursor-not-allowed",
          VARIANT_CLASSES[variant],
          SIZE_CLASSES[size],
          className
        )}
        {...props}
      >
        {isLoading ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" aria-hidden="true" />
        ) : (
          leftIcon && <span className="shrink-0 inline-flex">{leftIcon}</span>
        )}
        <span>{children}</span>
        {!isLoading && rightIcon && (
          <span className="shrink-0 inline-flex">{rightIcon}</span>
        )}
      </button>
    );
  }
);


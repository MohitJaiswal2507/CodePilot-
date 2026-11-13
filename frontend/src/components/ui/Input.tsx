"use client";

import React, { useId } from "react";
import { cn } from "@/lib/cn";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: string;
  error?: string;
  leftIcon?: React.ReactNode;
  rightElement?: React.ReactNode;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, leftIcon, rightElement, className, id, ...props },
  ref
) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const errorId = error ? `${inputId}-error` : undefined;

  return (
    <div className="space-y-1.5 w-full">
      {label && (
        <label
          htmlFor={inputId}
          className="block text-xs font-medium text-[#FAFAFA]"
        >
          {label}
        </label>
      )}
      <div className="relative flex items-center">
        {leftIcon && (
          <div className="absolute left-3 text-[#71717A] pointer-events-none flex items-center">
            {leftIcon}
          </div>
        )}
        <input
          ref={ref}
          id={inputId}
          aria-invalid={error ? true : undefined}
          aria-describedby={[errorId, hintId].filter(Boolean).join(" ") || undefined}
          className={cn(
            "w-full h-9 rounded-md bg-[#111113] border text-xs text-[#FAFAFA] placeholder:text-[#71717A] transition-colors",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3B82F6] focus-visible:border-[#3B82F6]",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            error ? "border-red-500/60" : "border-[#27272A] hover:border-[#3F3F46]",
            leftIcon ? "pl-9" : "px-3",
            rightElement ? "pr-9" : "pr-3",
            className
          )}
          {...props}
        />
        {rightElement && (
          <div className="absolute right-2 flex items-center">{rightElement}</div>
        )}
      </div>
      {error && (
        <p id={errorId} className="text-[11px] text-red-400">
          {error}
        </p>
      )}
      {!error && hint && (
        <p id={hintId} className="text-[11px] text-[#71717A]">
          {hint}
        </p>
      )}
    </div>
  );
});


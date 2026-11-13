"use client";

import React, { useId } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/cn";

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  hint?: string;
  error?: string;
  options?: SelectOption[];
}

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  function Select({ label, hint, error, options, children, className, id, ...props }, ref) {
    const generatedId = useId();
    const selectId = id ?? generatedId;
    const hintId = hint ? `${selectId}-hint` : undefined;
    const errorId = error ? `${selectId}-error` : undefined;

    return (
      <div className="space-y-1.5 w-full">
        {label && (
          <label
            htmlFor={selectId}
            className="block text-xs font-medium text-[#FAFAFA]"
          >
            {label}
          </label>
        )}
        <div className="relative">
          <select
            ref={ref}
            id={selectId}
            aria-invalid={error ? true : undefined}
            aria-describedby={[errorId, hintId].filter(Boolean).join(" ") || undefined}
            className={cn(
              "w-full h-9 appearance-none rounded-md bg-[#111113] border pl-3 pr-8 text-xs text-[#FAFAFA] transition-colors cursor-pointer",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3B82F6] focus-visible:border-[#3B82F6]",
              "disabled:opacity-50 disabled:cursor-not-allowed",
              error ? "border-red-500/60" : "border-[#27272A] hover:border-[#3F3F46]",
              className
            )}
            {...props}
          >
            {options
              ? options.map((opt) => (
                  <option
                    key={opt.value}
                    value={opt.value}
                    disabled={opt.disabled}
                    className="bg-[#111113] text-[#FAFAFA]"
                  >
                    {opt.label}
                  </option>
                ))
              : children}
          </select>
          <ChevronDown
            className="w-3.5 h-3.5 text-[#71717A] pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2"
            aria-hidden="true"
          />
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
  }
);


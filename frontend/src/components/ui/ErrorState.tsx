"use client";

import React from "react";
import { AlertCircle, RefreshCw } from "lucide-react";
import { cn } from "@/lib/cn";
import { Button } from "./Button";

export interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
}

export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
  retryLabel = "Try again",
  className,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cn(
        "rounded-lg border border-red-500/25 bg-red-500/10 p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3",
        className
      )}
    >
      <div className="flex items-start gap-3">
        <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" aria-hidden="true" />
        <div className="space-y-0.5">
          <p className="text-xs font-semibold text-red-300">{title}</p>
          <p className="text-xs text-red-200/85 leading-relaxed">{message}</p>
        </div>
      </div>

      {onRetry && (
        <Button
          variant="secondary"
          size="sm"
          onClick={onRetry}
          leftIcon={<RefreshCw className="w-3 h-3" />}
          className="shrink-0 self-start sm:self-center"
        >
          {retryLabel}
        </Button>
      )}
    </div>
  );
}


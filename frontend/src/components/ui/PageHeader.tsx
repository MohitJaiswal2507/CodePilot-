import React from "react";
import { cn } from "@/lib/cn";

export interface PageHeaderProps {
  title: string;
  description?: string;
  badge?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}

export function PageHeader({
  title,
  description,
  badge,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <div
      className={cn(
        "flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-5 border-b border-[#27272A]",
        className
      )}
    >
      <div className="space-y-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="text-lg font-semibold text-[#FAFAFA] tracking-tight">
            {title}
          </h1>
          {badge}
        </div>
        {description && (
          <p className="text-xs text-[#A1A1AA] leading-relaxed">{description}</p>
        )}
      </div>

      {actions && (
        <div className="flex flex-wrap items-center gap-2 shrink-0">{actions}</div>
      )}
    </div>
  );
}


import React from "react";
import { cn } from "@/lib/cn";

export interface SectionHeaderProps {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  className?: string;
}

export function SectionHeader({
  title,
  description,
  actions,
  className,
}: SectionHeaderProps) {
  return (
    <div
      className={cn(
        "flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2",
        className
      )}
    >
      <div className="space-y-0.5 min-w-0">
        <h2 className="text-sm font-semibold text-[#FAFAFA] tracking-tight">
          {title}
        </h2>
        {description && (
          <p className="text-xs text-[#A1A1AA]">{description}</p>
        )}
      </div>
      {actions && (
        <div className="flex items-center gap-2 shrink-0">{actions}</div>
      )}
    </div>
  );
}


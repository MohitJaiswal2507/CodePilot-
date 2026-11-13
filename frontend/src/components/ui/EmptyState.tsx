import React from "react";
import { Inbox } from "lucide-react";
import { cn } from "@/lib/cn";

export interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "rounded-lg border border-dashed border-[#27272A] bg-[#111113]/60 px-6 py-10 text-center flex flex-col items-center justify-center gap-2.5",
        className
      )}
    >
      <div className="w-9 h-9 rounded-md border border-[#27272A] bg-[#18181B] flex items-center justify-center text-[#71717A]">
        {icon ?? <Inbox className="w-4 h-4" aria-hidden="true" />}
      </div>
      <div className="space-y-1 max-w-sm">
        <p className="text-xs font-semibold text-[#FAFAFA]">{title}</p>
        {description && (
          <p className="text-xs text-[#A1A1AA] leading-relaxed">{description}</p>
        )}
      </div>
      {action && <div className="pt-1">{action}</div>}
    </div>
  );
}


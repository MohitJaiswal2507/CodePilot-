import React from "react";
import { cn } from "@/lib/cn";

export interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  className?: string;
}

export function Skeleton({ className, ...props }: SkeletonProps) {
  return (
    <div
      aria-hidden="true"
      className={cn("rounded-md bg-[#18181B] animate-cp-shimmer", className)}
      {...props}
    />
  );
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-2" aria-hidden="true">
      {Array.from({ length: lines }).map((_, idx) => (
        <Skeleton
          key={idx}
          className={cn("h-3", idx === lines - 1 ? "w-2/3" : "w-full")}
        />
      ))}
    </div>
  );
}

export function SkeletonCard() {
  return (
    <div
      aria-hidden="true"
      className="rounded-lg border border-[#27272A] bg-[#111113] p-5 space-y-3"
    >
      <Skeleton className="h-4 w-1/3" />
      <SkeletonText lines={2} />
    </div>
  );
}


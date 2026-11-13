import React from "react";
import { cn } from "@/lib/cn";

export type CardPadding = "none" | "sm" | "md" | "lg";

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  elevated?: boolean;
  glass?: boolean;
  interactive?: boolean;
  padding?: CardPadding;
}

const PADDING_CLASSES: Record<CardPadding, string> = {
  none: "",
  sm: "p-3.5",
  md: "p-5",
  lg: "p-6",
};

export function Card({
  elevated = false,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  glass = false,
  interactive = false,
  padding = "md",
  className,
  children,
  ...props
}: CardProps) {
  return (
    <div
      className={cn(
        "rounded-lg border border-[#272B36]",
        elevated ? "bg-[#181C25]" : "bg-[#111319]",
        interactive && "transition-colors duration-150 hover:border-[#373D4D]",
        PADDING_CLASSES[padding],
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("flex items-start justify-between gap-4", className)} {...props}>
      {children}
    </div>
  );
}

export function CardTitle({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn("text-sm font-semibold text-[#FAFAFA] tracking-tight", className)}
      {...props}
    >
      {children}
    </h3>
  );
}

export function CardDescription({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p className={cn("text-xs text-[#A1A1AA] leading-relaxed", className)} {...props}>
      {children}
    </p>
  );
}


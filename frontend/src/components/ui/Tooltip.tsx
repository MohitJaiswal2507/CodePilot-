"use client";

import React, { useEffect, useId, useState } from "react";
import { cn } from "@/lib/cn";

export type TooltipSide = "top" | "right" | "bottom" | "left";

export interface TooltipProps {
  content: string;
  side?: TooltipSide;
  disabled?: boolean;
  children: React.ReactElement<React.HTMLAttributes<HTMLElement>>;
  className?: string;
}

const POSITION_CLASSES: Record<TooltipSide, string> = {
  top: "bottom-full left-1/2 -translate-x-1/2 mb-1.5",
  right: "left-full top-1/2 -translate-y-1/2 ml-2",
  bottom: "top-full left-1/2 -translate-x-1/2 mt-1.5",
  left: "right-full top-1/2 -translate-y-1/2 mr-2",
};

export function Tooltip({
  content,
  side = "top",
  disabled = false,
  children,
  className,
}: TooltipProps) {
  const [isOpen, setIsOpen] = useState(false);
  const tooltipId = useId();

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsOpen(false);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen]);

  if (disabled || !content) {
    return children;
  }

  const existingDescribedBy = children.props["aria-describedby"];
  const describedBy = isOpen
    ? [existingDescribedBy, tooltipId].filter(Boolean).join(" ")
    : existingDescribedBy;

  const childWithProps = React.isValidElement(children)
    ? React.cloneElement(children, {
        "aria-describedby": describedBy,
        onMouseEnter: (e: React.MouseEvent<HTMLElement>) => {
          children.props.onMouseEnter?.(e);
          setIsOpen(true);
        },
        onMouseLeave: (e: React.MouseEvent<HTMLElement>) => {
          children.props.onMouseLeave?.(e);
          setIsOpen(false);
        },
        onFocus: (e: React.FocusEvent<HTMLElement>) => {
          children.props.onFocus?.(e);
          setIsOpen(true);
        },
        onBlur: (e: React.FocusEvent<HTMLElement>) => {
          children.props.onBlur?.(e);
          setIsOpen(false);
        },
      })
    : children;

  return (
    <div className={cn("relative inline-flex", className)}>
      {childWithProps}
      {isOpen && (
        <div
          id={tooltipId}
          role="tooltip"
          className={cn(
            "pointer-events-none absolute z-50 px-2 py-1 rounded-sm glass-elevated text-[11px] font-medium text-[#FAFAFA] whitespace-nowrap animate-cp-fade-in",
            POSITION_CLASSES[side]
          )}
        >
          {content}
        </div>
      )}
    </div>
  );
}

"use client";

import React, { useRef, useEffect } from "react";
import { Send, Square, Paperclip, X, CornerDownLeft } from "lucide-react";

export interface ChatComposerProps {
  value: string;
  onChange: (val: string) => void;
  onSend: () => void;
  onCancel: () => void;
  isLoading: boolean;
  isEditing?: boolean;
  onCancelEdit?: () => void;
  onEditPrevious?: () => void;
  placeholder?: string;
  disabled?: boolean;
}

export function ChatComposer({
  value,
  onChange,
  onSend,
  onCancel,
  isLoading,
  isEditing = false,
  onCancelEdit,
  onEditPrevious,
  placeholder = "Ask a question, paste code, or drop an error log... (Shift + Enter for new line, Enter to send)",
  disabled = false,
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea height as user types or pastes
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = "auto";
    const nextHeight = Math.min(Math.max(textarea.scrollHeight, 44), 200);
    textarea.style.height = `${nextHeight}px`;
  }, [value]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // 1. Enter without Shift -> Send
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!isLoading && value.trim()) {
        onSend();
      }
      return;
    }

    // 2. Ctrl/Cmd + Enter -> Alternative Send
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      if (!isLoading && value.trim()) {
        onSend();
      }
      return;
    }

    // 3. ArrowUp on empty composer -> Edit previous user message
    if (e.key === "ArrowUp" && !value.trim() && onEditPrevious) {
      e.preventDefault();
      onEditPrevious();
      return;
    }

    // 4. Escape -> Cancel editing previous message
    if (e.key === "Escape") {
      if (isEditing && onCancelEdit) {
        e.preventDefault();
        onCancelEdit();
      } else if (isLoading) {
        e.preventDefault();
        onCancel();
      }
    }
  };

  const hasContent = value.trim().length > 0;

  return (
    <div className="relative rounded-xl border border-white/[0.1] bg-[#111319]/90 backdrop-blur-md shadow-xl transition-all duration-150 focus-within:border-[#8B5CF6]/60 focus-within:ring-2 focus-within:ring-[#8B5CF6]/20">
      {/* Editing Previous Message Banner */}
      {isEditing && (
        <div className="flex items-center justify-between px-3 py-1.5 bg-[#8B5CF6]/15 border-b border-[#8B5CF6]/30 rounded-t-xl text-[11px] text-[#A78BFA]">
          <div className="flex items-center gap-1.5">
            <CornerDownLeft className="w-3.5 h-3.5 text-[#A78BFA]" />
            <span className="font-medium">Editing previous message</span>
            <span className="text-[#A1A1AA] text-[10px]">(Press Esc to cancel)</span>
          </div>
          {onCancelEdit && (
            <button
              onClick={onCancelEdit}
              className="p-1 rounded hover:bg-white/[0.08] text-[#A1A1AA] hover:text-[#F4F4F5] transition-colors"
              title="Cancel editing"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      )}

      {/* Main Composer Area */}
      <div className="flex items-end gap-2 p-2.5 sm:p-3">
        {/* Attachment Placeholder */}
        <button
          type="button"
          disabled={disabled || isLoading}
          title="Attach file or code snippet (Coming Soon)"
          className="p-2 rounded-lg text-[#71717A] hover:text-[#F4F4F5] hover:bg-white/[0.06] transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
        >
          <Paperclip className="w-4 h-4" />
        </button>

        {/* Textarea */}
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
          className="flex-1 bg-transparent text-xs sm:text-[13px] text-[#F4F4F5] placeholder:text-[#71717A] resize-none outline-none leading-relaxed min-h-[44px] max-h-[200px] overflow-y-auto py-2 px-1 font-sans selection:bg-[#8B5CF6]/30"
          style={{ height: "44px" }}
        />

        {/* Action Button: Send or Stop Generation */}
        <div className="shrink-0 flex items-center">
          {isLoading ? (
            <button
              type="button"
              onClick={onCancel}
              title="Stop generation (Esc)"
              className="flex items-center justify-center w-8 h-8 rounded-lg bg-[#181C25] hover:bg-red-500/20 border border-red-500/30 hover:border-red-500/50 text-red-400 transition-colors shadow-sm cursor-pointer"
            >
              <Square className="w-3.5 h-3.5 fill-current" />
            </button>
          ) : (
            <button
              type="button"
              onClick={onSend}
              disabled={!hasContent || disabled}
              title="Send message (Enter)"
              className="flex items-center justify-center w-8 h-8 rounded-lg bg-[#8B5CF6] hover:bg-[#7C3AED] disabled:bg-[#181C25] text-white disabled:text-[#71717A] transition-colors shadow-sm disabled:cursor-not-allowed cursor-pointer shadow-[0_0_16px_-4px_rgba(139,92,246,0.5)] disabled:shadow-none"
            >
              <Send className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Helper Footer Subtext */}
      <div className="hidden sm:flex items-center justify-between px-3 pb-2 pt-0.5 text-[10px] text-[#71717A] select-none">
        <span>
          <kbd className="px-1 py-0.5 rounded bg-[#181C25] border border-[#272B36] text-[#A1A1AA] font-mono text-[9px]">Enter</kbd> to send, <kbd className="px-1 py-0.5 rounded bg-[#181C25] border border-[#272B36] text-[#A1A1AA] font-mono text-[9px]">Shift + Enter</kbd> for new line
        </span>
        <span>
          <kbd className="px-1 py-0.5 rounded bg-[#181C25] border border-[#272B36] text-[#A1A1AA] font-mono text-[9px]">↑</kbd> edit previous
        </span>
      </div>
    </div>
  );
}


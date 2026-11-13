"use client";

import React, { useState } from "react";
import { Copy, Check, Code2 } from "lucide-react";

interface UserMessageProps {
  content: string;
}

interface Segment {
  type: "text" | "code";
  content: string;
  language?: string;
}

/**
 * Detect whether an unfenced block of text is raw programming code or an error stack trace.
 */
function isRawCodeBlock(text: string): boolean {
  const trimmed = text.trim();
  const lines = trimmed.split("\n");

  // Single line inputs are not code blocks unless explicit assignment or function definition
  if (lines.length === 1) {
    return /^(const|let|var|function|def|import|public\s+class|class|SELECT|curl|npm|git)\s/i.test(trimmed);
  }

  // Common code syntax heuristics
  const codeIndicators = [
    /\b(function|const|let|var|def|class|import|from|export|return|async|await|public|private|protected|void|int|float|double|char|bool|boolean|struct|enum|interface|type)\b/,
    /\b(if|else|for|while|switch|case|break|continue|try|catch|finally|throw|raise|yield)\s*[\(\{:]/,
    /^\s*(console\.log|print|System\.out|printf|std::cout)\s*\(/m,
    /^\s*(\{|\}|<[a-zA-Z]|<\/[a-zA-Z])/m,
    /[;{}][\s\n]*$/,
    /Traceback \(most recent call last\):/i,
    /NullPointerException|TypeError|ReferenceError|SyntaxError|IndexError|ValueError/,
    /^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\s+[A-Z0-9_*]/im,
    /=>/,
    /^\s*(#include|#define|package\s+|namespace\s+)/m,
  ];

  const matchCount = codeIndicators.filter((regex) => regex.test(trimmed)).length;
  const hasIndentedLines = lines.some((l) => /^[ \t]{2,}/.test(l));

  return (
    (matchCount >= 2 && hasIndentedLines) ||
    matchCount >= 3 ||
    /^\s*(function|def|class|public\s+class)\b/m.test(trimmed) ||
    /Traceback \(most recent call last\):/i.test(trimmed)
  );
}

/**
 * Split user input into text and code segments.
 * Supports:
 * 1. Markdown fenced blocks: ```lang ... ```
 * 2. Unfenced raw code (e.g. JavaScript, Python, C++, SQL, Stack Traces)
 * 3. Plain conversational text
 */
function parseUserContent(content: string): Segment[] {
  // 1. Check for fenced code blocks
  if (content.includes("```")) {
    const segments: Segment[] = [];
    const fenceRegex = /```([a-zA-Z0-9_-]*)\n?([\s\S]*?)```/g;
    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = fenceRegex.exec(content)) !== null) {
      if (match.index > lastIndex) {
        const textPart = content.slice(lastIndex, match.index);
        if (textPart.trim()) {
          segments.push({ type: "text", content: textPart });
        }
      }
      segments.push({
        type: "code",
        language: match[1] || "code",
        content: match[2],
      });
      lastIndex = match.index + match[0].length;
    }

    if (lastIndex < content.length) {
      const remaining = content.slice(lastIndex);
      if (remaining.trim()) {
        segments.push({ type: "text", content: remaining });
      }
    }

    if (segments.length > 0) return segments;
  }

  // 2. Check if the entire message is raw code
  if (isRawCodeBlock(content)) {
    return [{ type: "code", content, language: "code" }];
  }

  // 3. Plain conversational text
  return [{ type: "text", content }];
}

function UserCodeBlock({ code, language }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard fallback
    }
  };

  return (
    <div className="relative group my-2 rounded-lg bg-[#080A10]/90 border border-white/[0.12] overflow-hidden shadow-inner text-left">
      <div className="flex items-center justify-between px-3 py-1.5 bg-[#111319]/90 border-b border-white/[0.08] text-[10px] text-[#A1A1AA] select-none">
        <span className="font-mono font-medium uppercase tracking-wider text-[#A78BFA] flex items-center gap-1.5">
          <Code2 className="w-3 h-3 text-[#A78BFA]" />
          {language && language !== "code" ? language : "Code"}
        </span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 px-1.5 py-0.5 rounded hover:bg-white/[0.08] text-[#A1A1AA] hover:text-[#F4F4F5] transition-colors"
          title="Copy code"
        >
          {copied ? (
            <>
              <Check className="w-3 h-3 text-emerald-400" />
              <span className="text-[10px] text-emerald-400">Copied</span>
            </>
          ) : (
            <>
              <Copy className="w-3 h-3" />
              <span className="text-[10px]">Copy</span>
            </>
          )}
        </button>
      </div>
      <div className="p-3 overflow-x-auto max-w-full">
        <pre className="!bg-transparent !p-0 !m-0 font-mono text-[11px] leading-relaxed text-[#F4F4F5] whitespace-pre">
          <code>{code}</code>
        </pre>
      </div>
    </div>
  );
}

export function UserMessage({ content }: UserMessageProps) {
  const segments = parseUserContent(content);

  // If single pure text segment, render simple text paragraph
  if (segments.length === 1 && segments[0].type === "text") {
    return <p className="whitespace-pre-wrap break-words">{content}</p>;
  }

  // If mixed or code segment, render structured blocks
  return (
    <div className="space-y-1.5 text-left">
      {segments.map((seg, idx) => {
        if (seg.type === "code") {
          return <UserCodeBlock key={idx} code={seg.content} language={seg.language} />;
        }
        return (
          <p key={idx} className="whitespace-pre-wrap break-words">
            {seg.content}
          </p>
        );
      })}
    </div>
  );
}


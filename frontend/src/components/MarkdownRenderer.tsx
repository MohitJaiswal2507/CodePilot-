"use client";

import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { Check, Copy } from "lucide-react";

interface MarkdownRendererProps {
  content: string;
}

function CodeBlockHeader({
  language,
  rawCode,
}: {
  language: string;
  rawCode: string;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(rawCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access denied fallback
    }
  };

  return (
    <div className="flex items-center justify-between px-3.5 py-1.5 bg-[#0e1320] border-b border-slate-800 text-[11px] text-slate-400 select-none">
      <span className="font-mono text-xs text-indigo-400 font-semibold tracking-wide uppercase">
        {language || "code"}
      </span>
      <button
        onClick={handleCopy}
        className="flex items-center gap-1.5 px-2 py-0.5 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
        title="Copy code to clipboard"
      >
        {copied ? (
          <>
            <Check className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-[10px] text-emerald-400 font-medium">Copied!</span>
          </>
        ) : (
          <>
            <Copy className="w-3.5 h-3.5" />
            <span className="text-[10px]">Copy</span>
          </>
        )}
      </button>
    </div>
  );
}

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  return (
    <div className="prose prose-invert max-w-none text-xs leading-relaxed text-slate-200 space-y-3">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          h1: ({ children }) => (
            <h1 className="text-base font-bold text-white mt-4 mb-2 first:mt-0 tracking-tight">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-sm font-bold text-white mt-3.5 mb-2 first:mt-0 tracking-tight">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-xs font-semibold text-indigo-300 mt-3 mb-1.5 first:mt-0 uppercase tracking-wider">
              {children}
            </h3>
          ),
          p: ({ children }) => (
            <p className="mb-2.5 last:mb-0 leading-relaxed text-slate-200">
              {children}
            </p>
          ),
          ul: ({ children }) => (
            <ul className="list-disc pl-5 mb-2.5 space-y-1 text-slate-200">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal pl-5 mb-2.5 space-y-1 text-slate-200">
              {children}
            </ol>
          ),
          li: ({ children }) => (
            <li className="leading-relaxed pl-1">{children}</li>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-white">{children}</strong>
          ),
          em: ({ children }) => (
            <em className="italic text-slate-300">{children}</em>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-indigo-500 pl-3 py-1 my-2 bg-indigo-950/20 text-slate-300 italic rounded-r text-xs">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto my-3 rounded-lg border border-slate-800">
              <table className="w-full text-left text-xs border-collapse">
                {children}
              </table>
            </div>
          ),
          th: ({ children }) => (
            <th className="bg-slate-900 p-2 border-b border-slate-800 font-semibold text-white">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="p-2 border-b border-slate-800/60 text-slate-300">
              {children}
            </td>
          ),
          pre: ({ children }) => {
            // Unpack language and code from pre > code structure
            return <div className="my-3 rounded-lg overflow-hidden border border-slate-800 bg-[#070a12] shadow-sm">{children}</div>;
          },
          code: ({ className, children, ...props }) => {
            const isInline = !className && typeof children === "string" && !children.includes("\n");
            if (isInline) {
              return (
                <code
                  className="px-1.5 py-0.5 rounded bg-slate-800 text-indigo-300 font-mono text-[11px] border border-slate-700/60 font-medium"
                  {...props}
                >
                  {children}
                </code>
              );
            }

            // Extract language (e.g. "language-javascript hljs" -> "javascript")
            const match = /language-([a-zA-Z0-9_-]+)/.exec(className || "");
            const language = match ? match[1] : "";
            const rawCode = String(children).replace(/\n$/, "");

            return (
              <div>
                <CodeBlockHeader language={language} rawCode={rawCode} />
                <div className="p-3.5 overflow-x-auto text-xs font-mono leading-relaxed">
                  <pre className="!bg-transparent !p-0 !m-0 whitespace-pre">
                    <code className={className} {...props}>
                      {children}
                    </code>
                  </pre>
                </div>
              </div>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}


import React from "react";
import Link from "next/link";
import { ArrowLeft, Compass } from "lucide-react";

export default function NotFound() {
  return (
    <div className="relative min-h-screen w-full bg-[#080A10] flex items-center justify-center p-4 overflow-hidden">
      <div className="w-full max-w-md relative z-10 text-center">
        {/* Card */}
        <div className="bg-[#111319] border border-[#272B36] rounded-xl p-8 shadow-lg shadow-black/40 space-y-6">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-xl bg-[#181C25] border border-[#272B36] text-[#3B82F6]">
            <Compass className="w-7 h-7 text-[#3B82F6]" />
          </div>

          <div className="space-y-2">
            <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-[11px] font-mono font-medium bg-[#3B82F6]/10 text-[#93C5FD] border border-[#3B82F6]/30">
              <span>Error 404</span>
            </div>
            <h1 className="text-2xl font-bold text-[#F4F4F5] tracking-tight">
              Page Not Found
            </h1>
            <p className="text-xs text-[#A1A1AA] max-w-sm mx-auto leading-relaxed">
              The page or resource you are looking for does not exist, has been removed, or is temporarily unavailable.
            </p>
          </div>

          <div className="pt-2">
            <Link
              href="/"
              className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg bg-[#3B82F6] hover:bg-[#2563EB] text-white font-medium text-xs transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3B82F6]"
            >
              <ArrowLeft className="w-4 h-4" />
              <span>Return to Workspace</span>
            </Link>
          </div>
        </div>

        {/* Footer info */}
        <p className="text-center text-[11px] text-[#71717A] mt-6">
          CodePilot AI Platform
        </p>
      </div>
    </div>
  );
}

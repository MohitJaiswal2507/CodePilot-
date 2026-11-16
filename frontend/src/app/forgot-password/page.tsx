"use client";

import React, { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { authClient } from "@/lib/auth/client";
import { Mail, ArrowLeft, ArrowRight, Loader2, AlertCircle, CheckCircle2 } from "lucide-react";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isSubmitted, setIsSubmitted] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    const trimmedEmail = email.trim();
    if (!trimmedEmail) {
      setErrorMessage("Please enter your registered email address.");
      return;
    }

    setIsLoading(true);
    try {
      // Better Auth forgetPassword endpoint
      const clientAny = authClient as unknown as Record<string, (args: Record<string, unknown>) => Promise<unknown>>;
      if (typeof clientAny.forgetPassword === "function") {
        await clientAny.forgetPassword({
          email: trimmedEmail,
          redirectTo: `${typeof window !== "undefined" ? window.location.origin : ""}/login`,
        });
      }
      setIsSubmitted(true);
      setIsLoading(false);
    } catch (err: unknown) {
      // Even if error or user not found, typical security practice is to show standard confirmation
      const msg = err instanceof Error ? err.message : "Failed to process password reset request.";
      setErrorMessage(msg);
      setIsLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen w-full bg-[#080A10] flex items-center justify-center p-4 overflow-hidden">
      <div className="w-full max-w-md relative z-10">
        {/* Brand & Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-[#181C25] border border-white/[0.1] mb-4 shadow-lg shadow-black/40 p-2">
            <Image src="/codepilot-icon.svg" alt="CodePilot logo" width={32} height={32} priority className="w-full h-full object-contain" />
          </div>
          <h1 className="text-2xl font-bold text-[#F4F4F5] tracking-tight">Reset password</h1>
          <p className="text-xs text-[#A1A1AA] mt-1.5">Enter your email to receive recovery instructions</p>
        </div>

        {/* Card */}
        <div className="bg-[#111319] border border-[#272B36] rounded-xl p-7 shadow-lg shadow-black/40">
          {errorMessage && (
            <div
              role="alert"
              className="mb-5 p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/25 flex items-start gap-3 text-rose-300 text-xs animate-in fade-in"
            >
              <AlertCircle className="w-4 h-4 shrink-0 text-rose-400 mt-0.5" />
              <span>{errorMessage}</span>
            </div>
          )}

          {isSubmitted ? (
            <div className="space-y-5 text-center py-2">
              <div className="w-12 h-12 rounded-2xl bg-emerald-500/10 border border-emerald-500/25 text-emerald-400 flex items-center justify-center mx-auto shadow-md shadow-emerald-950/30">
                <CheckCircle2 className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-[#F4F4F5]">Check your email</h3>
                <p className="text-xs text-[#A1A1AA] mt-1.5 leading-relaxed">
                  If an account exists for <span className="text-[#F4F4F5] font-medium">{email}</span>, we have sent instructions to reset your password.
                </p>
              </div>
              <Link
                href="/login"
                className="w-full py-2.5 px-4 rounded-xl bg-[#181C25] hover:bg-[#202533] text-[#F4F4F5] font-medium text-xs inline-flex items-center justify-center gap-2 transition-colors border border-white/[0.08] hover:border-white/[0.16] shadow-sm"
              >
                <ArrowLeft className="w-4 h-4" />
                <span>Return to sign in</span>
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label
                  htmlFor="forgot-email"
                  className="block text-xs font-medium text-[#F4F4F5] mb-1.5"
                >
                  Registered Email Address
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-[#71717A]">
                    <Mail className="w-4 h-4" />
                  </div>
                  <input
                    id="forgot-email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="developer@example.com"
                    autoComplete="email"
                    required
                    className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-[#080A10] border border-white/[0.08] text-xs text-[#F4F4F5] placeholder-[#71717A] focus:outline-none focus:border-[#3B82F6] focus:ring-1 focus:ring-[#3B82F6]/50 transition-colors"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="w-full mt-2 py-2.5 px-4 rounded-xl bg-[#3B82F6] hover:bg-[#2563EB] disabled:bg-[#3B82F6]/50 text-white font-medium text-xs flex items-center justify-center gap-2 transition-all shadow-md shadow-blue-900/30 disabled:cursor-not-allowed cursor-pointer"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Sending instructions...</span>
                  </>
                ) : (
                  <>
                    <span>Send Reset Instructions</span>
                    <ArrowRight className="w-4 h-4" />
                  </>
                )}
              </button>

              <div className="pt-2 text-center">
                <Link
                  href="/login"
                  className="text-xs text-[#A1A1AA] hover:text-[#F4F4F5] inline-flex items-center gap-1.5 transition-colors"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  <span>Back to sign in</span>
                </Link>
              </div>
            </form>
          )}
        </div>

        {/* Footer info */}
        <p className="text-center text-[11px] text-[#71717A] mt-6">
          Powered by Neon Auth &amp; PostgreSQL
        </p>
      </div>
    </div>
  );
}

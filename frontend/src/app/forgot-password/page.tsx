"use client";

import React, { useState } from "react";
import Link from "next/link";
import { authClient } from "@/lib/auth/client";
import { Cpu, Mail, ArrowLeft, ArrowRight, Loader2, AlertCircle, CheckCircle2 } from "lucide-react";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isSubmitted, setIsSubmitted] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    if (!email.trim()) {
      setErrorMessage("Please enter your registered email address.");
      return;
    }

    setIsLoading(true);
    try {
      // Better Auth forgetPassword endpoint
      const clientAny = authClient as unknown as Record<string, (args: any) => Promise<any>>;
      if (typeof clientAny.forgetPassword === "function") {
        await clientAny.forgetPassword({
          email: email.trim(),
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
    <div className="min-h-screen w-full bg-[#090d16] flex items-center justify-center p-4">
      {/* Background radial gradient */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-950/20 via-transparent to-transparent pointer-events-none" />

      <div className="w-full max-w-md relative z-10">
        {/* Logo & Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-indigo-600/20 border border-indigo-500/30 text-indigo-400 mb-4 shadow-lg shadow-indigo-950/40">
            <Cpu className="w-6 h-6" />
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Reset password</h1>
          <p className="text-xs text-slate-400 mt-1.5">Enter your email to receive recovery instructions</p>
        </div>

        {/* Card */}
        <div className="bg-[#0d121f] border border-slate-800/80 rounded-2xl p-7 shadow-2xl backdrop-blur-sm">
          {errorMessage && (
            <div className="mb-5 p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-start gap-3 text-rose-300 text-xs animate-in fade-in">
              <AlertCircle className="w-4 h-4 shrink-0 text-rose-400 mt-0.5" />
              <span>{errorMessage}</span>
            </div>
          )}

          {isSubmitted ? (
            <div className="space-y-5 text-center py-2">
              <div className="w-12 h-12 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center mx-auto">
                <CheckCircle2 className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white">Check your email</h3>
                <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                  If an account exists for <span className="text-slate-200 font-medium">{email}</span>, we have sent instructions to reset your password.
                </p>
              </div>
              <Link
                href="/login"
                className="w-full py-2.5 px-4 rounded-lg bg-slate-800 hover:bg-slate-700 text-white font-medium text-xs inline-flex items-center justify-center gap-2 transition-colors border border-slate-700"
              >
                <ArrowLeft className="w-4 h-4" />
                <span>Return to sign in</span>
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">
                  Registered Email Address
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500">
                    <Mail className="w-4 h-4" />
                  </div>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="developer@example.com"
                    autoComplete="email"
                    required
                    className="w-full pl-10 pr-4 py-2.5 rounded-lg bg-[#090d16] border border-slate-800 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500/80 focus:ring-1 focus:ring-indigo-500/50 transition-colors"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="w-full mt-2 py-2.5 px-4 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-600/50 text-white font-medium text-xs flex items-center justify-center gap-2 transition-colors shadow-lg shadow-indigo-600/20 disabled:cursor-not-allowed cursor-pointer"
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
                  className="text-xs text-slate-400 hover:text-slate-300 inline-flex items-center gap-1.5 transition-colors"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  <span>Back to sign in</span>
                </Link>
              </div>
            </form>
          )}
        </div>

        {/* Footer info */}
        <p className="text-center text-[11px] text-slate-400 mt-6">
          Powered by Neon Auth & PostgreSQL
        </p>
      </div>
    </div>
  );
}

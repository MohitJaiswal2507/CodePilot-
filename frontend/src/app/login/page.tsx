"use client";

import React, { useState, Suspense } from "react";
import Image from "next/image";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { authClient } from "@/lib/auth/client";
import { setApiAuthToken } from "@/services/api";
import { Lock, Mail, ArrowRight, Loader2, AlertCircle, Eye, EyeOff } from "lucide-react";

function LoginForm() {
  const searchParams = useSearchParams();
  const callbackUrl = searchParams.get("callbackUrl") || "/";

  // Sanitize destination to avoid open redirects
  const destination = callbackUrl.startsWith("/") && !callbackUrl.startsWith("//") ? callbackUrl : "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isLoading) return; // Prevent duplicate submissions

    setErrorMessage(null);

    const trimmedEmail = email.trim();
    if (!trimmedEmail || !password) {
      setErrorMessage("Please enter both your email address and password.");
      return;
    }

    setIsLoading(true);

    try {
      const res = await authClient.signIn.email({
        email: trimmedEmail,
        password,
      });

      if (res?.error) {
        const errorDetail = res.error.message || "Invalid email or password. Please verify your credentials.";
        setErrorMessage(errorDetail);
        return;
      }

      // Check session to cache active token for FastAPI
      try {
        const sessionRes = await authClient.getSession();
        if (sessionRes?.data?.session?.token) {
          setApiAuthToken(sessionRes.data.session.token);
        }
      } catch (sessErr) {
        console.debug("Session priming:", sessErr);
      }

      // Perform clean full-page navigation so newly set cookies are transmitted to the server
      window.location.href = destination;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "An unexpected authentication error occurred.";
      setErrorMessage(msg);
    } finally {
      // Always reset loading state so the button never stays permanently disabled
      setIsLoading(false);
    }
  };

  return (
    <div className="w-full max-w-md relative z-10">
      {/* Brand & Header */}
      <div className="text-center mb-8">
        <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-[#181C25] border border-white/[0.1] mb-4 shadow-lg shadow-black/40 p-2">
          <Image src="/codepilot-icon.svg" alt="CodePilot logo" width={32} height={32} priority className="w-full h-full object-contain" />
        </div>
        <h1 className="text-2xl font-bold text-[#F4F4F5] tracking-tight">Welcome back</h1>
        <p className="text-xs text-[#A1A1AA] mt-1.5">Sign in to your CodePilot AI workspace</p>
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

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="login-email"
              className="block text-xs font-medium text-[#F4F4F5] mb-1.5"
            >
              Email address
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-[#71717A]">
                <Mail className="w-4 h-4" />
              </div>
              <input
                id="login-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="developer@example.com"
                autoComplete="email"
                disabled={isLoading}
                required
                className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-[#080A10] border border-white/[0.08] text-xs text-[#F4F4F5] placeholder-[#71717A] focus:outline-none focus:border-[#3B82F6] focus:ring-1 focus:ring-[#3B82F6]/50 transition-colors disabled:opacity-60"
              />
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label
                htmlFor="login-password"
                className="block text-xs font-medium text-[#F4F4F5]"
              >
                Password
              </label>
              <Link
                href="/forgot-password"
                className="text-[11px] text-[#3B82F6] hover:text-[#60A5FA] transition-colors"
              >
                Forgot password?
              </Link>
            </div>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-[#71717A]">
                <Lock className="w-4 h-4" />
              </div>
              <input
                id="login-password"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                autoComplete="current-password"
                disabled={isLoading}
                required
                className="w-full pl-10 pr-10 py-2.5 rounded-xl bg-[#080A10] border border-white/[0.08] text-xs text-[#F4F4F5] placeholder-[#71717A] focus:outline-none focus:border-[#3B82F6] focus:ring-1 focus:ring-[#3B82F6]/50 transition-colors disabled:opacity-60"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                disabled={isLoading}
                aria-label={showPassword ? "Hide password" : "Show password"}
                className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-[#71717A] hover:text-[#F4F4F5] transition-colors disabled:opacity-60 cursor-pointer"
              >
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
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
                <span>Signing in...</span>
              </>
            ) : (
              <>
                <span>Sign In</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </form>

        <div className="mt-6 pt-5 border-t border-white/[0.08] text-center">
          <p className="text-xs text-[#A1A1AA]">
            Don&apos;t have an account?{" "}
            <Link
              href="/register"
              className="font-medium text-[#3B82F6] hover:text-[#60A5FA] transition-colors"
            >
              Create one now
            </Link>
          </p>
        </div>
      </div>

      {/* Footer info */}
      <p className="text-center text-[11px] text-[#71717A] mt-6">
        Powered by Neon Auth &amp; PostgreSQL
      </p>
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="relative min-h-screen w-full bg-[#080A10] flex items-center justify-center p-4 overflow-hidden">
      <Suspense
        fallback={
          <div className="relative z-10 flex items-center justify-center p-12 text-[#A1A1AA] text-xs gap-2">
            <Loader2 className="w-4 h-4 animate-spin text-[#3B82F6]" />
            <span>Loading...</span>
          </div>
        }
      >
        <LoginForm />
      </Suspense>
    </div>
  );
}

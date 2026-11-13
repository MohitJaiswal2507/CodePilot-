"use client";

import React, { useState } from "react";
import Link from "next/link";
import { authClient } from "@/lib/auth/client";
import { setApiAuthToken } from "@/services/api";
import { Cpu, Lock, Mail, User, ArrowRight, Loader2, AlertCircle, CheckCircle2, Eye, EyeOff } from "lucide-react";

export default function RegisterPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isLoading) return;

    setErrorMessage(null);
    setSuccessMessage(null);

    const trimmedName = name.trim();
    const trimmedEmail = email.trim();

    if (!trimmedName) {
      setErrorMessage("Please enter your full name.");
      return;
    }

    if (!trimmedEmail) {
      setErrorMessage("Please enter a valid email address.");
      return;
    }

    if (password.length < 8) {
      setErrorMessage("Password must be at least 8 characters long.");
      return;
    }

    if (password !== confirmPassword) {
      setErrorMessage("Passwords do not match. Please re-enter.");
      return;
    }

    setIsLoading(true);

    try {
      const res = await authClient.signUp.email({
        email: trimmedEmail,
        password,
        name: trimmedName,
      });

      if (res?.error) {
        setErrorMessage(res.error.message || "Failed to create account. Please try again.");
        return;
      }

      setSuccessMessage("Account created successfully! Redirecting to workspace...");

      // Cache token if active session returned
      try {
        const sessionRes = await authClient.getSession();
        if (sessionRes?.data?.session?.token) {
          setApiAuthToken(sessionRes.data.session.token);
        }
      } catch (sessErr) {
        console.debug("Session priming:", sessErr);
      }

      setTimeout(() => {
        window.location.href = "/";
      }, 800);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "An unexpected error occurred during account creation.";
      setErrorMessage(msg);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen w-full bg-[#080A10] flex items-center justify-center p-4 overflow-hidden">
      <div className="w-full max-w-md relative z-10 my-8">
        {/* Brand & Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-[#181C25] border border-white/[0.1] text-[#3B82F6] mb-4 shadow-lg shadow-black/40">
            <Cpu className="w-6 h-6 text-[#3B82F6]" />
          </div>
          <h1 className="text-2xl font-bold text-[#F4F4F5] tracking-tight">Create your account</h1>
          <p className="text-xs text-[#A1A1AA] mt-1.5">Get started with AI-driven development and learning</p>
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

          {successMessage && (
            <div
              role="status"
              className="mb-5 p-3.5 rounded-xl bg-emerald-500/10 border border-emerald-500/25 flex items-start gap-3 text-emerald-300 text-xs animate-in fade-in"
            >
              <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400 mt-0.5" />
              <span>{successMessage}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="register-name"
                className="block text-xs font-medium text-[#F4F4F5] mb-1.5"
              >
                Full Name
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-[#71717A]">
                  <User className="w-4 h-4" />
                </div>
                <input
                  id="register-name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Mohit Jaiswal"
                  autoComplete="name"
                  disabled={isLoading}
                  required
                  className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-[#080A10] border border-white/[0.08] text-xs text-[#F4F4F5] placeholder-[#71717A] focus:outline-none focus:border-[#3B82F6] focus:ring-1 focus:ring-[#3B82F6]/50 transition-colors disabled:opacity-60"
                />
              </div>
            </div>

            <div>
              <label
                htmlFor="register-email"
                className="block text-xs font-medium text-[#F4F4F5] mb-1.5"
              >
                Email address
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-[#71717A]">
                  <Mail className="w-4 h-4" />
                </div>
                <input
                  id="register-email"
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
              <label
                htmlFor="register-password"
                className="block text-xs font-medium text-[#F4F4F5] mb-1.5"
              >
                Password <span className="text-[#71717A] font-normal">(min. 8 characters)</span>
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-[#71717A]">
                  <Lock className="w-4 h-4" />
                </div>
                <input
                  id="register-password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  autoComplete="new-password"
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

            <div>
              <label
                htmlFor="register-confirm-password"
                className="block text-xs font-medium text-[#F4F4F5] mb-1.5"
              >
                Confirm Password
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-[#71717A]">
                  <Lock className="w-4 h-4" />
                </div>
                <input
                  id="register-confirm-password"
                  type={showPassword ? "text" : "password"}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="••••••••••••"
                  autoComplete="new-password"
                  disabled={isLoading}
                  required
                  className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-[#080A10] border border-white/[0.08] text-xs text-[#F4F4F5] placeholder-[#71717A] focus:outline-none focus:border-[#3B82F6] focus:ring-1 focus:ring-[#3B82F6]/50 transition-colors disabled:opacity-60"
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
                  <span>Creating account...</span>
                </>
              ) : (
                <>
                  <span>Create Account</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>

          <div className="mt-6 pt-5 border-t border-white/[0.08] text-center">
            <p className="text-xs text-[#A1A1AA]">
              Already have an account?{" "}
              <Link
                href="/login"
                className="font-medium text-[#3B82F6] hover:text-[#60A5FA] transition-colors"
              >
                Sign in
              </Link>
            </p>
          </div>
        </div>

        {/* Footer info */}
        <p className="text-center text-[11px] text-[#71717A] mt-6">
          Powered by Neon Auth &amp; PostgreSQL
        </p>
      </div>
    </div>
  );
}

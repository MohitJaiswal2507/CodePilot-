"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Check,
  Code2,
  Cpu,
  Download,
  Info,
  Laptop,
  Loader2,
  LogOut,
  Monitor,
  Palette,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  User,
} from "lucide-react";
import { authClient } from "@/lib/auth/client";
import { performSignOut } from "@/lib/auth/signOut";
import {
  DEFAULT_EDITOR_SETTINGS,
  EditorSettings,
  getEditorSettings,
  resetEditorSettings,
  saveEditorSettings,
} from "@/lib/editorSettings";
import { LANGUAGE_LABELS, SupportedLanguage } from "@/lib/sandbox";
import {
  HealthStatus,
  ModelInfo,
  fetchAvailableModels,
  fetchBackendHealth,
} from "@/services/api";
import {
  checkLocalRuntimeHealth,
  getLocalRuntimeStatus,
  getLocalRuntimeToken,
  LocalRuntimeHealth,
  LocalRuntimeStatus,
} from "@/services/localRuntime";
import { RuntimeInstallWizard } from "./RuntimeInstallWizard";

type SettingsSection = "account" | "appearance" | "editor" | "ai" | "runtime" | "about";

const MODEL_STORAGE_KEY = "codepilot_gemini_model";
const FONT_SIZE_OPTIONS = [12, 13, 14, 15, 16, 18];
const LANGUAGES: SupportedLanguage[] = ["python", "java", "cpp"];

const SECTIONS: {
  id: SettingsSection;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}[] = [
  { id: "account", label: "Account", description: "Authenticated session", icon: User },
  { id: "appearance", label: "Appearance", description: "Workspace theme", icon: Palette },
  { id: "editor", label: "Code Editor", description: "Monaco & language defaults", icon: Code2 },
  { id: "runtime", label: "Local Runtime", description: "Docker execution daemon", icon: Laptop },
  { id: "ai", label: "AI Preferences", description: "Default Gemini model", icon: Sparkles },
  { id: "about", label: "About", description: "Version & backend health", icon: Info },
];

const TECH_STACK = [
  { label: "Frontend", value: "Next.js 15, React 19, TypeScript, Tailwind CSS" },
  { label: "Code Editor", value: "Monaco Editor (@monaco-editor/react)" },
  { label: "Backend", value: "FastAPI, Python, SQLAlchemy" },
  { label: "AI & RAG", value: "Google Gemini, LangGraph, ChromaDB" },
  { label: "Auth & Database", value: "Neon Auth (Better Auth) & PostgreSQL" },
  { label: "Execution", value: "Isolated Docker Sandbox (Python, Java, C++)" },
];

export function Settings() {
  const router = useRouter();
  const [activeSection, setActiveSection] = useState<SettingsSection>("account");
  const [isSigningOut, setIsSigningOut] = useState(false);

  // Code Editor state
  const [editorSettings, setEditorSettings] = useState<EditorSettings>(() => getEditorSettings());
  const [editorSavedNotice, setEditorSavedNotice] = useState(false);

  // AI Preferences state
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [defaultModelFromApi, setDefaultModelFromApi] = useState<string>("");
  const [selectedModel, setSelectedModel] = useState<string>(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem(MODEL_STORAGE_KEY) || "";
    }
    return "";
  });
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [modelSavedNotice, setModelSavedNotice] = useState(false);

  // About / Backend health state
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [isLoadingHealth, setIsLoadingHealth] = useState(false);

  // Local Runtime state
  const [runtimeHealth, setRuntimeHealth] = useState<LocalRuntimeHealth | null>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<LocalRuntimeStatus | null>(null);
  const [isLoadingRuntime, setIsLoadingRuntime] = useState(false);
  const [showRuntimeWizard, setShowRuntimeWizard] = useState(false);

  const loadRuntime = useCallback(async () => {
    setIsLoadingRuntime(true);
    const h = await checkLocalRuntimeHealth(2500);
    setRuntimeHealth(h);
    if (h?.status === "ok") {
      const s = await getLocalRuntimeStatus(3000);
      setRuntimeStatus(s);
    } else {
      setRuntimeStatus(null);
    }
    setIsLoadingRuntime(false);
  }, []);

  const sessionHook =
    typeof authClient?.useSession === "function"
      ? authClient.useSession()
      : { data: null, isPending: false };
  const user = sessionHook?.data?.user;
  const isSessionPending = sessionHook?.isPending;

  const loadModels = useCallback(async (refresh = false) => {
    setIsLoadingModels(true);
    setModelsError(null);
    try {
      const data = await fetchAvailableModels(refresh);
      setModels(data.models || []);
      setDefaultModelFromApi(data.default_model || "");

      const saved =
        typeof window !== "undefined" ? localStorage.getItem(MODEL_STORAGE_KEY) : null;
      if (saved && data.models.some((m) => m.id === saved)) {
        setSelectedModel(saved);
      } else if (data.default_model) {
        setSelectedModel(data.default_model);
      } else if (data.models.length > 0) {
        setSelectedModel(data.models[0].id);
      }
    } catch (err: unknown) {
      setModelsError(
        err instanceof Error
          ? err.message
          : "Unable to load available Gemini models from backend."
      );
    } finally {
      setIsLoadingModels(false);
    }
  }, []);

  const loadHealth = useCallback(async () => {
    setIsLoadingHealth(true);
    try {
      const status = await fetchBackendHealth();
      setHealth(status);
    } finally {
      setIsLoadingHealth(false);
    }
  }, []);

  useEffect(() => {
    loadModels(false);
    loadHealth();
    loadRuntime();
  }, [loadModels, loadHealth, loadRuntime]);

  const handleSignOut = async () => {
    setIsSigningOut(true);
    try {
      await performSignOut(router);
    } catch (err) {
      console.error("Sign out failed:", err);
      setIsSigningOut(false);
    }
  };

  const updateEditorSetting = <K extends keyof EditorSettings>(
    key: K,
    value: EditorSettings[K]
  ) => {
    const next = { ...editorSettings, [key]: value };
    setEditorSettings(next);
    saveEditorSettings(next);
    setEditorSavedNotice(true);
    setTimeout(() => setEditorSavedNotice(false), 1800);
  };

  const handleResetEditorSettings = () => {
    const reset = resetEditorSettings();
    setEditorSettings(reset);
    setEditorSavedNotice(true);
    setTimeout(() => setEditorSavedNotice(false), 1800);
  };

  const handleSelectDefaultModel = (modelId: string) => {
    setSelectedModel(modelId);
    if (typeof window !== "undefined") {
      localStorage.setItem(MODEL_STORAGE_KEY, modelId);
    }
    setModelSavedNotice(true);
    setTimeout(() => setModelSavedNotice(false), 1800);
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Workspace Header & Title Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 p-5 rounded-xl border border-[#272B36] bg-[#111319]">
        <div className="flex items-center gap-3.5">
          <div className="p-2.5 rounded-lg bg-[#181C25] border border-[#272B36] text-[#3B82F6] shrink-0">
            <Palette className="w-5 h-5" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-base font-bold text-white tracking-tight">
                Workspace Settings
              </h1>
              <span className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-md bg-[#181C25] text-[#A1A1AA] border border-[#272B36]">
                Configuration
              </span>
            </div>
            <p className="text-xs text-zinc-400 mt-0.5">
              Manage user session, editor preferences, default Gemini model, and runtime diagnostics.
            </p>
          </div>
        </div>
      </div>

      {/* Mobile/Tablet Horizontal Tabs */}
      <div className="flex md:hidden items-center gap-1.5 p-1 rounded-xl bg-[#111319] border border-[#272B36] overflow-x-auto">
        {SECTIONS.map((section) => {
          const Icon = section.icon;
          const isActive = activeSection === section.id;
          return (
            <button
              key={section.id}
              type="button"
              onClick={() => setActiveSection(section.id)}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium whitespace-nowrap transition-all cursor-pointer ${
                isActive
                  ? "bg-[#3B82F6] text-white shadow-sm shadow-blue-900/40"
                  : "text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.04]"
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{section.label}</span>
            </button>
          );
        })}
      </div>

      {/* Main Settings Grid */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
        {/* Desktop Settings Section Sidebar */}
        <aside className="hidden md:block md:col-span-4 lg:col-span-3">
          <div className="rounded-xl border border-[#272B36] bg-[#111319] p-2 space-y-1">
            {SECTIONS.map((section) => {
              const Icon = section.icon;
              const isActive = activeSection === section.id;
              return (
                <button
                  key={section.id}
                  type="button"
                  onClick={() => setActiveSection(section.id)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-all cursor-pointer ${
                    isActive
                      ? "bg-[#3B82F6]/10 text-[#F4F4F5] border border-[#3B82F6]/30 shadow-sm"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.04] border border-transparent"
                  }`}
                >
                  <Icon
                    className={`w-4 h-4 shrink-0 ${
                      isActive ? "text-[#3B82F6]" : "text-zinc-400"
                    }`}
                  />
                  <div className="min-w-0">
                    <p className="text-xs font-medium truncate">{section.label}</p>
                    <p className="text-[10px] text-zinc-500 truncate">{section.description}</p>
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

        {/* Settings Content Panel */}
        <section className="md:col-span-8 lg:col-span-9 space-y-6">
          {/* 1. Account */}
          {activeSection === "account" && (
            <div className="rounded-xl border border-[#272B36] bg-[#111319] p-6 space-y-6">
              <div>
                <h2 className="text-sm font-semibold text-white">Account Details</h2>
                <p className="text-xs text-zinc-400 mt-1">
                  Your current authenticated user profile and session identity.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="p-4 rounded-xl bg-[#181C25] border border-white/[0.08]">
                  <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">
                    Full Name
                  </p>
                  <p className="text-xs font-medium text-zinc-200 mt-1.5">
                    {isSessionPending ? "Loading..." : user?.name || "Not provided"}
                  </p>
                </div>

                <div className="p-4 rounded-xl bg-[#181C25] border border-white/[0.08]">
                  <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">
                    Email Address
                  </p>
                  <p className="text-xs font-medium text-zinc-200 mt-1.5 break-all">
                    {isSessionPending ? "Loading..." : user?.email || "Not available"}
                  </p>
                </div>
              </div>

              <div className="pt-4 border-t border-white/[0.08] flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <p className="text-xs text-zinc-400">
                  Sign out to terminate your current session and clear local authentication tokens.
                </p>
                <button
                  type="button"
                  onClick={handleSignOut}
                  disabled={isSigningOut}
                  className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 text-xs font-medium transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
                >
                  {isSigningOut ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <LogOut className="w-3.5 h-3.5" />
                  )}
                  <span>{isSigningOut ? "Signing out..." : "Sign Out"}</span>
                </button>
              </div>
            </div>
          )}

          {/* 2. Appearance */}
          {activeSection === "appearance" && (
            <div className="rounded-xl border border-[#272B36] bg-[#111319] p-6 space-y-5">
              <div>
                <h2 className="text-sm font-semibold text-white">Appearance &amp; Theme</h2>
                <p className="text-xs text-zinc-400 mt-1">
                  Interface theme configuration across the CodePilot AI platform.
                </p>
              </div>

              <div className="p-4 rounded-xl bg-[#181C25] border border-white/[0.08] flex items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-lg bg-[#111319] border border-[#272B36] text-[#3B82F6]">
                    <Monitor className="w-4 h-4" />
                  </div>
                  <div>
                    <p className="text-xs font-medium text-white">Engineered Precision Theme</p>
                    <p className="text-[11px] text-zinc-400 mt-0.5">
                      Midnight background (#080A10) with elevated surfaces, monochromatic blue backlighting, and high-contrast code legibility.
                    </p>
                  </div>
                </div>
                <span className="px-2.5 py-1 rounded-full text-[11px] font-medium bg-emerald-500/10 text-emerald-300 border border-emerald-500/25 shrink-0">
                  Active
                </span>
              </div>

              <p className="text-[11px] text-zinc-500">
                Dark mode is enforced to ensure high-contrast readability across Monaco syntax tokens, AST diagnostics, and terminal stdout streams.
              </p>
            </div>
          )}

          {/* 3. Code Editor */}
          {activeSection === "editor" && (
            <div className="rounded-xl border border-[#272B36] bg-[#111319] p-6 space-y-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-white">Code Editor Preferences</h2>
                  <p className="text-xs text-zinc-400 mt-1">
                    Preferences are saved locally and applied to both Code Reviewer and Code Execution Sandbox.
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  {editorSavedNotice && (
                    <span className="inline-flex items-center gap-1 text-[11px] text-emerald-300 bg-emerald-500/10 border border-emerald-500/25 px-2.5 py-1 rounded-full">
                      <Check className="w-3 h-3" />
                      Saved
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={handleResetEditorSettings}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#181C25] hover:bg-[#202533] border border-white/[0.08] hover:border-white/[0.16] text-xs text-zinc-300 hover:text-white transition-colors cursor-pointer"
                  >
                    <RotateCcw className="w-3.5 h-3.5 text-zinc-400" />
                    <span>Reset Defaults</span>
                  </button>
                </div>
              </div>

              <div className="rounded-xl border border-white/[0.08] bg-[#181C25] divide-y divide-white/[0.06] overflow-hidden">
                {/* Default Language */}
                <div className="p-4 space-y-2.5">
                  <label className="block text-xs font-medium text-zinc-200">
                    Default Programming Language
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {LANGUAGES.map((lang) => (
                      <button
                        key={lang}
                        type="button"
                        onClick={() => updateEditorSetting("defaultLanguage", lang)}
                        className={`px-3.5 py-1.5 rounded-lg text-xs font-medium border transition-all cursor-pointer ${
                          editorSettings.defaultLanguage === lang
                            ? "bg-[#3B82F6] text-white border-[#3B82F6] shadow-sm shadow-blue-900/40"
                            : "bg-[#080A10] text-zinc-300 border-white/[0.08] hover:border-white/[0.16]"
                        }`}
                      >
                        {LANGUAGE_LABELS[lang]}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Font Size & Tab Size */}
                <div className="p-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <label
                      htmlFor="editor-font-size"
                      className="block text-xs font-medium text-zinc-200"
                    >
                      Editor Font Size
                    </label>
                    <select
                      id="editor-font-size"
                      value={editorSettings.fontSize}
                      onChange={(e) =>
                        updateEditorSetting("fontSize", Number(e.target.value))
                      }
                      className="w-full px-3 py-2 rounded-lg bg-[#080A10] border border-white/[0.08] text-xs text-zinc-200 focus:outline-none focus:border-[#3B82F6]"
                    >
                      {FONT_SIZE_OPTIONS.map((size) => (
                        <option key={size} value={size}>
                          {size}px{size === DEFAULT_EDITOR_SETTINGS.fontSize ? " (Default)" : ""}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="space-y-2">
                    <label className="block text-xs font-medium text-zinc-200">
                      Indentation Tab Size
                    </label>
                    <div className="flex gap-2">
                      {([2, 4] as const).map((spaces) => (
                        <button
                          key={spaces}
                          type="button"
                          onClick={() => updateEditorSetting("tabSize", spaces)}
                          className={`flex-1 py-2 rounded-lg text-xs font-medium border transition-all cursor-pointer ${
                            editorSettings.tabSize === spaces
                              ? "bg-[#3B82F6] text-white border-[#3B82F6] shadow-sm shadow-blue-900/40"
                              : "bg-[#080A10] text-zinc-300 border-white/[0.08] hover:border-white/[0.16]"
                          }`}
                        >
                          {spaces} Spaces
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Word Wrap & Minimap Switches */}
                <div className="p-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="flex items-center justify-between gap-3 p-3 rounded-lg bg-[#080A10]/60 border border-white/[0.04]">
                    <div>
                      <p className="text-xs font-medium text-zinc-200">Word Wrap</p>
                      <p className="text-[11px] text-zinc-400">
                        Wrap long lines inside editor
                      </p>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={editorSettings.wordWrap === "on"}
                      onClick={() =>
                        updateEditorSetting(
                          "wordWrap",
                          editorSettings.wordWrap === "on" ? "off" : "on"
                        )
                      }
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all cursor-pointer ${
                        editorSettings.wordWrap === "on"
                          ? "bg-[#3B82F6]/15 text-[#60A5FA] border-[#3B82F6]/30"
                          : "bg-[#080A10] text-zinc-400 border-white/[0.08]"
                      }`}
                    >
                      {editorSettings.wordWrap === "on" ? "On" : "Off"}
                    </button>
                  </div>

                  <div className="flex items-center justify-between gap-3 p-3 rounded-lg bg-[#080A10]/60 border border-white/[0.04]">
                    <div>
                      <p className="text-xs font-medium text-zinc-200">Minimap</p>
                      <p className="text-[11px] text-zinc-400">
                        Code overview minimap
                      </p>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={editorSettings.minimap}
                      onClick={() =>
                        updateEditorSetting("minimap", !editorSettings.minimap)
                      }
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all cursor-pointer ${
                        editorSettings.minimap
                          ? "bg-[#3B82F6]/15 text-[#60A5FA] border-[#3B82F6]/30"
                          : "bg-[#080A10] text-zinc-400 border-white/[0.08]"
                      }`}
                    >
                      {editorSettings.minimap ? "Enabled" : "Disabled"}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Local Runtime Settings */}
          {activeSection === "runtime" && (
            <div className="rounded-xl border border-[#272B36] bg-[#111319] p-6 space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-white">CodePilot Local Runtime</h2>
                  <p className="text-xs text-zinc-400 mt-1">
                    Execute code inside Docker on your personal machine with zero cloud runner dependency.
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={loadRuntime}
                    disabled={isLoadingRuntime}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[#181C25] hover:bg-[#202533] border border-white/[0.08] hover:border-white/[0.16] text-xs text-zinc-300 hover:text-white disabled:opacity-50 transition-colors cursor-pointer"
                  >
                    <RefreshCw
                      className={`w-3.5 h-3.5 text-zinc-400 ${isLoadingRuntime ? "animate-spin" : ""}`}
                    />
                    <span>Refresh</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowRuntimeWizard(true)}
                    className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-medium text-xs shadow-md shadow-blue-900/30 transition-all cursor-pointer"
                  >
                    <Laptop className="w-3.5 h-3.5" />
                    <span>Open Setup Wizard</span>
                  </button>
                </div>
              </div>

              {/* Status Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="p-4 rounded-xl bg-[#181C25] border border-white/[0.08] space-y-1">
                  <p className="text-[10px] uppercase font-bold text-zinc-500">Daemon Service</p>
                  <p className="text-sm font-bold text-white flex items-center gap-2">
                    <span
                      className={`w-2 h-2 rounded-full ${
                        runtimeHealth?.status === "ok" ? "bg-emerald-400" : "bg-rose-400"
                      }`}
                    />
                    {runtimeHealth?.status === "ok" ? "Running (Port 8088)" : "Offline"}
                  </p>
                  <p className="text-[11px] text-zinc-400">
                    {runtimeHealth?.latencyMs !== undefined
                      ? `${runtimeHealth.latencyMs} ms latency`
                      : "Daemon not running locally"}
                  </p>
                </div>

                <div className="p-4 rounded-xl bg-[#181C25] border border-white/[0.08] space-y-1">
                  <p className="text-[10px] uppercase font-bold text-zinc-500">Docker Engine</p>
                  <p className="text-sm font-bold text-white flex items-center gap-2">
                    <span
                      className={`w-2 h-2 rounded-full ${
                        runtimeHealth?.docker_available ? "bg-emerald-400" : "bg-rose-400"
                      }`}
                    />
                    {runtimeHealth?.docker_available
                      ? `Ready (${runtimeHealth.docker_version})`
                      : "Daemon Stopped / Missing"}
                  </p>
                  <p className="text-[11px] text-zinc-400">
                    {runtimeHealth?.docker_available
                      ? "Isolated sandbox execution enabled"
                      : "Start Docker Desktop"}
                  </p>
                </div>

                <div className="p-4 rounded-xl bg-[#181C25] border border-white/[0.08] space-y-1">
                  <p className="text-[10px] uppercase font-bold text-zinc-500">Browser Pairing</p>
                  <p className="text-sm font-bold text-white flex items-center gap-2">
                    <ShieldCheck
                      className={`w-4 h-4 ${
                        runtimeHealth?.status === "ok" && getLocalRuntimeToken()
                          ? "text-emerald-400"
                          : "text-zinc-500"
                      }`}
                    />
                    {runtimeHealth?.status === "ok" && getLocalRuntimeToken()
                      ? "Paired & Authenticated"
                      : "Unpaired"}
                  </p>
                  <p className="text-[11px] text-zinc-400">RFC 1918 Private Network Access</p>
                </div>
              </div>

              {/* Language Environments */}
              <div className="space-y-3 pt-2">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                  Language Environments
                </h3>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {[
                    { lang: "Python 3.12", tag: "python:3.12-slim" },
                    { lang: "Java 21", tag: "eclipse-temurin:21-jdk" },
                    { lang: "C++ (GCC 14)", tag: "gcc:14" },
                  ].map(({ lang, tag }) => {
                    const isInstalled = runtimeStatus?.languages?.images?.[tag]?.installed ?? true;
                    return (
                      <div
                        key={tag}
                        className="p-3.5 rounded-xl bg-[#181C25] border border-white/[0.08] flex items-center justify-between"
                      >
                        <div>
                          <p className="text-xs font-medium text-white">{lang}</p>
                          <p className="text-[10px] font-mono text-zinc-500 mt-0.5">{tag}</p>
                        </div>
                        <span
                          className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
                            isInstalled
                              ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/30"
                              : "bg-amber-500/10 text-amber-300 border-amber-500/30"
                          }`}
                        >
                          {isInstalled ? "Installed" : "Missing"}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Download Desktop Installer */}
              <div className="space-y-3 pt-2">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                  Desktop Installers
                </h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <a
                    href="/downloads/codepilot-runtime-setup-win-x64.exe"
                    download
                    className="p-3.5 rounded-xl border border-blue-500/30 bg-blue-500/10 hover:bg-blue-500/20 transition-all flex items-center justify-between cursor-pointer"
                  >
                    <div>
                      <p className="text-xs font-bold text-white flex items-center gap-1.5">
                        <Download className="w-4 h-4 text-blue-400" />
                        Windows Installer (.exe)
                      </p>
                      <p className="text-[11px] text-zinc-400 mt-1">
                        Automated setup wizard (~29.8 MB)
                      </p>
                    </div>
                    <span className="text-xs font-semibold text-blue-400">Download</span>
                  </a>

                  <a
                    href="/downloads/codepilot-runtime-portable-win-x64.zip"
                    download
                    className="p-3.5 rounded-xl border border-[#272B36] bg-[#181C25] hover:bg-[#202533] transition-all flex items-center justify-between cursor-pointer"
                  >
                    <div>
                      <p className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                        <Download className="w-4 h-4 text-zinc-400" />
                        Portable Archive (.zip)
                      </p>
                      <p className="text-[11px] text-zinc-400 mt-1">
                        No install required (~21.3 MB)
                      </p>
                    </div>
                    <span className="text-xs font-semibold text-zinc-400">Download</span>
                  </a>
                </div>
              </div>
            </div>
          )}

          {/* 4. AI Preferences */}
          {activeSection === "ai" && (
            <div className="rounded-xl border border-[#272B36] bg-[#111319] p-6 space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-white">AI Model Preferences</h2>
                  <p className="text-xs text-zinc-400 mt-1">
                    Choose the default Gemini model used across the AI Learning Tutor and code analysis workflows.
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  {modelSavedNotice && (
                    <span className="inline-flex items-center gap-1 text-[11px] text-emerald-300 bg-emerald-500/10 border border-emerald-500/25 px-2.5 py-1 rounded-full">
                      <Check className="w-3 h-3" />
                      Saved
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => loadModels(true)}
                    disabled={isLoadingModels}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[#181C25] hover:bg-[#202533] border border-white/[0.08] hover:border-white/[0.16] text-xs text-zinc-300 hover:text-white disabled:opacity-50 transition-colors cursor-pointer"
                  >
                    <RefreshCw
                      className={`w-3.5 h-3.5 text-zinc-400 ${isLoadingModels ? "animate-spin" : ""}`}
                    />
                    <span>Refresh Models</span>
                  </button>
                </div>
              </div>

              {modelsError && (
                <div className="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/25 text-xs text-rose-300">
                  {modelsError}
                </div>
              )}

              {isLoadingModels && models.length === 0 ? (
                <div className="py-8 flex items-center justify-center gap-2 text-xs text-zinc-400">
                  <Loader2 className="w-4 h-4 animate-spin text-[#3B82F6]" />
                  <span>Loading available models...</span>
                </div>
              ) : models.length > 0 ? (
                <div className="space-y-2.5">
                  {models.map((model) => {
                    const isSelected = selectedModel === model.id;
                    const isBackendDefault = model.id === defaultModelFromApi || model.is_default;
                    return (
                      <button
                        key={model.id}
                        type="button"
                        onClick={() => handleSelectDefaultModel(model.id)}
                        className={`w-full text-left p-3.5 rounded-lg border transition-all cursor-pointer flex items-start justify-between gap-3 ${
                          isSelected
                            ? "bg-[#3B82F6]/10 border-[#3B82F6]/40 shadow-sm shadow-blue-950/30"
                            : "bg-[#181C25] border-white/[0.08] hover:border-white/[0.16]"
                        }`}
                      >
                        <div className="space-y-1 min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-xs font-semibold text-white">
                              {model.display_name || model.id}
                            </span>
                            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-md bg-[#080A10] text-zinc-300 border border-white/[0.08]">
                              {model.category}
                            </span>
                            {isBackendDefault && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded-md bg-[#3B82F6]/15 text-[#60A5FA] border border-[#3B82F6]/30 font-medium">
                                Server Default
                              </span>
                            )}
                          </div>
                          {model.description && (
                            <p className="text-[11px] text-zinc-400 leading-relaxed">
                              {model.description}
                            </p>
                          )}
                          <p className="text-[10px] font-mono text-zinc-500">{model.id}</p>
                        </div>

                        <div
                          className={`w-5 h-5 rounded-full border flex items-center justify-center shrink-0 mt-0.5 ${
                            isSelected
                              ? "bg-[#3B82F6] border-[#3B82F6] text-white shadow-sm shadow-blue-900/40"
                              : "border-zinc-700 bg-[#080A10]"
                          }`}
                        >
                          {isSelected && <Check className="w-3 h-3" />}
                        </div>
                      </button>
                    );
                  })}
                </div>
              ) : (
                !modelsError && (
                  <p className="text-xs text-zinc-400">
                    No models returned by the backend.
                  </p>
                )
              )}
            </div>
          )}

          {/* 5. About */}
          {activeSection === "about" && (
            <div className="rounded-xl border border-[#272B36] bg-[#111319] p-6 space-y-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-lg bg-[#181C25] border border-[#272B36] text-[#3B82F6]">
                    <Cpu className="w-5 h-5" />
                  </div>
                  <div>
                    <h2 className="text-sm font-semibold text-white">CodePilot AI</h2>
                    <p className="text-xs text-zinc-400">
                      Frontend v0.1.0
                      {health?.version && health.version !== "unknown"
                        ? ` • Backend v${health.version}`
                        : ""}
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={loadHealth}
                  disabled={isLoadingHealth}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[#181C25] hover:bg-[#202533] border border-white/[0.08] hover:border-white/[0.16] text-xs text-zinc-300 hover:text-white disabled:opacity-50 transition-colors cursor-pointer"
                >
                  <RefreshCw
                    className={`w-3.5 h-3.5 text-zinc-400 ${isLoadingHealth ? "animate-spin" : ""}`}
                  />
                  <span>Check Health</span>
                </button>
              </div>

              {/* Live Backend Health */}
              <div className="p-4 rounded-xl bg-[#181C25] border border-white/[0.08] space-y-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-zinc-200">
                    Backend Service Status
                  </span>
                  {health ? (
                    <span
                      className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${
                        health.status === "healthy"
                          ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/30"
                          : health.status === "unhealthy"
                          ? "bg-amber-500/10 text-amber-300 border-amber-500/30"
                          : "bg-rose-500/10 text-rose-300 border-rose-500/30"
                      }`}
                    >
                      {health.status}
                    </span>
                  ) : (
                    <span className="text-[11px] text-zinc-400">Checking...</span>
                  )}
                </div>

                {health && (
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-[11px]">
                    <div>
                      <p className="text-zinc-500">Service</p>
                      <p className="font-mono text-zinc-200 mt-0.5">{health.service}</p>
                    </div>
                    <div>
                      <p className="text-zinc-500">Version</p>
                      <p className="font-mono text-zinc-200 mt-0.5">{health.version}</p>
                    </div>
                    <div>
                      <p className="text-zinc-500">Environment</p>
                      <p className="font-mono text-zinc-200 mt-0.5">{health.environment}</p>
                    </div>
                    <div>
                      <p className="text-zinc-500">Latency</p>
                      <p className="font-mono text-cyan-400 font-semibold mt-0.5">
                        {health.latencyMs !== undefined ? `${health.latencyMs} ms` : "—"}
                      </p>
                    </div>
                  </div>
                )}

                {health?.error && (
                  <p className="text-[11px] text-rose-300">{health.error}</p>
                )}
              </div>

              {/* Technology Stack */}
              <div className="space-y-2.5">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                  Verified Technology Stack
                </h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {TECH_STACK.map((item) => (
                    <div
                      key={item.label}
                      className="p-3 rounded-xl bg-[#181C25] border border-white/[0.08]"
                    >
                      <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-500">
                        {item.label}
                      </p>
                      <p className="text-xs text-zinc-200 mt-1">{item.value}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </section>
      </div>

      <RuntimeInstallWizard
        isOpen={showRuntimeWizard}
        onClose={() => {
          setShowRuntimeWizard(false);
          loadRuntime();
        }}
      />
    </div>
  );
}

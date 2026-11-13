"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  Code2,
  FileText,
  MessageSquare,
  RefreshCw,
  Terminal,
} from "lucide-react";
import { authClient } from "@/lib/auth/client";
import { AppTab } from "@/lib/navigation";
import {
  CodeReviewHistoryItem,
  ConversationSummary,
  DocumentSummary,
  HealthStatus,
  fetchBackendHealth,
  fetchCodeReviewHistory,
  fetchConversations,
  fetchDocuments,
} from "@/services/api";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  SectionHeader,
  Skeleton,
  SkeletonCard,
} from "@/components/ui";

interface DashboardOverviewProps {
  onNavigate: (tab: AppTab) => void;
}

interface AsyncSlice<T> {
  data: T;
  loading: boolean;
  error: string | null;
}

interface ActivityEntry {
  id: string;
  type: "conversation" | "document" | "review";
  title: string;
  meta: string;
  timestamp: string;
  targetTab: AppTab;
  conversationId?: string;
}

function formatRelativeTime(isoDate: string): string {
  const date = new Date(isoDate);
  if (Number.isNaN(date.getTime())) return "Unknown";

  const diffSeconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (diffSeconds < 60) return "Just now";
  if (diffSeconds < 3600) return `${Math.floor(diffSeconds / 60)}m ago`;
  if (diffSeconds < 86400) return `${Math.floor(diffSeconds / 3600)}h ago`;
  if (diffSeconds < 604800) return `${Math.floor(diffSeconds / 86400)}d ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function DashboardOverview({ onNavigate }: DashboardOverviewProps) {
  const sessionHook =
    typeof authClient?.useSession === "function"
      ? authClient.useSession()
      : { data: null, isPending: false };
  const userName = sessionHook?.data?.user?.name?.trim() || "";
  const firstName = userName ? userName.split(/\s+/)[0] : "";

  // Client-only formatted date to avoid SSR hydration mismatch
  const [formattedDate, setFormattedDate] = useState<string>("");

  const [healthState, setHealthState] = useState<AsyncSlice<HealthStatus | null>>({
    data: null,
    loading: true,
    error: null,
  });
  const [conversationsState, setConversationsState] = useState<
    AsyncSlice<{ items: ConversationSummary[]; total: number }>
  >({
    data: { items: [], total: 0 },
    loading: true,
    error: null,
  });
  const [documentsState, setDocumentsState] = useState<
    AsyncSlice<{ items: DocumentSummary[]; total: number }>
  >({
    data: { items: [], total: 0 },
    loading: true,
    error: null,
  });
  const [reviewsState, setReviewsState] = useState<
    AsyncSlice<{ items: CodeReviewHistoryItem[]; total: number }>
  >({
    data: { items: [], total: 0 },
    loading: true,
    error: null,
  });

  const loadDashboardData = useCallback(async () => {
    setHealthState((prev) => ({ ...prev, loading: true, error: null }));
    setConversationsState((prev) => ({ ...prev, loading: true, error: null }));
    setDocumentsState((prev) => ({ ...prev, loading: true, error: null }));
    setReviewsState((prev) => ({ ...prev, loading: true, error: null }));

    const [healthRes, convRes, docRes, revRes] = await Promise.allSettled([
      fetchBackendHealth(),
      fetchConversations(10, 0),
      fetchDocuments(),
      fetchCodeReviewHistory(10, 0),
    ]);

    if (healthRes.status === "fulfilled") {
      setHealthState({ data: healthRes.value, loading: false, error: null });
    } else {
      setHealthState({
        data: null,
        loading: false,
        error: "Unable to check backend health.",
      });
    }

    if (convRes.status === "fulfilled") {
      setConversationsState({
        data: {
          items: convRes.value.conversations || [],
          total: convRes.value.total ?? (convRes.value.conversations?.length || 0),
        },
        loading: false,
        error: null,
      });
    } else {
      setConversationsState({
        data: { items: [], total: 0 },
        loading: false,
        error:
          convRes.reason instanceof Error
            ? convRes.reason.message
            : "Failed to load conversations.",
      });
    }

    if (docRes.status === "fulfilled") {
      setDocumentsState({
        data: {
          items: docRes.value.documents || [],
          total: docRes.value.total_documents ?? (docRes.value.documents?.length || 0),
        },
        loading: false,
        error: null,
      });
    } else {
      setDocumentsState({
        data: { items: [], total: 0 },
        loading: false,
        error:
          docRes.reason instanceof Error
            ? docRes.reason.message
            : "Failed to load uploaded documents.",
      });
    }

    if (revRes.status === "fulfilled") {
      setReviewsState({
        data: {
          items: revRes.value.reviews || [],
          total: revRes.value.total ?? (revRes.value.reviews?.length || 0),
        },
        loading: false,
        error: null,
      });
    } else {
      setReviewsState({
        data: { items: [], total: 0 },
        loading: false,
        error:
          revRes.reason instanceof Error
            ? revRes.reason.message
            : "Failed to load code review history.",
      });
    }
  }, []);

  useEffect(() => {
    setFormattedDate(
      new Date().toLocaleDateString(undefined, {
        weekday: "long",
        month: "short",
        day: "numeric",
      })
    );
    loadDashboardData();
  }, [loadDashboardData]);

  const handleOpenConversation = (conversationId: string) => {
    if (typeof window !== "undefined") {
      localStorage.setItem("codepilot_active_conv_id", conversationId);
    }
    onNavigate("ai-tutor");
  };

  const recentActivity = useMemo<ActivityEntry[]>(() => {
    const entries: ActivityEntry[] = [];

    for (const conv of conversationsState.data.items) {
      entries.push({
        id: `conv-${conv.id}`,
        type: "conversation",
        title: conv.title || "Untitled conversation",
        meta: `${conv.message_count} ${conv.message_count === 1 ? "message" : "messages"}`,
        timestamp: conv.updated_at,
        targetTab: "ai-tutor",
        conversationId: conv.id,
      });
    }

    for (const doc of documentsState.data.items) {
      entries.push({
        id: `doc-${doc.document_name}`,
        type: "document",
        title: doc.document_name,
        meta: `${doc.total_pages} ${doc.total_pages === 1 ? "page" : "pages"} • ${doc.total_chunks} chunks`,
        timestamp: doc.uploaded_at,
        targetTab: "ai-tutor",
      });
    }

    for (const rev of reviewsState.data.items) {
      entries.push({
        id: `rev-${rev.id}`,
        type: "review",
        title: `${rev.language.toUpperCase()} Review (${rev.quality_score}/10)`,
        meta: rev.summary || rev.code_snippet,
        timestamp: rev.created_at,
        targetTab: "code-review",
      });
    }

    return entries
      .sort(
        (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
      )
      .slice(0, 6);
  }, [
    conversationsState.data.items,
    documentsState.data.items,
    reviewsState.data.items,
  ]);

  const isAnyLoading =
    healthState.loading ||
    conversationsState.loading ||
    documentsState.loading ||
    reviewsState.loading;

  const firstError =
    conversationsState.error || documentsState.error || reviewsState.error;

  const quickActions: {
    tab: AppTab;
    title: string;
    description: string;
    cta: string;
    icon: React.ComponentType<{ className?: string }>;
  }[] = [
    {
      tab: "ai-tutor",
      title: "AI Learning Tutor",
      description:
        "Ask curriculum-grounded questions and explore explanations cited from your uploaded PDFs.",
      cta: "Open AI Tutor",
      icon: BookOpen,
    },
    {
      tab: "code-review",
      title: "Code Reviewer",
      description:
        "Run multi-stage static analysis, Big-O complexity derivation, and edge-case checks.",
      cta: "Review Code",
      icon: Code2,
    },
    {
      tab: "sandbox",
      title: "Code Sandbox",
      description:
        "Compile and execute Python, Java, and C++ programs inside an isolated Docker container.",
      cta: "Open Sandbox",
      icon: Terminal,
    },
  ];

  const healthBadgeVariant =
    healthState.data?.status === "healthy"
      ? "success"
      : healthState.data?.status === "unhealthy"
      ? "warning"
      : "danger";

  return (
    <div className="space-y-8">
      {/* A. Welcome Header */}
      <section className="rounded-xl border border-[#272B36] bg-[#111319] p-6 sm:p-7">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div className="space-y-1">
            <h1 className="text-xl sm:text-2xl font-semibold text-[#FAFAFA] tracking-tight">
              {firstName ? `Welcome back, ${firstName}` : "Welcome back"}
            </h1>
            <p className="text-xs sm:text-sm text-[#A1A1AA] max-w-2xl leading-relaxed">
              Study from course materials, review code with AI diagnostics, and test solutions in an isolated sandbox.
            </p>
          </div>

          <div className="flex items-center gap-3">
            {formattedDate && (
              <span className="text-xs text-[#71717A] hidden md:inline">
                {formattedDate}
              </span>
            )}
            <Button
              variant="secondary"
              size="sm"
              onClick={loadDashboardData}
              isLoading={isAnyLoading}
              leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
              className="self-start sm:self-auto"
            >
              Refresh
            </Button>
          </div>
        </div>
      </section>

      {/* B. Quick Actions */}
      <section
        className="space-y-3 animate-cp-fade-up"
        style={{ animationDelay: "50ms" }}
      >
        <SectionHeader
          title="Quick Actions"
          description="Jump directly into a workspace tool."
        />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {quickActions.map((action) => {
            const Icon = action.icon;
            return (
              <Card
                key={action.tab}
                interactive
                padding="lg"
                className="flex flex-col justify-between gap-5 bg-[#111319] hover:bg-[#151821] border-[#272B36] hover:border-[#373D4D]"
              >
                <div className="space-y-3.5">
                  <div className="w-9 h-9 rounded-md bg-[#181C25] border border-[#272B36] flex items-center justify-center text-[#3B82F6]">
                    <Icon className="w-4 h-4" aria-hidden="true" />
                  </div>
                  <div className="space-y-1">
                    <h3 className="text-sm font-semibold text-[#FAFAFA]">
                      {action.title}
                    </h3>
                    <p className="text-xs text-[#A1A1AA] leading-relaxed">
                      {action.description}
                    </p>
                  </div>
                </div>

                <div>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => onNavigate(action.tab)}
                    rightIcon={<ArrowRight className="w-3.5 h-3.5" />}
                    className="w-full justify-between"
                  >
                    {action.cta}
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      </section>

      {/* C. Overview Metrics */}
      <section
        className="space-y-3 animate-cp-fade-up"
        style={{ animationDelay: "100ms" }}
      >
        <SectionHeader
          title="Workspace Overview"
          description="Live counts retrieved from your account and backend service."
        />

        {firstError && (
          <ErrorState
            title="Some workspace metrics could not be loaded"
            message={firstError}
            onRetry={loadDashboardData}
          />
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Metric 1: Conversations */}
          {conversationsState.loading ? (
            <SkeletonCard />
          ) : (
            <Card elevated interactive padding="md" className="space-y-3">
              <div className="flex items-center justify-between text-xs text-[#A1A1AA]">
                <span>Conversations</span>
                <div className="w-7 h-7 rounded-md bg-[#181C25] border border-[#272B36] flex items-center justify-center text-[#71717A]">
                  <MessageSquare className="w-3.5 h-3.5" aria-hidden="true" />
                </div>
              </div>
              <p className="text-3xl font-semibold text-[#FAFAFA] tabular-nums tracking-tight">
                {conversationsState.error ? "—" : conversationsState.data.total}
              </p>
              <p className="text-[11px] text-[#71717A]">
                {conversationsState.error
                  ? "Unavailable"
                  : conversationsState.data.total === 0
                  ? "No chats started yet"
                  : "Persisted AI Tutor threads"}
              </p>
            </Card>
          )}

          {/* Metric 2: Uploaded Documents */}
          {documentsState.loading ? (
            <SkeletonCard />
          ) : (
            <Card elevated interactive padding="md" className="space-y-3">
              <div className="flex items-center justify-between text-xs text-[#A1A1AA]">
                <span>Uploaded PDFs</span>
                <div className="w-7 h-7 rounded-md bg-[#181C25] border border-[#272B36] flex items-center justify-center text-[#71717A]">
                  <FileText className="w-3.5 h-3.5" aria-hidden="true" />
                </div>
              </div>
              <p className="text-3xl font-semibold text-[#FAFAFA] tabular-nums tracking-tight">
                {documentsState.error ? "—" : documentsState.data.total}
              </p>
              <p className="text-[11px] text-[#71717A]">
                {documentsState.error
                  ? "Unavailable"
                  : documentsState.data.total === 0
                  ? "Upload a PDF in AI Tutor"
                  : "Indexed in vector store"}
              </p>
            </Card>
          )}

          {/* Metric 3: Code Reviews */}
          {reviewsState.loading ? (
            <SkeletonCard />
          ) : (
            <Card elevated interactive padding="md" className="space-y-3">
              <div className="flex items-center justify-between text-xs text-[#A1A1AA]">
                <span>Code Reviews</span>
                <div className="w-7 h-7 rounded-md bg-[#181C25] border border-[#272B36] flex items-center justify-center text-[#71717A]">
                  <Code2 className="w-3.5 h-3.5" aria-hidden="true" />
                </div>
              </div>
              <p className="text-3xl font-semibold text-[#FAFAFA] tabular-nums tracking-tight">
                {reviewsState.error ? "—" : reviewsState.data.total}
              </p>
              <p className="text-[11px] text-[#71717A]">
                {reviewsState.error
                  ? "Unavailable"
                  : reviewsState.data.total === 0
                  ? "No reviews submitted yet"
                  : "Completed AI analyses"}
              </p>
            </Card>
          )}

          {/* Metric 4: Backend Connection */}
          {healthState.loading ? (
            <SkeletonCard />
          ) : (
            <Card elevated interactive padding="md" className="space-y-3">
              <div className="flex items-center justify-between text-xs text-[#A1A1AA]">
                <span>Backend Service</span>
                <Badge variant={healthBadgeVariant} size="sm" dot>
                  {healthState.data?.status ?? "offline"}
                </Badge>
              </div>
              <p className="text-3xl font-semibold text-[#FAFAFA] tabular-nums tracking-tight">
                {healthState.data?.latencyMs !== undefined
                  ? `${healthState.data.latencyMs} ms`
                  : "—"}
              </p>
              <p className="text-[11px] text-[#71717A] truncate">
                {healthState.data?.status === "healthy"
                  ? `FastAPI v${healthState.data.version}`
                  : healthState.data?.error || "Backend unreachable"}
              </p>
            </Card>
          )}
        </div>
      </section>

      {/* D & E. Recent Activity & Recent Conversations */}
      <section
        className="grid grid-cols-1 lg:grid-cols-12 gap-6 animate-cp-fade-up"
        style={{ animationDelay: "150ms" }}
      >
        {/* E. Recent Conversations */}
        <div className="lg:col-span-6 space-y-3">
          <SectionHeader
            title="Recent Conversations"
            description="Reopen a saved AI Tutor thread."
            actions={
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onNavigate("ai-tutor")}
                rightIcon={<ArrowRight className="w-3 h-3" />}
              >
                View all
              </Button>
            }
          />

          <Card padding="none" className="overflow-hidden bg-[#111319] border-[#272B36]">
            {conversationsState.loading ? (
              <div className="p-4 space-y-3">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : conversationsState.error ? (
              <div className="p-4">
                <ErrorState
                  message={conversationsState.error}
                  onRetry={loadDashboardData}
                />
              </div>
            ) : conversationsState.data.items.length === 0 ? (
              <EmptyState
                icon={<MessageSquare className="w-4 h-4" />}
                title="No conversations yet"
                description="Start a curriculum-grounded Q&A session in the AI Learning Tutor."
                action={
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => onNavigate("ai-tutor")}
                  >
                    Start a Conversation
                  </Button>
                }
                className="border-0 rounded-none bg-transparent"
              />
            ) : (
              <ul className="divide-y divide-[#272B36]">
                {conversationsState.data.items.slice(0, 5).map((conv) => (
                  <li key={conv.id}>
                    <button
                      type="button"
                      onClick={() => handleOpenConversation(conv.id)}
                      className="w-full px-4 py-3.5 flex items-center justify-between gap-3 text-left hover:bg-[#181C25] transition-colors duration-150 motion-reduce:transition-none cursor-pointer focus-visible:outline-none focus-visible:bg-[#181C25]"
                    >
                      <div className="min-w-0 space-y-1">
                        <p className="text-xs font-medium text-[#FAFAFA] truncate">
                          {conv.title || "Untitled conversation"}
                        </p>
                        <div className="flex flex-wrap items-center gap-2 text-[11px] text-[#71717A]">
                          <span>
                            {conv.message_count}{" "}
                            {conv.message_count === 1 ? "message" : "messages"}
                          </span>
                          {conv.document_filter && (
                            <Badge variant="ai" size="sm">
                              {conv.document_filter}
                            </Badge>
                          )}
                        </div>
                      </div>
                      <span className="text-[11px] text-[#71717A] tabular-nums shrink-0">
                        {formatRelativeTime(conv.updated_at)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        {/* D. Recent Activity */}
        <div className="lg:col-span-6 space-y-3">
          <SectionHeader
            title="Recent Activity"
            description="Latest conversations, uploaded PDFs, and code reviews."
          />

          <Card padding="none" className="overflow-hidden bg-[#111319] border-[#272B36]">
            {conversationsState.loading &&
            documentsState.loading &&
            reviewsState.loading ? (
              <div className="p-4 space-y-3">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : recentActivity.length === 0 ? (
              <EmptyState
                icon={<Code2 className="w-4 h-4" />}
                title="No recent activity"
                description="Your uploaded PDFs, AI Tutor threads, and code reviews will appear here."
                action={
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => onNavigate("code-review")}
                  >
                    Submit a Code Review
                  </Button>
                }
                className="border-0 rounded-none bg-transparent"
              />
            ) : (
              <ul className="divide-y divide-[#272B36]">
                {recentActivity.map((item) => {
                  const badgeLabel =
                    item.type === "conversation"
                      ? "Chat"
                      : item.type === "document"
                      ? "PDF"
                      : "Review";
                  const badgeVariant =
                    item.type === "conversation"
                      ? "ai"
                      : item.type === "document"
                      ? "neutral"
                      : "cyan";

                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        onClick={() => {
                          if (item.conversationId) {
                            handleOpenConversation(item.conversationId);
                          } else {
                            onNavigate(item.targetTab);
                          }
                        }}
                        className="w-full px-4 py-3.5 flex items-center justify-between gap-3 text-left hover:bg-[#181C25] transition-colors duration-150 motion-reduce:transition-none cursor-pointer focus-visible:outline-none focus-visible:bg-[#181C25]"
                      >
                        <div className="min-w-0 space-y-1">
                          <div className="flex items-center gap-2 min-w-0">
                            <Badge variant={badgeVariant} size="sm">
                              {badgeLabel}
                            </Badge>
                            <p className="text-xs font-medium text-[#FAFAFA] truncate">
                              {item.title}
                            </p>
                          </div>
                          <p className="text-[11px] text-[#71717A] truncate">
                            {item.meta}
                          </p>
                        </div>
                        <span className="text-[11px] text-[#71717A] tabular-nums shrink-0">
                          {formatRelativeTime(item.timestamp)}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </div>
      </section>
    </div>
  );
}

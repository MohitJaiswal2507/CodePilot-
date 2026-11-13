"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  BookOpen,
  UploadCloud,
  FileText,
  Trash2,
  AlertCircle,
  CheckCircle2,
  Sparkles,
  Loader2,
  FileCheck,
  RotateCcw,
  ChevronRight,
  Filter,
  Cpu,
  RefreshCw,
  Check,
  ChevronDown,
  MessageSquare,
  Edit3,
  Plus,
  X,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import {
  DocumentSummary,
  Citation,
  ModelInfo,
  ConversationSummary,
  fetchDocuments,
  uploadDocument,
  deleteDocument,
  clearAllDocuments,
  fetchAvailableModels,
  fetchConversations,
  fetchConversation,
  createConversation,
  updateConversation,
  deleteConversation,
  sendConversationMessage,
} from "@/services/api";
import { Badge } from "@/components/ui";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { ChatComposer } from "./chat/ChatComposer";
import { UserMessage } from "./chat/UserMessage";

interface Message {
  id: string;
  sender: "user" | "assistant";
  text: string;
  citations?: Citation[];
  insufficientContext?: boolean;
  isError?: boolean;
  modelUsed?: string;
  timestamp: string;
}

export function AITutor() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedFilter, setSelectedFilter] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputQuery, setInputQuery] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [isQuerying, setIsQuerying] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  // Left sidebar tab: "materials" or "history"
  const [leftTab, setLeftTab] = useState<"materials" | "history">("materials");
  const [docSearchQuery, setDocSearchQuery] = useState<string>("");
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState<boolean>(false);

  // Conversation Management State
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [activeConversationTitle, setActiveConversationTitle] = useState<string>("New Chat");
  const [isLoadingConversations, setIsLoadingConversations] = useState(false);
  const [isLoadingActiveConversation, setIsLoadingActiveConversation] = useState(false);
  const [editingConvId, setEditingConvId] = useState<string | null>(null);
  const [editingConvTitle, setEditingConvTitle] = useState("");
  const [isEditingHeaderTitle, setIsEditingHeaderTitle] = useState(false);
  const [headerTitleInput, setHeaderTitleInput] = useState("");

  // Model Selection State
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [activeRouting, setActiveRouting] = useState<Record<string, string>>({});
  const [isRefreshingModels, setIsRefreshingModels] = useState(false);
  const [isModelDropdownOpen, setIsModelDropdownOpen] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const chatBottomRef = useRef<HTMLDivElement>(null);
  const modelDropdownRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Previous message edit state
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);

  const loadDocuments = useCallback(async () => {
    try {
      const response = await fetchDocuments();
      setDocuments(response.documents || []);
    } catch {
      // Clear documents on error to prevent displaying stale state across accounts
      setDocuments([]);
    }
  }, []);

  const loadModels = useCallback(async (refresh: boolean = false) => {
    try {
      if (refresh) setIsRefreshingModels(true);
      const data = await fetchAvailableModels(refresh);
      setModels(data.models || []);
      setActiveRouting(data.active_routing || {});

      const saved = typeof window !== "undefined" ? localStorage.getItem("codepilot_gemini_model") : null;
      if (saved && data.models.some((m) => m.id === saved)) {
        setSelectedModel(saved);
      } else if (data.default_model) {
        setSelectedModel(data.default_model);
      } else if (data.models.length > 0) {
        setSelectedModel(data.models[0].id);
      }
    } catch {
      // Backend may be offline or initializing
    } finally {
      setIsRefreshingModels(false);
    }
  }, []);

  // Load conversation detail helper
  const loadConversationDetail = useCallback(async (convId: string) => {
    try {
      setIsLoadingActiveConversation(true);
      const detail = await fetchConversation(convId);
      setActiveConversationId(detail.id);
      setActiveConversationTitle(detail.title);
      if (typeof window !== "undefined") {
        localStorage.setItem("codepilot_active_conv_id", detail.id);
      }
      if (detail.selected_model) {
        setSelectedModel(detail.selected_model);
      }
      if (detail.document_filter !== undefined) {
        setSelectedFilter(detail.document_filter || "");
      }
      const mappedMessages: Message[] = detail.messages.map((m) => ({
        id: m.id,
        sender: m.role === "user" ? "user" : "assistant",
        text: m.content,
        citations: m.citations || [],
        insufficientContext: m.insufficient_context,
        isError: m.is_error,
        modelUsed: m.model_used,
        timestamp: new Date(m.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      }));
      setMessages(mappedMessages);
    } catch (err) {
      console.warn("Failed to load conversation details:", err);
    } finally {
      setIsLoadingActiveConversation(false);
    }
  }, []);

  // Load conversation list and restore last active conversation
  const loadConversations = useCallback(async () => {
    try {
      setIsLoadingConversations(true);
      const data = await fetchConversations();
      setConversations(data.conversations || []);

      const savedConvId = typeof window !== "undefined" ? localStorage.getItem("codepilot_active_conv_id") : null;
      if (savedConvId && data.conversations.some((c) => c.id === savedConvId)) {
        await loadConversationDetail(savedConvId);
      } else if (data.conversations.length > 0) {
        // Default to the most recent conversation if no saved ID exists
        await loadConversationDetail(data.conversations[0].id);
      } else {
        // No conversations exist yet: ready for fresh new chat
        setActiveConversationId(null);
        setActiveConversationTitle("New Chat");
        setMessages([]);
      }
    } catch {
      // Backend or DB may be initializing
    } finally {
      setIsLoadingConversations(false);
    }
  }, [loadConversationDetail]);

  useEffect(() => {
    loadDocuments();
    loadModels();
    loadConversations();
  }, [loadDocuments, loadModels, loadConversations]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (modelDropdownRef.current && !modelDropdownRef.current.contains(event.target as Node)) {
        setIsModelDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSelectModel = (modelId: string) => {
    setSelectedModel(modelId);
    if (typeof window !== "undefined") {
      localStorage.setItem("codepilot_gemini_model", modelId);
    }
    if (activeConversationId) {
      updateConversation(activeConversationId, { selected_model: modelId }).catch(() => {});
    }
    setIsModelDropdownOpen(false);
  };

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isQuerying]);

  // Mobile drawer body scroll locking & Escape key dismissal
  useEffect(() => {
    if (!mobileDrawerOpen) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setMobileDrawerOpen(false);
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [mobileDrawerOpen]);

  const handleFileUpload = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setUploadError("Only PDF documents (.pdf) are supported.");
      return;
    }
    if (file.size > 15 * 1024 * 1024) {
      setUploadError("File exceeds the 15MB size limit.");
      return;
    }

    setUploadError(null);
    setUploadSuccess(null);
    setIsUploading(true);

    try {
      const response = await uploadDocument(file);
      setUploadSuccess(`Indexed '${response.document.document_name}' (${response.document.total_chunks} chunks).`);
      await loadDocuments();
      setTimeout(() => setUploadSuccess(null), 4000);
    } catch (err: unknown) {
      setUploadError(err instanceof Error ? err.message : "Failed to upload document.");
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      handleFileUpload(e.target.files[0]);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  };

  const handleDelete = async (docName: string) => {
    try {
      await deleteDocument(docName);
      if (selectedFilter === docName) setSelectedFilter("");
      await loadDocuments();
    } catch (err: unknown) {
      setUploadError(err instanceof Error ? err.message : "Failed to delete document.");
    }
  };

  const handleClearAll = async () => {
    if (!confirm("Are you sure you want to remove all indexed materials?")) return;
    try {
      await clearAllDocuments();
      setSelectedFilter("");
      setDocuments([]);
    } catch (err: unknown) {
      setUploadError(err instanceof Error ? err.message : "Failed to clear documents.");
    }
  };

  const handleCancelGeneration = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsQuerying(false);
  };

  const handleEditPrevious = () => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].sender === "user") {
        setInputQuery(messages[i].text);
        setEditingMessageId(messages[i].id);
        break;
      }
    }
  };

  const handleCancelEdit = () => {
    setEditingMessageId(null);
    setInputQuery("");
  };

  // Start a fresh new chat
  const handleStartNewChat = () => {
    setActiveConversationId(null);
    setActiveConversationTitle("New Chat");
    setMessages([]);
    setEditingMessageId(null);
    setInputQuery("");
    if (typeof window !== "undefined") {
      localStorage.removeItem("codepilot_active_conv_id");
    }
  };

  // Switch to a chosen conversation
  const handleSelectConversation = async (convId: string) => {
    if (convId === activeConversationId) return;
    await loadConversationDetail(convId);
  };

  // Delete conversation
  const handleDeleteConversation = async (convId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await deleteConversation(convId);
      const updated = conversations.filter((c) => c.id !== convId);
      setConversations(updated);

      if (activeConversationId === convId) {
        if (updated.length > 0) {
          await loadConversationDetail(updated[0].id);
        } else {
          handleStartNewChat();
        }
      }
    } catch (err) {
      console.error("Failed to delete conversation:", err);
    }
  };

  // Rename conversation from sidebar list
  const handleStartInlineRename = (conv: ConversationSummary, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingConvId(conv.id);
    setEditingConvTitle(conv.title);
  };

  const handleSaveInlineRename = async (convId: string) => {
    const trimmed = editingConvTitle.trim();
    setEditingConvId(null);
    if (!trimmed) return;

    try {
      const updated = await updateConversation(convId, { title: trimmed });
      setConversations((prev) =>
        prev.map((c) => (c.id === convId ? { ...c, title: updated.title } : c))
      );
      if (activeConversationId === convId) {
        setActiveConversationTitle(updated.title);
      }
    } catch (err) {
      console.error("Failed to rename conversation:", err);
    }
  };

  // Rename active conversation from header
  const handleSaveHeaderTitle = async () => {
    const trimmed = headerTitleInput.trim();
    setIsEditingHeaderTitle(false);
    if (!trimmed || !activeConversationId) return;

    try {
      const updated = await updateConversation(activeConversationId, { title: trimmed });
      setActiveConversationTitle(updated.title);
      setConversations((prev) =>
        prev.map((c) => (c.id === activeConversationId ? { ...c, title: updated.title } : c))
      );
    } catch (err) {
      console.error("Failed to rename conversation:", err);
    }
  };

  // Send message using backend persistent conversation
  const handleSendMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const query = inputQuery.trim();
    if (!query || isQuerying) return;

    let baseMessages = messages;
    if (editingMessageId) {
      const editIndex = messages.findIndex((m) => m.id === editingMessageId);
      if (editIndex !== -1) {
        baseMessages = messages.slice(0, editIndex);
      }
      setEditingMessageId(null);
    }

    const tempId = "temp-" + Date.now().toString();
    const optimisticUserMsg: Message = {
      id: tempId,
      sender: "user",
      text: query,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    setMessages([...baseMessages, optimisticUserMsg]);
    setInputQuery("");
    setIsQuerying(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      let targetConvId = activeConversationId;

      // If starting fresh without an existing conversation, create one first
      if (!targetConvId) {
        const newConv = await createConversation({
          title: query.slice(0, 45),
          selected_model: selectedModel || undefined,
          document_filter: selectedFilter || undefined,
        });
        targetConvId = newConv.id;
        setActiveConversationId(newConv.id);
        setActiveConversationTitle(newConv.title);
        if (typeof window !== "undefined") {
          localStorage.setItem("codepilot_active_conv_id", newConv.id);
        }
      }

      const result = await sendConversationMessage(
        targetConvId,
        query,
        selectedModel || undefined,
        selectedFilter || undefined,
        undefined,
        controller.signal
      );

      const persistedUserMsg: Message = {
        id: result.user_message.id,
        sender: "user",
        text: result.user_message.content,
        timestamp: new Date(result.user_message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };

      const assistantMsg: Message = {
        id: result.assistant_message.id,
        sender: "assistant",
        text: result.assistant_message.content,
        citations: result.assistant_message.citations || [],
        insufficientContext: result.assistant_message.insufficient_context,
        isError: result.assistant_message.is_error,
        modelUsed: result.assistant_message.model_used || selectedModel,
        timestamp: new Date(result.assistant_message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };

      setMessages((prev) => {
        const withoutOptimistic = prev.filter((m) => m.id !== tempId);
        return [...withoutOptimistic, persistedUserMsg, assistantMsg];
      });

      // Update conversation title and list ordering
      if (result.conversation) {
        setActiveConversationTitle(result.conversation.title);
        setConversations((prev) => {
          const idx = prev.findIndex((c) => c.id === result.conversation.id);
          let updatedList: ConversationSummary[];
          if (idx !== -1) {
            updatedList = [...prev];
            updatedList[idx] = result.conversation;
          } else {
            updatedList = [result.conversation, ...prev];
          }
          return updatedList.sort(
            (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
          );
        });
      }
    } catch (err: unknown) {
      const isAbort = 
        (err instanceof DOMException && err.name === "AbortError") ||
        (err instanceof Error && err.name === "AbortError") ||
        (err instanceof Error && err.message.toLowerCase().includes("abort"));

      if (isAbort) {
        const cancelledMsg: Message = {
          id: (Date.now() + 1).toString(),
          sender: "assistant",
          text: "*Generation stopped by user.*",
          insufficientContext: false,
          isError: false,
          modelUsed: selectedModel,
          timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        };
        setMessages((prev) => [...prev.filter((m) => m.id !== tempId), optimisticUserMsg, cancelledMsg]);
        return;
      }

      const errorMsg: Message = {
        id: (Date.now() + 1).toString(),
        sender: "assistant",
        text: err instanceof Error ? `Connection error: ${err.message}` : "Failed to receive response from tutor service.",
        insufficientContext: false,
        isError: true,
        modelUsed: selectedModel,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev.filter((m) => m.id !== tempId), optimisticUserMsg, errorMsg]);
    } finally {
      setIsQuerying(false);
      abortControllerRef.current = null;
    }
  };

  const handleRetry = async (failedMsgId: string) => {
    if (isQuerying || !activeConversationId) return;
    const failedIndex = messages.findIndex((m) => m.id === failedMsgId);
    if (failedIndex === -1) return;

    let queryToRetry = "";
    for (let i = failedIndex - 1; i >= 0; i--) {
      if (messages[i].sender === "user") {
        queryToRetry = messages[i].text;
        break;
      }
    }
    if (!queryToRetry) return;

    // Remove the failed assistant message from UI
    setMessages((prev) => prev.filter((m) => m.id !== failedMsgId));
    setIsQuerying(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const result = await sendConversationMessage(
        activeConversationId,
        queryToRetry,
        selectedModel || undefined,
        selectedFilter || undefined,
        undefined,
        controller.signal
      );

      const assistantMsg: Message = {
        id: result.assistant_message.id,
        sender: "assistant",
        text: result.assistant_message.content,
        citations: result.assistant_message.citations || [],
        insufficientContext: result.assistant_message.insufficient_context,
        isError: result.assistant_message.is_error,
        modelUsed: result.assistant_message.model_used || selectedModel,
        timestamp: new Date(result.assistant_message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: unknown) {
      const errorMsg: Message = {
        id: Date.now().toString(),
        sender: "assistant",
        text: err instanceof Error ? `Connection error: ${err.message}` : "Failed to receive response from tutor service.",
        insufficientContext: false,
        isError: true,
        modelUsed: selectedModel,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsQuerying(false);
      abortControllerRef.current = null;
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const formatRelativeTime = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      const now = new Date();
      const diffSec = Math.floor((now.getTime() - d.getTime()) / 1000);
      if (diffSec < 60) return "just now";
      if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
      if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
      return `${Math.floor(diffSec / 86400)}d ago`;
    } catch {
      return "";
    }
  };

  const currentModelObj = models.find((m) => m.id === selectedModel);

  const filteredDocuments = documents.filter((doc) =>
    doc.document_name.toLowerCase().includes(docSearchQuery.toLowerCase())
  );

  const renderSidebarContent = () => (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Tab Switcher: Materials vs Chat History */}
      <div className="p-2 border-b border-white/[0.08] bg-white/[0.02] flex items-center gap-1.5 shrink-0">
        <button
          onClick={() => setLeftTab("materials")}
          className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-medium flex items-center justify-center gap-1.5 transition-all duration-150 cursor-pointer ${
            leftTab === "materials"
              ? "bg-[#181C25] text-[#F4F4F5] shadow-sm border border-white/[0.12]"
              : "text-[#A1A1AA] hover:text-[#F4F4F5] hover:bg-white/[0.04]"
          }`}
        >
          <BookOpen className="w-3.5 h-3.5 text-[#3B82F6]" />
          <span>Materials</span>
          <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-[#111319] text-[#A1A1AA] border border-[#272B36]">
            {documents.length}
          </span>
        </button>
        <button
          onClick={() => setLeftTab("history")}
          className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-medium flex items-center justify-center gap-1.5 transition-all duration-150 cursor-pointer ${
            leftTab === "history"
              ? "bg-[#181C25] text-[#F4F4F5] shadow-sm border border-white/[0.12]"
              : "text-[#A1A1AA] hover:text-[#F4F4F5] hover:bg-white/[0.04]"
          }`}
        >
          <MessageSquare className="w-3.5 h-3.5 text-[#3B82F6]" />
          <span>History</span>
          <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-[#111319] text-[#A1A1AA] border border-[#272B36]">
            {conversations.length}
          </span>
        </button>
      </div>

      {/* TAB 1: MATERIALS CONTENT */}
      {leftTab === "materials" && (
        <div className="flex-1 flex flex-col min-h-0">
          {/* Upload Drop Zone */}
          <div className="p-3.5 border-b border-white/[0.08] space-y-3 shrink-0">
            <div
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`border-2 border-dashed rounded-xl p-4 text-center cursor-pointer transition-all duration-150 ${
                isDragging
                  ? "border-[#3B82F6] bg-[#3B82F6]/10"
                  : "border-white/[0.12] hover:border-[#3B82F6]/50 bg-white/[0.02] hover:bg-white/[0.04]"
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,application/pdf"
                onChange={handleFileChange}
                className="hidden"
              />
              {isUploading ? (
                <div className="flex flex-col items-center gap-2 py-2 text-[#3B82F6]">
                  <Loader2 className="w-6 h-6 animate-spin" />
                  <span className="text-xs font-medium">Extracting & indexing chunks...</span>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-1.5 py-1">
                  <div className="w-9 h-9 rounded-lg bg-[#3B82F6]/15 border border-[#3B82F6]/30 text-[#3B82F6] flex items-center justify-center shadow-[0_0_16px_-4px_rgba(59,130,246,0.35)]">
                    <UploadCloud className="w-5 h-5" />
                  </div>
                  <p className="text-xs font-medium text-[#F4F4F5]">Upload Course Material (PDF)</p>
                  <p className="text-[10px] text-[#71717A]">Drag & drop or browse (Max 15MB)</p>
                </div>
              )}
            </div>

            {/* Feedback Messages */}
            {uploadError && (
              <div className="p-2.5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-[11px] flex items-start gap-2">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{uploadError}</span>
              </div>
            )}
            {uploadSuccess && (
              <div className="p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-[11px] flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                <span>{uploadSuccess}</span>
              </div>
            )}
          </div>

          {/* Search Documents and Context Scope Filter */}
          {documents.length > 0 && (
            <div className="p-3 border-b border-white/[0.08] bg-white/[0.015] space-y-2 shrink-0">
              <div className="relative">
                <Search className="w-3.5 h-3.5 text-[#71717A] absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  type="text"
                  value={docSearchQuery}
                  onChange={(e) => setDocSearchQuery(e.target.value)}
                  placeholder="Search indexed PDFs..."
                  className="w-full bg-[#111319] border border-white/[0.09] rounded-lg pl-8 pr-3 py-1.5 text-xs text-[#F4F4F5] placeholder:text-[#71717A] focus:outline-none focus:border-[#3B82F6]/60 transition-colors"
                />
              </div>

              <div className="flex items-center justify-between gap-2 pt-0.5">
                <div className="flex items-center gap-1.5 text-[11px] text-[#A1A1AA]">
                  <Filter className="w-3 h-3 text-[#3B82F6]" />
                  <span>Context Scope:</span>
                </div>
                <select
                  value={selectedFilter}
                  onChange={(e) => setSelectedFilter(e.target.value)}
                  className="bg-[#111319] border border-white/[0.1] text-[#F4F4F5] text-[11px] rounded-md px-2 py-1 max-w-[150px] truncate focus:outline-none focus:border-[#3B82F6] cursor-pointer"
                >
                  <option value="">All Documents</option>
                  {documents.map((d) => (
                    <option key={d.document_name} value={d.document_name}>
                      {d.document_name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {/* Document List */}
          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {documents.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center p-4 text-[#71717A] space-y-2">
                <FileText className="w-8 h-8 opacity-40 text-[#3B82F6]" />
                <p className="text-xs font-medium text-[#A1A1AA]">No materials indexed yet</p>
                <p className="text-[11px] text-[#71717A] max-w-[200px] leading-relaxed">
                  Upload lecture notes, syllabi, or textbook chapters to ground answers.
                </p>
              </div>
            ) : filteredDocuments.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center p-4 text-[#71717A] space-y-1">
                <Search className="w-6 h-6 opacity-40" />
                <p className="text-xs text-[#A1A1AA]">No documents match &ldquo;{docSearchQuery}&rdquo;</p>
              </div>
            ) : (
              filteredDocuments.map((doc) => {
                const isFiltered = selectedFilter === doc.document_name;
                return (
                  <div
                    key={doc.document_name}
                    onClick={() => {
                      setSelectedFilter(isFiltered ? "" : doc.document_name);
                    }}
                    className={`p-3 rounded-xl border transition-all duration-150 cursor-pointer ${
                      isFiltered
                        ? "bg-[#3B82F6]/10 border-[#3B82F6]/40 shadow-[0_0_20px_-8px_rgba(59,130,246,0.35)]"
                        : "bg-white/[0.02] border-white/[0.08] hover:border-white/[0.16] hover:bg-white/[0.04]"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex items-start gap-2.5">
                        <div className="w-7 h-7 rounded-lg bg-[#3B82F6]/15 border border-[#3B82F6]/30 flex items-center justify-center text-[#3B82F6] shrink-0 mt-0.5">
                          <FileCheck className="w-3.5 h-3.5" />
                        </div>
                        <div className="min-w-0">
                          <p className="text-xs font-medium text-[#F4F4F5] truncate" title={doc.document_name}>
                            {doc.document_name}
                          </p>
                          <div className="flex items-center gap-1.5 mt-1 text-[10px] text-[#A1A1AA]">
                            <span>{doc.total_pages} {doc.total_pages === 1 ? "page" : "pages"}</span>
                            <span>•</span>
                            <span>{doc.total_chunks} chunks</span>
                            {doc.file_size_bytes > 0 && (
                              <>
                                <span>•</span>
                                <span>{formatFileSize(doc.file_size_bytes)}</span>
                              </>
                            )}
                          </div>
                        </div>
                      </div>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(doc.document_name);
                        }}
                        title="Remove document"
                        className="text-[#71717A] hover:text-red-400 transition-colors p-1 rounded hover:bg-white/[0.06] cursor-pointer"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Clear All Footer */}
          {documents.length > 0 && (
            <div className="p-3 border-t border-white/[0.08] bg-white/[0.015] flex justify-between items-center shrink-0">
              <span className="text-[11px] text-[#A1A1AA]">
                Total: {documents.reduce((acc, d) => acc + d.total_chunks, 0)} chunks
              </span>
              <button
                onClick={handleClearAll}
                className="text-[11px] text-[#A1A1AA] hover:text-red-400 transition-colors flex items-center gap-1 cursor-pointer"
              >
                <Trash2 className="w-3 h-3" />
                <span>Clear All</span>
              </button>
            </div>
          )}
        </div>
      )}

      {/* TAB 2: CHAT HISTORY CONTENT */}
      {leftTab === "history" && (
        <div className="flex-1 flex flex-col min-h-0">
          {/* New Chat Button */}
          <div className="p-3 border-b border-white/[0.08] shrink-0">
            <button
              onClick={() => {
                handleStartNewChat();
                setMobileDrawerOpen(false);
              }}
              className="w-full py-2 px-3 rounded-lg bg-[#3B82F6] hover:bg-[#2563EB] text-white text-xs font-medium flex items-center justify-center gap-2 transition-all duration-150 shadow-[0_0_16px_-4px_rgba(59,130,246,0.45)] cursor-pointer"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>New Chat</span>
            </button>
          </div>

          {/* Conversation Threads List */}
          <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
            {isLoadingConversations && conversations.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center p-4 text-[#71717A] space-y-2">
                <Loader2 className="w-5 h-5 animate-spin text-[#3B82F6]" />
                <p className="text-xs">Loading conversations...</p>
              </div>
            ) : conversations.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center p-4 text-[#71717A] space-y-2">
                <MessageSquare className="w-8 h-8 opacity-40 text-[#3B82F6]" />
                <p className="text-xs font-medium text-[#A1A1AA]">No saved conversations</p>
                <p className="text-[11px] text-[#71717A] max-w-[200px] leading-relaxed">
                  Your questions and learning sessions will automatically persist here.
                </p>
              </div>
            ) : (
              conversations.map((conv) => {
                const isActive = conv.id === activeConversationId;
                const isEditingThis = editingConvId === conv.id;

                return (
                  <div
                    key={conv.id}
                    onClick={() => {
                      handleSelectConversation(conv.id);
                      setMobileDrawerOpen(false);
                    }}
                    className={`group relative p-2.5 rounded-xl border text-left cursor-pointer transition-all duration-150 ${
                      isActive
                        ? "bg-[#3B82F6]/15 border-[#3B82F6]/40 text-[#F4F4F5] shadow-[0_0_20px_-8px_rgba(59,130,246,0.35)]"
                        : "bg-white/[0.02] border-transparent hover:bg-white/[0.04] hover:border-white/[0.08] text-[#A1A1AA]"
                    }`}
                  >
                    {isEditingThis ? (
                      <div
                        className="flex items-center gap-1.5"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <input
                          autoFocus
                          type="text"
                          value={editingConvTitle}
                          onChange={(e) => setEditingConvTitle(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleSaveInlineRename(conv.id);
                            if (e.key === "Escape") setEditingConvId(null);
                          }}
                          className="flex-1 bg-[#080A10] border border-[#3B82F6] rounded px-2 py-1 text-xs text-[#F4F4F5] focus:outline-none"
                        />
                        <button
                          onClick={() => handleSaveInlineRename(conv.id)}
                          className="p-1 rounded bg-[#3B82F6] hover:bg-[#2563EB] text-white cursor-pointer"
                        >
                          <Check className="w-3 h-3" />
                        </button>
                        <button
                          onClick={() => setEditingConvId(null)}
                          className="p-1 rounded bg-[#181C25] hover:bg-white/[0.08] text-[#A1A1AA] cursor-pointer"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-start justify-between gap-1.5">
                        <div className="min-w-0 flex-1">
                          <p className="text-xs font-medium truncate text-[#F4F4F5]" title={conv.title}>
                            {conv.title}
                          </p>
                          <div className="flex items-center gap-2 mt-1 text-[10px] text-[#71717A]">
                            <span>{conv.message_count} {conv.message_count === 1 ? "msg" : "msgs"}</span>
                            <span>•</span>
                            <span>{formatRelativeTime(conv.updated_at)}</span>
                          </div>
                        </div>

                        {/* Action icons on hover or active */}
                        <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={(e) => handleStartInlineRename(conv, e)}
                            title="Rename chat"
                            className="p-1 text-[#71717A] hover:text-[#F4F4F5] transition-colors cursor-pointer"
                          >
                            <Edit3 className="w-3 h-3" />
                          </button>
                          <button
                            onClick={(e) => handleDeleteConversation(conv.id, e)}
                            title="Delete conversation"
                            className="p-1 text-[#71717A] hover:text-red-400 transition-colors cursor-pointer"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>

          {/* History Footer */}
          <div className="p-3 border-t border-white/[0.08] bg-white/[0.015] text-[11px] text-[#A1A1AA] flex items-center justify-between shrink-0">
            <span>{conversations.length} {conversations.length === 1 ? "thread" : "threads"} stored</span>
            <button
              onClick={loadConversations}
              disabled={isLoadingConversations}
              title="Refresh conversation list"
              className="hover:text-[#F4F4F5] transition-colors flex items-center gap-1 cursor-pointer"
            >
              <RefreshCw className={`w-3 h-3 ${isLoadingConversations ? "animate-spin text-[#3B82F6]" : ""}`} />
              <span>Refresh</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div className="h-[calc(100vh-7.5rem)] flex gap-5 max-w-7xl mx-auto select-none relative">
      {/* Desktop Left Column: Learning Materials & Chat History Sidebar */}
      <div className="hidden lg:flex w-80 flex-col rounded-xl bg-[#111319] border border-[#272B36] shrink-0 overflow-hidden">
        {renderSidebarContent()}
      </div>

      {/* Mobile Drawer Overlay */}
      {mobileDrawerOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Learning Materials and Conversation History"
          className="fixed inset-0 z-50 lg:hidden flex"
        >
          <div
            className="fixed inset-0 bg-black/60 backdrop-blur-sm transition-opacity"
            onClick={() => setMobileDrawerOpen(false)}
          />
          <div className="relative w-80 max-w-[85vw] h-full bg-[#111319] border-r border-white/[0.1] shadow-2xl flex flex-col z-10">
            <div className="p-3 border-b border-white/[0.08] flex items-center justify-between">
              <span className="text-xs font-semibold text-[#F4F4F5]">Tutor Workspace</span>
              <button
                type="button"
                onClick={() => setMobileDrawerOpen(false)}
                className="p-1 rounded text-[#71717A] hover:text-[#F4F4F5] cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3B82F6]"
                aria-label="Close tutor workspace drawer"
                title="Close drawer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            {renderSidebarContent()}
          </div>
        </div>
      )}

      {/* Right Column: Q&A Chat Console */}
      <div className="flex-1 flex flex-col rounded-xl bg-[#111319] border border-[#272B36] overflow-hidden min-w-0">
        {/* Chat Header */}
        <div className="p-3.5 sm:p-4 border-b border-white/[0.08] flex items-center justify-between relative bg-white/[0.02]">
          <div className="min-w-0 flex-1 mr-3 flex items-center gap-2">
            {/* Mobile Drawer Trigger Button */}
            <button
              onClick={() => setMobileDrawerOpen(true)}
              className="lg:hidden p-2 rounded-lg bg-white/[0.04] border border-white/[0.08] text-[#3B82F6] hover:text-white transition-colors cursor-pointer shrink-0"
              title="Open materials and history"
            >
              <SlidersHorizontal className="w-4 h-4" />
            </button>

            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                {isEditingHeaderTitle ? (
                  <div className="flex items-center gap-1.5 max-w-sm">
                    <input
                      autoFocus
                      type="text"
                      value={headerTitleInput}
                      onChange={(e) => setHeaderTitleInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleSaveHeaderTitle();
                        if (e.key === "Escape") setIsEditingHeaderTitle(false);
                      }}
                      className="bg-[#080A10] border border-[#3B82F6] rounded px-2 py-0.5 text-xs text-[#F4F4F5] focus:outline-none"
                    />
                    <button
                      onClick={handleSaveHeaderTitle}
                      className="p-1 rounded bg-[#3B82F6] hover:bg-[#2563EB] text-white cursor-pointer"
                    >
                      <Check className="w-3 h-3" />
                    </button>
                    <button
                      onClick={() => setIsEditingHeaderTitle(false)}
                      className="p-1 rounded bg-[#181C25] hover:bg-white/[0.08] text-[#A1A1AA] cursor-pointer"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 group min-w-0">
                    <h2 className="text-sm font-semibold text-[#F4F4F5] truncate max-w-xs sm:max-w-md" title={activeConversationTitle}>
                      {activeConversationTitle || "AI Learning Assistant"}
                    </h2>
                    {activeConversationId && (
                      <button
                        onClick={() => {
                          setHeaderTitleInput(activeConversationTitle);
                          setIsEditingHeaderTitle(true);
                        }}
                        title="Rename conversation"
                        className="p-1 text-[#71717A] hover:text-[#F4F4F5] opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer shrink-0"
                      >
                        <Edit3 className="w-3 h-3" />
                      </button>
                    )}
                  </div>
                )}
                <Badge variant="ai" size="sm" dot className="shrink-0 hidden sm:inline-flex">
                  Curriculum Grounded
                </Badge>
              </div>
              <p className="text-[11px] text-[#A1A1AA] mt-0.5 truncate">
                {selectedFilter
                  ? `Filtered to context: ${selectedFilter}`
                  : "Retrieving from all indexed course materials"}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {/* Dynamic Model Selector Dropdown */}
            <div className="relative" ref={modelDropdownRef}>
              <button
                onClick={() => setIsModelDropdownOpen(!isModelDropdownOpen)}
                className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.1] text-xs text-[#F4F4F5] transition-colors shadow-sm cursor-pointer"
                title="Select Gemini Model"
              >
                <Cpu className="w-3.5 h-3.5 text-[#3B82F6]" />
                <span className="font-medium text-[11px] max-w-[90px] sm:max-w-[130px] truncate">
                  {currentModelObj?.display_name || selectedModel || "Gemini Model"}
                </span>
                {currentModelObj && (
                  <span className={`hidden sm:inline-block text-[9px] px-1.5 py-0.5 rounded border font-mono font-medium ${
                    currentModelObj.category === "fast"
                      ? "bg-amber-500/10 text-amber-300 border-amber-500/20"
                      : currentModelObj.category === "reasoning"
                      ? "bg-[#3B82F6]/10 text-[#93C5FD] border-[#3B82F6]/20"
                      : currentModelObj.category === "preview"
                      ? "bg-cyan-500/10 text-cyan-300 border-cyan-500/20"
                      : "bg-emerald-500/10 text-emerald-300 border-emerald-500/20"
                  }`}>
                    {currentModelObj.category.toUpperCase()}
                  </span>
                )}
                <ChevronDown className={`w-3.5 h-3.5 text-[#71717A] transition-transform duration-200 ${isModelDropdownOpen ? "rotate-180" : ""}`} />
              </button>

              {/* Dropdown Menu */}
              {isModelDropdownOpen && (
                <div className="absolute right-0 top-full mt-2 w-80 sm:w-96 rounded-xl bg-[#111319] border border-white/[0.14] shadow-2xl z-50 overflow-hidden flex flex-col">
                  {/* Dropdown Header */}
                  <div className="p-3 border-b border-white/[0.08] flex items-center justify-between bg-white/[0.02]">
                    <div className="flex items-center gap-2">
                      <Cpu className="w-4 h-4 text-[#3B82F6]" />
                      <span className="text-xs font-semibold text-[#F4F4F5] tracking-wide uppercase">Gemini Models</span>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        loadModels(true);
                      }}
                      disabled={isRefreshingModels}
                      title="Refresh available models from Google API"
                      className="p-1.5 rounded-md hover:bg-white/[0.06] text-[#A1A1AA] hover:text-[#F4F4F5] transition-colors disabled:opacity-50 cursor-pointer"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${isRefreshingModels ? "animate-spin text-[#3B82F6]" : ""}`} />
                    </button>
                  </div>

                  {/* Routing Info Banner */}
                  {activeRouting.rewrite && (
                    <div className="px-3 py-1.5 bg-[#3B82F6]/10 border-b border-[#3B82F6]/20 text-[10px] text-[#93C5FD] flex items-center justify-between font-mono">
                      <span>Rewriter: {activeRouting.rewrite}</span>
                      <span>Active: {selectedModel}</span>
                    </div>
                  )}

                  {/* Model Items List */}
                  <div className="max-h-72 overflow-y-auto p-1.5 space-y-1">
                    {models.length === 0 ? (
                      <div className="p-4 text-center text-xs text-[#71717A]">
                        {isRefreshingModels ? "Loading available models..." : "No Gemini models discovered."}
                      </div>
                    ) : (
                      models.map((model) => {
                        const isSelected = (model.id === selectedModel);
                        return (
                          <button
                            key={model.id}
                            onClick={() => handleSelectModel(model.id)}
                            className={`w-full text-left p-2.5 rounded-lg border transition-all flex items-start justify-between gap-2.5 cursor-pointer ${
                              isSelected
                                ? "bg-[#3B82F6]/15 border-[#3B82F6]/40 text-[#F4F4F5]"
                                : "bg-white/[0.02] border-transparent hover:bg-white/[0.05] hover:border-white/[0.08] text-[#A1A1AA]"
                            }`}
                          >
                            <div className="min-w-0 flex-1 space-y-1">
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-medium text-[#F4F4F5] truncate">{model.display_name}</span>
                                <span className={`text-[9px] px-1.5 py-0.2 rounded border font-mono font-medium ${
                                  model.category === "fast"
                                    ? "bg-amber-500/10 text-amber-300 border-amber-500/20"
                                    : model.category === "reasoning"
                                    ? "bg-[#3B82F6]/10 text-[#93C5FD] border-[#3B82F6]/20"
                                    : model.category === "preview"
                                    ? "bg-cyan-500/10 text-cyan-300 border-cyan-500/20"
                                    : "bg-emerald-500/10 text-emerald-300 border-emerald-500/20"
                                }`}>
                                  {model.category.toUpperCase()}
                                </span>
                                {model.is_default && (
                                  <span className="text-[9px] px-1.5 py-0.2 rounded bg-white/[0.06] text-[#A1A1AA] border border-white/[0.08] font-mono">
                                    DEFAULT
                                  </span>
                                )}
                              </div>
                              {model.description && (
                                <p className="text-[11px] text-[#A1A1AA] line-clamp-2 leading-relaxed">
                                  {model.description}
                                </p>
                              )}
                              <p className="text-[10px] text-[#71717A] font-mono truncate">{model.id}</p>
                            </div>
                            {isSelected && (
                              <div className="w-5 h-5 rounded-full bg-[#3B82F6]/20 text-[#3B82F6] flex items-center justify-center shrink-0 mt-0.5 border border-[#3B82F6]/40">
                                <Check className="w-3 h-3" />
                              </div>
                            )}
                          </button>
                        );
                      })
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Quick New Chat Button */}
            <button
              onClick={handleStartNewChat}
              className="text-xs text-[#F4F4F5] hover:text-white transition-colors flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-white/[0.1] hover:border-white/[0.16] bg-white/[0.04] shadow-sm cursor-pointer"
              title="Start a new chat thread"
            >
              <Plus className="w-3 h-3 text-[#3B82F6]" />
              <span className="hidden sm:inline">New Chat</span>
            </button>
          </div>
        </div>

        {/* Message Thread */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-5">
          {isLoadingActiveConversation ? (
            <div className="h-full flex flex-col items-center justify-center text-center space-y-2 text-[#71717A]">
              <Loader2 className="w-6 h-6 animate-spin text-[#3B82F6]" />
              <p className="text-xs">Loading conversation history...</p>
            </div>
          ) : messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center max-w-md mx-auto space-y-4">
              <div className="w-12 h-12 rounded-xl bg-[#3B82F6]/15 border border-[#3B82F6]/30 text-[#3B82F6] flex items-center justify-center shadow-[0_0_24px_-6px_rgba(59,130,246,0.4)]">
                <Sparkles className="w-6 h-6" />
              </div>
              <div className="space-y-1.5">
                <h3 className="text-sm font-semibold text-[#F4F4F5]">Curriculum-Grounded Learning Assistant</h3>
                <p className="text-xs text-[#A1A1AA] leading-relaxed">
                  Ask questions about algorithms, system architectures, or language rules found in your uploaded materials.
                  Every answer provides verifiable citations and strictly avoids hallucination.
                </p>
              </div>

              {documents.length > 0 && (
                <div className="w-full space-y-2 pt-2">
                  <p className="text-[11px] uppercase tracking-wider font-semibold text-[#71717A] text-left">
                    Suggested Questions
                  </p>
                  <div className="space-y-1.5 text-left">
                    <button
                      onClick={() => setInputQuery("What are the key concepts and topics covered in this material?")}
                      className="w-full p-2.5 rounded-lg bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.08] hover:border-white/[0.14] text-xs text-[#F4F4F5] text-left transition-colors flex items-center justify-between cursor-pointer"
                    >
                      <span>What are the key concepts and topics covered in this material?</span>
                      <ChevronRight className="w-3.5 h-3.5 text-[#71717A] shrink-0" />
                    </button>
                    <button
                      onClick={() => setInputQuery("Explain the time and space complexity trade-offs discussed.")}
                      className="w-full p-2.5 rounded-lg bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.08] hover:border-white/[0.14] text-xs text-[#F4F4F5] text-left transition-colors flex items-center justify-between cursor-pointer"
                    >
                      <span>Explain the time and space complexity trade-offs discussed.</span>
                      <ChevronRight className="w-3.5 h-3.5 text-[#71717A] shrink-0" />
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex flex-col ${msg.sender === "user" ? "items-end" : "items-start"} animate-cp-fade-up`}
              >
                <div className="flex items-center gap-2 mb-1 px-1">
                  <span className="text-[10px] font-medium text-[#A1A1AA]">
                    {msg.sender === "user" ? "You" : "AI Learning Assistant"}
                  </span>
                  {msg.sender === "assistant" && msg.modelUsed && (
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-white/[0.06] text-[#93C5FD] font-mono border border-white/[0.08]">
                      {msg.modelUsed}
                    </span>
                  )}
                  <span className="text-[10px] text-[#71717A]">{msg.timestamp}</span>
                </div>

                <div
                  className={`max-w-[85%] rounded-2xl p-4 text-xs leading-relaxed ${
                    msg.sender === "user"
                      ? "bg-[#3B82F6] text-[#F4F4F5] rounded-tr-sm shadow-md"
                      : msg.isError
                      ? "bg-red-950/20 text-red-200 border border-red-900/40 rounded-tl-sm space-y-3.5 shadow-md"
                      : "bg-[#181C25] text-[#F4F4F5] border border-[#272B36] rounded-tl-sm space-y-3.5 shadow-sm"
                  }`}
                >
                  {msg.sender === "user" ? (
                    <UserMessage content={msg.text} />
                  ) : msg.isError ? (
                    <div className="space-y-3">
                      <div className="flex items-start gap-2.5 text-red-300">
                        <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
                        <div className="flex-1 text-xs leading-relaxed">{msg.text}</div>
                      </div>
                      <button
                        onClick={() => handleRetry(msg.id)}
                        disabled={isQuerying}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-300 border border-red-500/30 text-[11px] font-medium transition-colors disabled:opacity-50 cursor-pointer"
                      >
                        <RotateCcw className="w-3.5 h-3.5" />
                        <span>Retry Request</span>
                      </button>
                    </div>
                  ) : (
                    <MarkdownRenderer content={msg.text} />
                  )}

                  {/* Insufficient Context Alert - strictly excluded on provider errors */}
                  {!msg.isError && msg.insufficientContext && msg.sender === "assistant" && (
                    <div className="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-[11px] flex items-center gap-2">
                      <AlertCircle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                      <span>Context is insufficient in current material. Refusing to speculate.</span>
                    </div>
                  )}

                  {/* Citations Box */}
                  {msg.citations && msg.citations.length > 0 && (
                    <div className="pt-3 border-t border-white/[0.08] space-y-2.5">
                      <div className="flex items-center justify-between">
                        <p className="text-[10px] uppercase font-semibold text-[#3B82F6] flex items-center gap-1.5 tracking-wider">
                          <FileText className="w-3 h-3 text-[#3B82F6]" /> Grounded Source Citations
                        </p>
                        <span className="text-[10px] text-[#A1A1AA] font-mono">
                          {msg.citations.length} {msg.citations.length === 1 ? "source" : "sources"}
                        </span>
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {msg.citations.map((c, idx) => (
                          <div
                            key={idx}
                            className="p-3 rounded-xl bg-[#080A10]/80 border border-white/[0.08] hover:border-[#3B82F6]/40 text-[11px] space-y-1.5 transition-all duration-150 shadow-sm"
                          >
                            <div className="flex items-center justify-between gap-1 text-[10px] font-medium text-[#93C5FD]">
                              <span className="truncate max-w-[150px] font-mono text-[#F4F4F5]" title={c.document_name}>
                                {c.document_name}
                              </span>
                              <Badge variant="ai" size="sm">
                                Page {c.page_number}
                              </Badge>
                            </div>
                            <p className="text-[#A1A1AA] text-[11px] line-clamp-3 italic leading-relaxed">
                              &ldquo;{c.snippet}&rdquo;
                            </p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))
          )}

          {isQuerying && (
            <div className="flex flex-col items-start space-y-1 animate-cp-fade-in">
              <span className="text-[10px] font-medium text-[#A1A1AA] px-1">AI Learning Assistant</span>
              <div className="p-3.5 rounded-xl bg-[#181C25] border border-[#272B36] flex items-center gap-2.5 text-xs text-[#93C5FD] shadow-sm">
                <Loader2 className="w-4 h-4 animate-spin text-[#3B82F6]" />
                <span>Searching vector database & grounding response...</span>
              </div>
            </div>
          )}

          <div ref={chatBottomRef} />
        </div>

        {/* Chat Composer Bar */}
        <div className="p-3 sm:p-4 border-t border-white/[0.08] bg-white/[0.015]">
          <ChatComposer
            value={inputQuery}
            onChange={setInputQuery}
            onSend={handleSendMessage}
            onCancel={handleCancelGeneration}
            isLoading={isQuerying}
            isEditing={!!editingMessageId}
            onCancelEdit={handleCancelEdit}
            onEditPrevious={handleEditPrevious}
            placeholder={
              documents.length === 0
                ? "Upload course materials (PDF) first to ask curriculum-grounded questions..."
                : "Ask a question, paste code, or drop an error log... (Shift + Enter for new line, Enter to send)"
            }
            disabled={documents.length === 0}
          />
        </div>
      </div>
    </div>
  );
}

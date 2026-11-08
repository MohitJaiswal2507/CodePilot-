export interface HealthStatus {
  status: "healthy" | "unhealthy" | "offline";
  service: string;
  version: string;
  environment: string;
  timestamp: string;
  latencyMs?: number;
  error?: string;
}

export interface Citation {
  document_name: string;
  page_number: number;
  snippet: string;
}

export interface DocumentSummary {
  document_name: string;
  total_pages: number;
  total_chunks: number;
  file_size_bytes: number;
  uploaded_at: string;
}

export interface UploadResponse {
  status: string;
  message: string;
  document: DocumentSummary;
}

export interface DocumentListResponse {
  documents: DocumentSummary[];
  total_documents: number;
  total_chunks: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface QueryResponse {
  answer: string;
  citations: Citation[];
  insufficient_context: boolean;
  retrieved_chunks_count: number;
  standalone_query?: string;
  is_error?: boolean;
  model_used?: string;
}

export interface ModelInfo {
  id: string;
  display_name: string;
  description?: string;
  category: "fast" | "balanced" | "reasoning" | "preview" | "general" | string;
  is_default: boolean;
  supported_methods: string[];
  input_token_limit?: number;
  output_token_limit?: number;
}

export interface ModelListResponse {
  models: ModelInfo[];
  default_model: string;
  active_routing: Record<string, string>;
}

export interface MessageRecord {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  insufficient_context?: boolean;
  is_error?: boolean;
  model_used?: string;
  status?: string;
  created_at: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  selected_model: string;
  document_filter?: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail {
  id: string;
  title: string;
  selected_model: string;
  document_filter?: string | null;
  created_at: string;
  updated_at: string;
  messages: MessageRecord[];
}

export interface SendMessageResult {
  user_message: MessageRecord;
  assistant_message: MessageRecord;
  conversation: ConversationSummary;
}

export interface CodeReviewIssue {
  type: "bug" | "error" | "warning" | "performance" | "style" | "security";
  severity: "critical" | "high" | "medium" | "low" | "info";
  message: string;
  line_number?: number | null;
  suggestion?: string | null;
}

export interface EdgeCaseAnalysis {
  category: string;
  scenario: string;
  behavior: string;
  handled: boolean;
}

export interface ComplexityAnalysis {
  time_complexity: string;
  time_reasoning: string;
  space_complexity: string;
  space_reasoning: string;
}

export interface CodeReviewResult {
  summary: string;
  overall_assessment: "excellent" | "good" | "needs_improvement" | "problematic" | "critical_bugs";
  quality_score: number;
  detected_issues: CodeReviewIssue[];
  edge_cases: EdgeCaseAnalysis[];
  complexity: ComplexityAnalysis;
  improvement_suggestions: string[];
  corrected_code?: string | null;
  explanation_of_changes?: string | null;
  static_analysis_notes?: string | null;
}

export interface CodeReviewResponse {
  id: string;
  language: string;
  submitted_code: string;
  review: CodeReviewResult;
  model_used: string;
  created_at: string;
}

export interface CodeReviewHistoryItem {
  id: string;
  language: string;
  code_snippet: string;
  summary: string;
  overall_assessment: string;
  quality_score: number;
  model_used: string;
  created_at: string;
}

export interface CodeReviewHistoryResponse {
  reviews: CodeReviewHistoryItem[];
  total: number;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

let inMemoryAuthToken: string | null = null;

export function clearApiAuthToken(): void {
  inMemoryAuthToken = null;
  if (typeof window !== "undefined") {
    try {
      localStorage.removeItem("codepilot_auth_token");
    } catch {}
  }
}

export function setApiAuthToken(token: string | null): void {
  inMemoryAuthToken = token;
  if (typeof window !== "undefined") {
    try {
      if (token) {
        localStorage.setItem("codepilot_auth_token", token);
      } else {
        localStorage.removeItem("codepilot_auth_token");
      }
    } catch {
      // Storage unavailable or quota exceeded
    }
  }
}

export function getApiAuthToken(): string | null {
  if (typeof window !== "undefined") {
    // 1. Prioritize active cookie session token
    try {
      const match = document.cookie.match(
        /(?:^|;\s*)(?:__Secure-)?(?:neon-auth|better-auth)\.session_token=([^;]+)/
      );
      if (match && match[1]) {
        const cookieToken = decodeURIComponent(match[1]);
        if (cookieToken) {
          inMemoryAuthToken = cookieToken;
          return cookieToken;
        }
      }
    } catch {}

    // 2. Check local storage if cookie is not readable (e.g. strict dev setup)
    try {
      const stored = localStorage.getItem("codepilot_auth_token");
      if (stored) {
        inMemoryAuthToken = stored;
        return stored;
      }
    } catch {}
  }
  return inMemoryAuthToken;
}

export async function getAuthHeaders(extraHeaders: Record<string, string> = {}): Promise<Record<string, string>> {
  const headers: Record<string, string> = { ...extraHeaders };
  let token: string | null = null;

  // Always attempt to get the freshest session token from active Neon Auth session
  if (typeof window !== "undefined") {
    try {
      const { authClient } = await import("@/lib/auth/client");
      const session = await authClient.getSession();
      if (session?.data?.session?.token) {
        token = session.data.session.token;
        setApiAuthToken(token);
      } else if (!session?.data?.user) {
        // No active user session - clear cached token to prevent sending stale tokens from previous accounts
        clearApiAuthToken();
      }
    } catch {
      // Session fetch error handled silently
    }
  }

  if (!token) {
    token = getApiAuthToken();
  }

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  return headers;
}

export async function fetchBackendHealth(): Promise<HealthStatus> {
  const startTime = performance.now();
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 4000);

    const response = await fetch(`${API_BASE_URL}/api/health`, {
      method: "GET",
      signal: controller.signal,
      headers: {
        "Accept": "application/json",
      },
      cache: "no-store",
    });

    clearTimeout(timeoutId);
    const latencyMs = Math.round(performance.now() - startTime);

    if (!response.ok) {
      return {
        status: "unhealthy",
        service: "CodePilot AI Backend",
        version: "unknown",
        environment: "unknown",
        timestamp: new Date().toISOString(),
        latencyMs,
        error: `HTTP ${response.status}: ${response.statusText}`,
      };
    }

    const data = await response.json();
    return {
      ...data,
      latencyMs,
    };
  } catch (err: unknown) {
    const latencyMs = Math.round(performance.now() - startTime);
    const errorMessage = err instanceof Error ? err.message : "Failed to connect to backend server";
    return {
      status: "offline",
      service: "CodePilot AI Backend",
      version: "0.1.0",
      environment: "development",
      timestamp: new Date().toISOString(),
      latencyMs,
      error: errorMessage,
    };
  }
}

export async function uploadDocument(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const authHeaders = await getAuthHeaders();
  const response = await fetch(`${API_BASE_URL}/api/tutor/upload`, {
    method: "POST",
    headers: authHeaders,
    body: formData,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Upload failed with HTTP ${response.status}`);
  }

  return response.json();
}

export async function fetchDocuments(): Promise<DocumentListResponse> {
  const headers = await getAuthHeaders({
    "Accept": "application/json",
  });
  const response = await fetch(`${API_BASE_URL}/api/tutor/documents`, {
    method: "GET",
    headers,
    cache: "no-store",
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to fetch documents: HTTP ${response.status}`);
  }

  return response.json();
}

export async function deleteDocument(documentName: string): Promise<{ status: string; message: string }> {
  const headers = await getAuthHeaders({
    "Accept": "application/json",
  });
  const response = await fetch(`${API_BASE_URL}/api/tutor/documents/${encodeURIComponent(documentName)}`, {
    method: "DELETE",
    headers,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to delete document: HTTP ${response.status}`);
  }

  return response.json();
}

export async function clearAllDocuments(): Promise<{ status: string; message: string }> {
  const headers = await getAuthHeaders({
    "Accept": "application/json",
  });
  const response = await fetch(`${API_BASE_URL}/api/tutor/documents`, {
    method: "DELETE",
    headers,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to clear documents: HTTP ${response.status}`);
  }

  return response.json();
}

export async function fetchAvailableModels(refresh: boolean = false): Promise<ModelListResponse> {
  const url = `${API_BASE_URL}/api/tutor/models${refresh ? "?refresh=true" : ""}`;
  const headers = await getAuthHeaders({
    "Accept": "application/json",
  });
  const response = await fetch(url, {
    method: "GET",
    headers,
    cache: "no-store",
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to fetch models: HTTP ${response.status}`);
  }

  return response.json();
}

export async function askTutor(
  question: string,
  documentFilter?: string,
  history: ChatMessage[] = [],
  model?: string,
  top_k: number = 4,
  signal?: AbortSignal
): Promise<QueryResponse> {
  const headers = await getAuthHeaders({
    "Content-Type": "application/json",
    "Accept": "application/json",
  });
  const response = await fetch(`${API_BASE_URL}/api/tutor/query`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      question,
      document_filter: documentFilter || null,
      top_k,
      history,
      model: model || null,
    }),
    signal,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Query failed with HTTP ${response.status}`);
  }

  return response.json();
}

export function getClientSessionId(): string {
  if (typeof window === "undefined") return "default_session";
  let sessionId = localStorage.getItem("codepilot_session_id");
  if (!sessionId) {
    sessionId = "session_" + Math.random().toString(36).substring(2, 12) + "_" + Date.now().toString(36);
    localStorage.setItem("codepilot_session_id", sessionId);
  }
  return sessionId;
}

export async function fetchConversations(
  limit: number = 50,
  offset: number = 0,
  sessionId?: string
): Promise<{ conversations: ConversationSummary[]; total: number }> {
  const sid = sessionId || getClientSessionId();
  const headers = await getAuthHeaders({
    "Accept": "application/json",
    "X-Session-ID": sid,
  });
  const response = await fetch(`${API_BASE_URL}/api/conversations?limit=${limit}&offset=${offset}`, {
    method: "GET",
    headers,
    cache: "no-store",
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to fetch conversations: HTTP ${response.status}`);
  }

  return response.json();
}

export async function fetchConversation(
  conversationId: string,
  sessionId?: string
): Promise<ConversationDetail> {
  const sid = sessionId || getClientSessionId();
  const headers = await getAuthHeaders({
    "Accept": "application/json",
    "X-Session-ID": sid,
  });
  const response = await fetch(`${API_BASE_URL}/api/conversations/${encodeURIComponent(conversationId)}`, {
    method: "GET",
    headers,
    cache: "no-store",
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to fetch conversation: HTTP ${response.status}`);
  }

  return response.json();
}

export async function createConversation(
  data?: { title?: string; selected_model?: string; document_filter?: string },
  sessionId?: string
): Promise<ConversationDetail> {
  const sid = sessionId || getClientSessionId();
  const headers = await getAuthHeaders({
    "Content-Type": "application/json",
    "Accept": "application/json",
    "X-Session-ID": sid,
  });
  const response = await fetch(`${API_BASE_URL}/api/conversations`, {
    method: "POST",
    headers,
    body: JSON.stringify(data || {}),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to create conversation: HTTP ${response.status}`);
  }

  return response.json();
}

export async function updateConversation(
  conversationId: string,
  data: { title?: string; selected_model?: string; document_filter?: string },
  sessionId?: string
): Promise<ConversationDetail> {
  const sid = sessionId || getClientSessionId();
  const headers = await getAuthHeaders({
    "Content-Type": "application/json",
    "Accept": "application/json",
    "X-Session-ID": sid,
  });
  const response = await fetch(`${API_BASE_URL}/api/conversations/${encodeURIComponent(conversationId)}`, {
    method: "PATCH",
    headers,
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to update conversation: HTTP ${response.status}`);
  }

  return response.json();
}

export async function deleteConversation(
  conversationId: string,
  sessionId?: string
): Promise<void> {
  const sid = sessionId || getClientSessionId();
  const headers = await getAuthHeaders({
    "Accept": "application/json",
    "X-Session-ID": sid,
  });
  const response = await fetch(`${API_BASE_URL}/api/conversations/${encodeURIComponent(conversationId)}`, {
    method: "DELETE",
    headers,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to delete conversation: HTTP ${response.status}`);
  }
}

export async function sendConversationMessage(
  conversationId: string,
  question: string,
  model?: string,
  documentFilter?: string,
  sessionId?: string,
  signal?: AbortSignal
): Promise<SendMessageResult> {
  const sid = sessionId || getClientSessionId();
  const headers = await getAuthHeaders({
    "Content-Type": "application/json",
    "Accept": "application/json",
    "X-Session-ID": sid,
  });
  const response = await fetch(`${API_BASE_URL}/api/conversations/${encodeURIComponent(conversationId)}/messages`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      question,
      model: model || null,
      document_filter: documentFilter || null,
    }),
    signal,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Message delivery failed with HTTP ${response.status}`);
  }

  return response.json();
}

// -----------------------------------------------------------------------------
// AI Code Reviewer API Services
// -----------------------------------------------------------------------------

export async function submitCodeReview(
  code: string,
  language: string,
  model?: string
): Promise<CodeReviewResponse> {
  const headers = await getAuthHeaders({
    "Content-Type": "application/json",
    "Accept": "application/json",
  });

  const response = await fetch(`${API_BASE_URL}/api/reviewer/review`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      code,
      language,
      model: model || null,
    }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Code review failed with status ${response.status}`);
  }

  return response.json();
}

export async function fetchCodeReviewHistory(
  limit: number = 20,
  offset: number = 0
): Promise<CodeReviewHistoryResponse> {
  const headers = await getAuthHeaders({
    "Accept": "application/json",
  });

  const response = await fetch(
    `${API_BASE_URL}/api/reviewer/history?limit=${limit}&offset=${offset}`,
    {
      method: "GET",
      headers,
      cache: "no-store",
    }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to fetch review history: HTTP ${response.status}`);
  }

  return response.json();
}

export async function fetchCodeReviewDetail(id: string): Promise<CodeReviewResponse> {
  const headers = await getAuthHeaders({
    "Accept": "application/json",
  });

  const response = await fetch(
    `${API_BASE_URL}/api/reviewer/${encodeURIComponent(id)}`,
    {
      method: "GET",
      headers,
      cache: "no-store",
    }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to fetch review details: HTTP ${response.status}`);
  }

  return response.json();
}

export async function deleteCodeReview(id: string): Promise<void> {
  const headers = await getAuthHeaders({
    "Accept": "application/json",
  });

  const response = await fetch(
    `${API_BASE_URL}/api/reviewer/${encodeURIComponent(id)}`,
    {
      method: "DELETE",
      headers,
    }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to delete review: HTTP ${response.status}`);
  }
}

export async function clearCodeReviewHistory(): Promise<void> {
  const headers = await getAuthHeaders({
    "Accept": "application/json",
  });

  const response = await fetch(`${API_BASE_URL}/api/reviewer`, {
    method: "DELETE",
    headers,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to clear review history: HTTP ${response.status}`);
  }
}

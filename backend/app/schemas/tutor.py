from typing import Optional, List
from pydantic import BaseModel, Field

class Citation(BaseModel):
    document_name: str = Field(..., description="Name of the source document")
    page_number: int = Field(..., description="1-based page number where context was found")
    snippet: str = Field(..., description="Excerpt of the retrieved source text")

class DocumentChunk(BaseModel):
    id: str = Field(..., description="Unique chunk identifier")
    document_name: str
    page_number: int
    chunk_index: int
    text: str

class DocumentSummary(BaseModel):
    id: Optional[str] = None
    document_name: str
    total_pages: int
    total_chunks: int
    file_size_bytes: int = 0
    uploaded_at: str
    owner_user_id: Optional[str] = None
    upload_status: Optional[str] = "completed"

class UploadResponse(BaseModel):
    status: str
    message: str
    document: DocumentSummary

class ChatMessage(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message text")

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=25000, description="Student's conceptual or technical question, code snippet, or error log")
    document_filter: Optional[str] = Field(None, description="Optional document name to filter retrieval")
    top_k: int = Field(default=4, ge=1, le=10, description="Number of context chunks to retrieve")
    history: List[ChatMessage] = Field(default_factory=list, description="Recent conversation history turns")
    model: Optional[str] = Field(None, description="Optional user-selected Gemini model ID")

class QueryResponse(BaseModel):
    answer: str
    citations: List[Citation] = Field(default_factory=list)
    insufficient_context: bool = False
    retrieved_chunks_count: int = 0
    standalone_query: Optional[str] = None
    is_error: bool = False
    model_used: Optional[str] = Field(None, description="The model ID that answered the question")

class ModelInfo(BaseModel):
    id: str = Field(..., description="Normalized model identifier (e.g., 'gemini-3.5-flash-lite')")
    display_name: str = Field(..., description="Display name for UI")
    description: Optional[str] = Field(None, description="Model capability description")
    category: str = Field(default="general", description="Category: 'fast', 'balanced', 'reasoning', 'preview'")
    is_default: bool = Field(default=False, description="Whether this model is the server default")
    supported_methods: List[str] = Field(default_factory=list, description="Supported API generation methods")
    input_token_limit: Optional[int] = None
    output_token_limit: Optional[int] = None

class ModelListResponse(BaseModel):
    models: List[ModelInfo] = Field(default_factory=list)
    default_model: str
    active_routing: dict[str, str] = Field(default_factory=dict)

class DocumentListResponse(BaseModel):
    documents: List[DocumentSummary] = Field(default_factory=list)
    total_documents: int = 0
    total_chunks: int = 0

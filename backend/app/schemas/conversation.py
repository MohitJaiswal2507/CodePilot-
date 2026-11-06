from typing import Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, ConfigDict
from app.schemas.tutor import Citation

class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: str
    content: str
    citations: Optional[List[Citation]] = None
    insufficient_context: bool = False
    is_error: bool = False
    model_used: Optional[str] = None
    status: str = "completed"
    created_at: datetime


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    selected_model: str
    document_filter: Optional[str] = None
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class ConversationDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    selected_model: str
    document_filter: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    messages: List[MessageResponse] = Field(default_factory=list)


class ConversationListResponse(BaseModel):
    conversations: List[ConversationSummary] = Field(default_factory=list)
    total: int = 0


class CreateConversationRequest(BaseModel):
    title: Optional[str] = Field(default="New Conversation", max_length=255)
    selected_model: Optional[str] = Field(default=None, max_length=128)
    document_filter: Optional[str] = Field(default=None, max_length=255)


class UpdateConversationRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    selected_model: Optional[str] = Field(default=None, max_length=128)
    document_filter: Optional[str] = Field(default=None, max_length=255)


class SendMessageRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=25000, description="User question or code snippet")
    model: Optional[str] = Field(default=None, max_length=128)
    document_filter: Optional[str] = Field(default=None, max_length=255)

    @field_validator("question")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Question cannot be empty or whitespace only.")
        return v.strip()


class SendMessageResponse(BaseModel):
    user_message: MessageResponse
    assistant_message: MessageResponse
    conversation: ConversationSummary

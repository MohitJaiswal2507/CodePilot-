from typing import Optional
from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.auth import get_current_user, AuthenticatedUser
from app.schemas.conversation import (
    ConversationListResponse,
    ConversationDetailResponse,
    CreateConversationRequest,
    UpdateConversationRequest,
    SendMessageRequest,
    SendMessageResponse,
)
from app.services import conversation_service

router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    session_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> ConversationListResponse:
    """List conversations owned by the authenticated user, sorted by most recently updated."""
    summaries, total = conversation_service.list_conversations(
        db=db,
        user_id=current_user.user_id,
        session_id=x_session_id or session_id,
        limit=limit,
        offset=offset,
    )
    return ConversationListResponse(conversations=summaries, total=total)


@router.post("", response_model=ConversationDetailResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: CreateConversationRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    session_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> ConversationDetailResponse:
    """Create a new conversation thread owned by the authenticated user."""
    return conversation_service.create_conversation(
        db=db,
        user_id=current_user.user_id,
        session_id=x_session_id or session_id,
        title=payload.title,
        selected_model=payload.selected_model,
        document_filter=payload.document_filter,
    )


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(
    conversation_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    session_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> ConversationDetailResponse:
    """Retrieve full conversation details verifying ownership by the authenticated user."""
    return conversation_service.get_conversation(
        db=db,
        conversation_id=conversation_id,
        user_id=current_user.user_id,
        session_id=x_session_id or session_id,
    )


@router.patch("/{conversation_id}", response_model=ConversationDetailResponse)
def update_conversation(
    conversation_id: str,
    payload: UpdateConversationRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    session_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> ConversationDetailResponse:
    """Rename a conversation or update its configuration after verifying user ownership."""
    return conversation_service.update_conversation(
        db=db,
        conversation_id=conversation_id,
        user_id=current_user.user_id,
        session_id=x_session_id or session_id,
        title=payload.title,
        selected_model=payload.selected_model,
        document_filter=payload.document_filter,
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_200_OK)
def delete_conversation(
    conversation_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    session_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Delete a user-owned conversation and cascade to all its messages."""
    conversation_service.delete_conversation(
        db=db,
        conversation_id=conversation_id,
        user_id=current_user.user_id,
        session_id=x_session_id or session_id,
    )
    return {"status": "success", "message": f"Conversation '{conversation_id}' deleted."}


@router.post("/{conversation_id}/messages", response_model=SendMessageResponse)
def send_message(
    conversation_id: str,
    payload: SendMessageRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    session_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> SendMessageResponse:
    """
    Send a message within an existing user-owned conversation thread:
    Saves user query, runs conversation-aware RAG, auto-titles, persists assistant response + citations.
    """
    return conversation_service.send_conversation_message(
        db=db,
        conversation_id=conversation_id,
        user_id=current_user.user_id,
        session_id=x_session_id or session_id,
        question=payload.question,
        model_override=payload.model,
        document_filter=payload.document_filter,
    )

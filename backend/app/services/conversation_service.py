import re
import logging
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from fastapi import HTTPException, status

from app.models.conversation import Conversation, Message
from app.schemas.tutor import ChatMessage, Citation
from app.schemas.conversation import (
    ConversationSummary,
    ConversationDetailResponse,
    MessageResponse,
    SendMessageResponse,
)
from app.services.rag_service import answer_question
from app.services import model_service
from app.core.config import settings

logger = logging.getLogger(__name__)

def generate_conversation_title(question: str) -> str:
    """Generate a clean, readable 3-6 word title from the user's initial question or code snippet."""
    clean = question.strip()
    if not clean:
        return "New Conversation"
    # If first line contains code syntax (e.g. function findMax(...) {)
    first_line = clean.splitlines()[0].strip()

    # If code definition
    code_match = re.match(r"^(?:async\s+)?(?:def|function|class|public\s+class)\s+([a-zA-Z0-9_]+)", first_line)
    if code_match:
        return f"Code: {code_match.group(1)}()"

    # Strip conversational prefixes: "What is", "Explain", "Can you show me", "How does"
    clean_text = re.sub(
        r"^(?:can\s+you\s+)?(?:please\s+)?(?:explain|what\s+is|what\s+are|how\s+to|how\s+does|tell\s+me\s+about|show\s+me\s+an?\s+example\s+of)\s+",
        "",
        first_line,
        flags=re.IGNORECASE,
    ).strip()

    # Remove trailing punctuation
    clean_text = clean_text.rstrip("?!.:;,")
    if not clean_text:
        clean_text = first_line[:40]

    # Capitalize first character
    title = clean_text[:50].strip()
    return title[:1].upper() + title[1:] if title else "New Conversation"


def _get_conversation_with_ownership_check(
    db: Session,
    conversation_id: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Conversation:
    """
    Retrieve conversation with strict multi-tenant ownership enforcement:
    - If user_id is provided: ensures conversation.user_id matches the authenticated user.
    - If no user_id: falls back to session_id for development/backward compatibility.
    - Prevents cross-user IDOR access by returning 404.
    """
    query = db.query(Conversation).filter(Conversation.id == conversation_id)

    if user_id:
        # Match user_id or (if unassigned legacy record) match session_id
        query = query.filter(
            or_(
                Conversation.user_id == user_id,
                (Conversation.user_id.is_(None)) & (Conversation.session_id == session_id) if session_id else False,
            )
        )
    elif session_id:
        query = query.filter(Conversation.session_id == session_id)

    conv = query.first()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found.",
        )
    
    # If conversation was unassigned and an authenticated user accesses it with matching session, claim ownership
    if user_id and conv.user_id is None:
        conv.user_id = user_id
        db.commit()
        db.refresh(conv)

    return conv


def list_conversations(
    db: Session,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[ConversationSummary], int]:
    """Retrieve conversations for the authenticated user or session, sorted by updated_at descending."""
    query = db.query(Conversation)

    if user_id:
        query = query.filter(
            or_(
                Conversation.user_id == user_id,
                (Conversation.user_id.is_(None)) & (Conversation.session_id == session_id) if session_id else False,
            )
        )
    elif session_id:
        query = query.filter(Conversation.session_id == session_id)

    total = query.count()

    conversations = (
        query.order_by(Conversation.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    summaries = []
    for conv in conversations:
        msg_count = db.query(func.count(Message.id)).filter(Message.conversation_id == conv.id).scalar() or 0
        summaries.append(
            ConversationSummary(
                id=conv.id,
                title=conv.title,
                user_id=conv.user_id,
                session_id=conv.session_id,
                selected_model=conv.selected_model,
                document_filter=conv.document_filter,
                message_count=msg_count,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
            )
        )

    return summaries, total


def create_conversation(
    db: Session,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    title: Optional[str] = None,
    selected_model: Optional[str] = None,
    document_filter: Optional[str] = None,
) -> ConversationDetailResponse:
    """Create a new conversation associated with authenticated user or session."""
    model_id = selected_model or settings.GEMINI_MODEL
    validated_model = model_service.normalize_model_id(model_id)

    conv = Conversation(
        title=(title or "New Conversation").strip(),
        user_id=user_id,
        session_id=session_id or "default_session",
        selected_model=validated_model,
        document_filter=document_filter,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)

    return ConversationDetailResponse(
        id=conv.id,
        title=conv.title,
        user_id=conv.user_id,
        session_id=conv.session_id,
        selected_model=conv.selected_model,
        document_filter=conv.document_filter,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[],
    )


def get_conversation(
    db: Session,
    conversation_id: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> ConversationDetailResponse:
    """Retrieve a conversation and its messages verifying user ownership."""
    conv = _get_conversation_with_ownership_check(
        db=db,
        conversation_id=conversation_id,
        user_id=user_id,
        session_id=session_id,
    )

    message_responses = [
        MessageResponse(
            id=m.id,
            conversation_id=m.conversation_id,
            role=m.role,
            content=m.content,
            citations=[Citation(**c) for c in (m.citations or [])] if m.citations else None,
            insufficient_context=m.insufficient_context,
            is_error=m.is_error,
            model_used=m.model_used,
            status=m.status,
            created_at=m.created_at,
        )
        for m in conv.messages
    ]

    return ConversationDetailResponse(
        id=conv.id,
        title=conv.title,
        user_id=conv.user_id,
        session_id=conv.session_id,
        selected_model=conv.selected_model,
        document_filter=conv.document_filter,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=message_responses,
    )


def update_conversation(
    db: Session,
    conversation_id: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    title: Optional[str] = None,
    selected_model: Optional[str] = None,
    document_filter: Optional[str] = None,
) -> ConversationDetailResponse:
    """Update conversation metadata (title, model, or document scope) after ownership verification."""
    conv = _get_conversation_with_ownership_check(
        db=db,
        conversation_id=conversation_id,
        user_id=user_id,
        session_id=session_id,
    )

    if title is not None:
        conv.title = title.strip() or conv.title
    if selected_model is not None:
        conv.selected_model = model_service.normalize_model_id(selected_model)
    if document_filter is not None:
        conv.document_filter = document_filter if document_filter.strip() else None

    db.commit()
    db.refresh(conv)

    return get_conversation(db, conversation_id, user_id=user_id, session_id=session_id)


def delete_conversation(
    db: Session,
    conversation_id: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """Delete a conversation and its messages via cascade after ownership verification."""
    conv = _get_conversation_with_ownership_check(
        db=db,
        conversation_id=conversation_id,
        user_id=user_id,
        session_id=session_id,
    )

    db.delete(conv)
    db.commit()


def send_conversation_message(
    db: Session,
    conversation_id: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    question: str = "",
    model_override: Optional[str] = None,
    document_filter: Optional[str] = None,
    llm_callable = None,
    rewrite_callable = None,
) -> SendMessageResponse:
    """
    1. Verify conversation ownership against authenticated user.
    2. Save user message.
    3. Build conversation history from existing stored messages.
    4. Auto-generate title if still default.
    5. Execute RAG pipeline via answer_question.
    6. Save assistant message with citations.
    7. Update conversation timestamp and commit.
    """
    conv = _get_conversation_with_ownership_check(
        db=db,
        conversation_id=conversation_id,
        user_id=user_id,
        session_id=session_id,
    )

    # 1. Save user message
    user_msg = Message(
        conversation_id=conv.id,
        role="user",
        content=question.strip(),
        status="completed",
    )
    db.add(user_msg)

    # 2. Extract preceding history for RAG query rewriter and generator
    prior_messages = [
        ChatMessage(role=m.role, content=m.content)
        for m in conv.messages
        if not m.is_error and not m.content.startswith("Error communicating")
    ]

    # 3. Auto-title if conversation is currently named 'New Conversation'
    if conv.title in ["New Conversation", "", None] and len(conv.messages) == 0:
        conv.title = generate_conversation_title(question)

    # 4. Resolve active model and document scope
    target_model = model_override or conv.selected_model or settings.GEMINI_MODEL
    doc_filter = document_filter if document_filter is not None else conv.document_filter

    # Validate model
    validated_model = model_service.validate_model_id(target_model)
    if model_override:
        conv.selected_model = validated_model

    # 5. Execute RAG pipeline with verified user isolation
    effective_user_id = conv.user_id or user_id or "default_user"
    rag_response = answer_question(
        question=question,
        user_id=effective_user_id,
        document_filter=doc_filter,
        history=prior_messages,
        model=validated_model,
        llm_callable=llm_callable,
        rewrite_callable=rewrite_callable,
    )

    # 6. Save assistant message
    citations_data = (
        [c.model_dump() for c in rag_response.citations]
        if rag_response.citations
        else None
    )

    assistant_msg = Message(
        conversation_id=conv.id,
        role="assistant",
        content=rag_response.answer,
        citations=citations_data,
        insufficient_context=rag_response.insufficient_context,
        is_error=rag_response.is_error,
        model_used=rag_response.model_used or validated_model,
        status="error" if rag_response.is_error else "completed",
    )
    db.add(assistant_msg)

    # 7. Update conversation timestamp
    db.commit()
    db.refresh(user_msg)
    db.refresh(assistant_msg)
    db.refresh(conv)

    msg_count = db.query(func.count(Message.id)).filter(Message.conversation_id == conv.id).scalar() or 0
    conv_summary = ConversationSummary(
        id=conv.id,
        title=conv.title,
        user_id=conv.user_id,
        session_id=conv.session_id,
        selected_model=conv.selected_model,
        document_filter=conv.document_filter,
        message_count=msg_count,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )

    return SendMessageResponse(
        user_message=MessageResponse(
            id=user_msg.id,
            conversation_id=user_msg.conversation_id,
            role=user_msg.role,
            content=user_msg.content,
            created_at=user_msg.created_at,
            status=user_msg.status,
        ),
        assistant_message=MessageResponse(
            id=assistant_msg.id,
            conversation_id=assistant_msg.conversation_id,
            role=assistant_msg.role,
            content=assistant_msg.content,
            citations=rag_response.citations,
            insufficient_context=assistant_msg.insufficient_context,
            is_error=assistant_msg.is_error,
            model_used=assistant_msg.model_used,
            status=assistant_msg.status,
            created_at=assistant_msg.created_at,
        ),
        conversation=conv_summary,
    )

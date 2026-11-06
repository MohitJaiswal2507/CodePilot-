import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, 
    String, 
    Text, 
    DateTime, 
    Boolean, 
    JSON, 
    ForeignKey, 
    Index
)
from sqlalchemy.orm import relationship
from app.db.base import Base

def generate_uuid() -> str:
    return str(uuid.uuid4())

def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(128), nullable=True, index=True)
    title = Column(String(255), nullable=False, default="New Conversation")
    session_id = Column(String(64), nullable=False, default="default_session", index=True)
    selected_model = Column(String(128), nullable=False, default="gemini-3.5-flash-lite")
    document_filter = Column(String(255), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now, nullable=False, index=True)

    # Cascading deletion of messages when a conversation is deleted
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at.asc()",
    )

    __table_args__ = (
        Index("ix_conversations_session_updated", "session_id", "updated_at"),
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    conversation_id = Column(
        String(36), 
        ForeignKey("conversations.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True
    )
    role = Column(String(32), nullable=False) # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    citations = Column(JSON, nullable=True) # List of Citation dicts: [{document_name, page_number, snippet}]
    insufficient_context = Column(Boolean, default=False, nullable=False)
    is_error = Column(Boolean, default=False, nullable=False)
    model_used = Column(String(128), nullable=True)
    status = Column(String(32), default="completed", nullable=False) # 'completed', 'interrupted', 'error'
    
    created_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False, index=True)

    conversation = relationship("Conversation", back_populates="messages")

    __table_args__ = (
        Index("ix_messages_conv_created", "conversation_id", "created_at"),
    )


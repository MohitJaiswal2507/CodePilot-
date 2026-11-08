import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, JSON, Index
from sqlalchemy.sql import func
from app.db.base import Base

class CodeReview(Base):
    """
    Persistent code review records enforcing strict multi-user ownership.
    """
    __tablename__ = "code_reviews"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_user_id = Column(String(128), nullable=False, index=True)
    language = Column(String(32), nullable=False)
    submitted_code = Column(Text, nullable=False)
    structured_result = Column(JSON, nullable=False)
    model_used = Column(String(128), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        Index("ix_code_reviews_owner_created", "owner_user_id", "created_at"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "owner_user_id": self.owner_user_id,
            "language": self.language,
            "submitted_code": self.submitted_code,
            "structured_result": self.structured_result,
            "model_used": self.model_used,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


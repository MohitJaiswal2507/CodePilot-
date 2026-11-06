import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, BigInteger, DateTime, Index
from sqlalchemy.sql import func
from app.db.base import Base

class Document(Base):
    """
    PostgreSQL persistent document record enforcing strict user ownership.
    """
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_user_id = Column(String(128), nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)
    storage_reference = Column(String(512), nullable=True)
    upload_status = Column(String(32), nullable=False, default="completed")
    processing_status = Column(String(32), nullable=False, default="indexed")
    total_pages = Column(Integer, nullable=False, default=0)
    total_chunks = Column(Integer, nullable=False, default=0)
    file_size_bytes = Column(BigInteger, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_documents_owner_filename", "owner_user_id", "original_filename"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "owner_user_id": self.owner_user_id,
            "original_filename": self.original_filename,
            "storage_reference": self.storage_reference,
            "upload_status": self.upload_status,
            "processing_status": self.processing_status,
            "total_pages": self.total_pages,
            "total_chunks": self.total_chunks,
            "file_size_bytes": self.file_size_bytes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


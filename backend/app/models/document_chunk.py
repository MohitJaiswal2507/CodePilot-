"""
SQLAlchemy Model and VectorType for pgvector document chunks.
"""

import uuid
from typing import Optional, List, Any
from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
    Text,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.sql import func
from sqlalchemy.types import TypeDecorator, UserDefinedType

from app.core.config import settings
from app.db.base import Base

PGVECTOR_CANONICAL_DIMENSION = 768


class PGVector(UserDefinedType):
    """PostgreSQL pgvector native type representation."""

    cache_ok = True

    def __init__(self, dim: int = PGVECTOR_CANONICAL_DIMENSION):
        self.dim = dim

    def get_col_spec(self, **kw: Any) -> str:
        return f"vector({self.dim})"

    def bind_processor(self, dialect: Any) -> Any:
        def process(value: Any) -> Optional[str]:
            if value is None:
                return None
            if isinstance(value, str):
                return value
            return "[" + ",".join(f"{float(x):.8f}" for x in value) + "]"
        return process

    def result_processor(self, dialect: Any, coltype: Any) -> Any:
        def process(value: Any) -> Optional[List[float]]:
            if value is None:
                return None
            if isinstance(value, list):
                return [float(x) for x in value]
            if isinstance(value, str):
                cleaned = value.strip("[]() \t\n\r")
                if not cleaned:
                    return []
                return [float(x.strip()) for x in cleaned.split(",") if x.strip()]
            return [float(x) for x in value]
        return process


class VectorType(TypeDecorator):
    """
    SQLAlchemy TypeDecorator for vector embeddings.
    Emits native PostgreSQL `vector(dim)` on PostgreSQL/Neon,
    and transparently falls back to TEXT on SQLite/other dialects for local development and testing.
    """

    impl = Text
    cache_ok = True

    def __init__(self, dim: int = PGVECTOR_CANONICAL_DIMENSION, **kwargs: Any):
        super().__init__(**kwargs)
        self.dim = dim

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGVector(self.dim))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return "[" + ",".join(f"{float(x):.8f}" for x in value) + "]"

    def process_result_value(self, value: Any, dialect: Any) -> Optional[List[float]]:
        if value is None:
            return None
        if isinstance(value, list):
            return [float(x) for x in value]
        if isinstance(value, str):
            cleaned = value.strip("[]() \t\n\r")
            if not cleaned:
                return []
            return [float(x.strip()) for x in cleaned.split(",") if x.strip()]
        return [float(x) for x in value]


class DocumentChunkModel(Base):
    """
    Persistent document chunk model stored in PostgreSQL with pgvector embeddings.
    Guarantees strict tenant isolation by indexing and filtering on owner_user_id.
    """

    __tablename__ = "document_chunks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    chunk_id = Column(String(64), nullable=False)
    document_id = Column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_user_id = Column(String(128), nullable=False, index=True)
    document_name = Column(String(255), nullable=False)
    page_number = Column(Integer, nullable=False, default=1)
    chunk_index = Column(Integer, nullable=False, default=0)
    text = Column(Text, nullable=False)
    file_size_bytes = Column(BigInteger, nullable=False, default=0)
    embedding = Column(VectorType(PGVECTOR_CANONICAL_DIMENSION), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_document_chunks_owner_docname", "owner_user_id", "document_name"),
        Index("ix_document_chunks_doc_chunk", "document_id", "chunk_index"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "owner_user_id": self.owner_user_id,
            "document_name": self.document_name,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "file_size_bytes": self.file_size_bytes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

"""create document_chunks table with pgvector

Revision ID: c4e8b1d9a2f3
Revises: 56b97dbd4349
Create Date: 2026-11-14 18:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from app.models.document_chunk import PGVector, PGVECTOR_CANONICAL_DIMENSION

# revision identifiers, used by Alembic.
revision: str = "c4e8b1d9a2f3"
down_revision: Union[str, Sequence[str], None] = "56b97dbd4349"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        vec_col = sa.Column("embedding", PGVector(PGVECTOR_CANONICAL_DIMENSION), nullable=True)
    else:
        vec_col = sa.Column("embedding", sa.Text(), nullable=True)

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("chunk_id", sa.String(length=64), nullable=False),
        sa.Column(
            "document_id",
            sa.String(length=36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_user_id", sa.String(length=128), nullable=False),
        sa.Column("document_name", sa.String(length=255), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        vec_col,
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(op.f("ix_document_chunks_document_id"), "document_chunks", ["document_id"], unique=False)
    op.create_index(op.f("ix_document_chunks_owner_user_id"), "document_chunks", ["owner_user_id"], unique=False)
    op.create_index("ix_document_chunks_owner_docname", "document_chunks", ["owner_user_id", "document_name"], unique=False)
    op.create_index("ix_document_chunks_doc_chunk", "document_chunks", ["document_id", "chunk_index"], unique=False)

    if is_postgres:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
            "ON document_chunks USING hnsw (embedding vector_cosine_ops);"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw;")

    op.drop_index("ix_document_chunks_doc_chunk", table_name="document_chunks")
    op.drop_index("ix_document_chunks_owner_docname", table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_owner_user_id"), table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_document_id"), table_name="document_chunks")
    op.drop_table("document_chunks")

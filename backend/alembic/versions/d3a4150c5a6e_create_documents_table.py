"""create documents table

Revision ID: d3a4150c5a6e
Revises: a2e3198f1234
Create Date: 2026-11-06 16:10:22.290418

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3a4150c5a6e'
down_revision: Union[str, Sequence[str], None] = 'a2e3198f1234'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'documents',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('owner_user_id', sa.String(length=128), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('storage_reference', sa.String(length=512), nullable=True),
        sa.Column('upload_status', sa.String(length=32), nullable=False, server_default='completed'),
        sa.Column('processing_status', sa.String(length=32), nullable=False, server_default='indexed'),
        sa.Column('total_pages', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_chunks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('file_size_bytes', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_documents_created_at'), 'documents', ['created_at'], unique=False)
    op.create_index(op.f('ix_documents_owner_user_id'), 'documents', ['owner_user_id'], unique=False)
    op.create_index('ix_documents_owner_filename', 'documents', ['owner_user_id', 'original_filename'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_documents_owner_filename', table_name='documents')
    op.drop_index(op.f('ix_documents_owner_user_id'), table_name='documents')
    op.drop_index(op.f('ix_documents_created_at'), table_name='documents')
    op.drop_table('documents')

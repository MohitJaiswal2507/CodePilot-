"""add_user_id_to_conversations

Revision ID: a2e3198f1234
Revises: f1dc370fd6e9
Create Date: 2026-11-05 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a2e3198f1234'
down_revision: Union[str, Sequence[str], None] = 'f1dc370fd6e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Safely add user_id column and indexes to conversations table."""
    # 1. Add nullable user_id column
    op.add_column('conversations', sa.Column('user_id', sa.String(length=128), nullable=True))
    
    # 2. Add index for user queries
    op.create_index('ix_conversations_user_id', 'conversations', ['user_id'], unique=False)
    
    # 3. Add composite index for sorted user conversations
    op.create_index('ix_conversations_user_updated', 'conversations', ['user_id', 'updated_at'], unique=False)


def downgrade() -> None:
    """Revert user_id column and indexes from conversations table."""
    op.drop_index('ix_conversations_user_updated', table_name='conversations')
    op.drop_index('ix_conversations_user_id', table_name='conversations')
    op.drop_column('conversations', 'user_id')


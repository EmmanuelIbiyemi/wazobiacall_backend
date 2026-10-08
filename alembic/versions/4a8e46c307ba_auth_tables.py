"""auth_tables

Revision ID: 4a8e46c307ba
Revises: 
Create Date: 2026-10-08 09:23:28.361853

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4a8e46c307ba'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "users",
        sa.Column("userID", sa.String(225), primary_key=True),
        sa.Column("username", sa.String(50), nullable=False, unique=True),
        sa.Column("email", sa.String(100), nullable=False, unique=True),
        sa.Column("password", sa.String(255), nullable=False),
        sa.Column("phone_number", sa.String(100), default=True),
        sa.Column("verified_number", sa.Boolean, default=True),
        sa.Column("prefer_lang", sa.String(255), default=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    


def downgrade() -> None:
    """Downgrade schema."""
    pass

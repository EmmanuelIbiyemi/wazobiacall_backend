"""correction on the users table

Revision ID: ad3a841f8f0f
Revises: 4a8e46c307ba
Create Date: 2026-10-08 11:01:20.447042

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad3a841f8f0f'
down_revision: Union[str, Sequence[str], None] = '4a8e46c307ba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        'users', 
        'userID', 
        existing_type=sa.Integer(), 
        type_=sa.String(225), 
        nullable=False

    )


def downgrade() -> None:
    """Downgrade schema."""
    pass

"""Nullable bot_token and chat_id on settings (optional Telegram).

Revision ID: 202604281200_tg_opt
Revises:
Create Date: 2026-04-28

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "202604281200_tg_opt"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "settings",
        "chat_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.alter_column(
        "settings",
        "bot_token",
        existing_type=sa.String(),
        nullable=True,
    )


def downgrade() -> None:
    """Восстанавливает NOT NULL; упадёт, если остались строки с NULL в этих колонках."""
    op.alter_column(
        "settings",
        "bot_token",
        existing_type=sa.String(),
        nullable=False,
    )
    op.alter_column(
        "settings",
        "chat_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )

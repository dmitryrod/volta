"""Add Polymarket event URL fields to asset_config."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "asset_config",
        sa.Column("polymarket_event_slug", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "asset_config",
        sa.Column("polymarket_event_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("asset_config", "polymarket_event_url")
    op.drop_column("asset_config", "polymarket_event_slug")

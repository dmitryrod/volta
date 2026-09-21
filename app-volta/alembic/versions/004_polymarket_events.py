"""Add polymarket_events catalog table and backfill from asset_config."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "polymarket_events",
        sa.Column("base_asset", sa.String(length=16), nullable=False),
        sa.Column("event_slug", sa.String(length=256), nullable=False),
        sa.Column("event_url", sa.Text(), nullable=False),
        sa.Column("event_title", sa.Text(), nullable=True),
        sa.Column("event_end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("base_asset", "event_slug"),
    )
    op.create_index(
        "ix_polymarket_events_base_end",
        "polymarket_events",
        ["base_asset", "event_end_date"],
    )
    op.execute(
        """
        INSERT INTO polymarket_events (base_asset, event_slug, event_url, event_title, event_end_date)
        SELECT base_asset, polymarket_event_slug, polymarket_event_url, NULL, NULL
        FROM asset_config
        WHERE polymarket_event_slug IS NOT NULL
          AND polymarket_event_url IS NOT NULL
        ON CONFLICT (base_asset, event_slug) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_polymarket_events_base_end", table_name="polymarket_events")
    op.drop_table("polymarket_events")

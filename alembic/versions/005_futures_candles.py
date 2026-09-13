"""Add futures_candles table for exchange OHLC history."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "futures_candles",
        sa.Column("base_asset", sa.String(length=16), nullable=False),
        sa.Column("interval", sa.String(length=8), nullable=False),
        sa.Column("open_time", sa.BigInteger(), nullable=False),
        sa.Column("open", sa.Double(), nullable=False),
        sa.Column("high", sa.Double(), nullable=False),
        sa.Column("low", sa.Double(), nullable=False),
        sa.Column("close", sa.Double(), nullable=False),
        sa.Column("volume", sa.Double(), nullable=True),
        sa.PrimaryKeyConstraint("base_asset", "interval", "open_time"),
    )
    op.create_index(
        "ix_futures_candles_base_interval_time",
        "futures_candles",
        ["base_asset", "interval", sa.text("open_time DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_futures_candles_base_interval_time", table_name="futures_candles")
    op.drop_table("futures_candles")

"""Initial schema: snapshots + asset_config seed."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "instrument_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("base_asset", sa.String(length=16), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("market", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ts", "base_asset", "exchange", "symbol", "metric",
            name="uq_instrument_snapshots_key",
        ),
    )
    op.create_index(
        "ix_instrument_snapshots_base_ts",
        "instrument_snapshots",
        ["base_asset", sa.text("ts DESC")],
    )

    op.create_table(
        "panel_snapshots",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("base_asset", sa.String(length=16), nullable=False),
        sa.Column("futures_symbol", sa.String(length=64), nullable=True),
        sa.Column("futures_price", sa.Double(), nullable=True),
        sa.Column("call_price", sa.Double(), nullable=True),
        sa.Column("put_price", sa.Double(), nullable=True),
        sa.Column("call_symbol", sa.String(length=64), nullable=True),
        sa.Column("put_symbol", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("ts", "base_asset"),
    )

    op.create_table(
        "polymarket_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("base_asset", sa.String(length=16), nullable=False),
        sa.Column("market_id", sa.String(length=128), nullable=True),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("yes_probability", sa.Double(), nullable=False),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ts", "base_asset", "market_id",
            name="uq_polymarket_snapshots_key",
        ),
    )
    op.create_index(
        "ix_polymarket_snapshots_base_ts",
        "polymarket_snapshots",
        ["base_asset", sa.text("ts DESC")],
    )

    op.create_table(
        "asset_config",
        sa.Column("base_asset", sa.String(length=16), nullable=False),
        sa.Column("futures_symbol", sa.String(length=64), nullable=False),
        sa.Column("polymarket_market_id", sa.String(length=128), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("base_asset"),
    )

    asset_config = sa.table(
        "asset_config",
        sa.column("base_asset", sa.String),
        sa.column("futures_symbol", sa.String),
        sa.column("polymarket_market_id", sa.String),
        sa.column("enabled", sa.Boolean),
    )
    op.bulk_insert(
        asset_config,
        [
            {"base_asset": "BTC", "futures_symbol": "BTCUSDT", "polymarket_market_id": None, "enabled": True},
            {"base_asset": "ETH", "futures_symbol": "ETHUSDT", "polymarket_market_id": None, "enabled": True},
            {"base_asset": "SOL", "futures_symbol": "SOLUSDT", "polymarket_market_id": None, "enabled": True},
        ],
    )


def downgrade() -> None:
    op.drop_table("asset_config")
    op.drop_index("ix_polymarket_snapshots_base_ts", table_name="polymarket_snapshots")
    op.drop_table("polymarket_snapshots")
    op.drop_table("panel_snapshots")
    op.drop_index("ix_instrument_snapshots_base_ts", table_name="instrument_snapshots")
    op.drop_table("instrument_snapshots")

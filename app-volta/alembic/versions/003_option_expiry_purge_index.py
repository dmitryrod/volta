"""Partial index on option expiry in instrument_snapshots meta_json."""

from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_instrument_snapshots_option_expiry
        ON instrument_snapshots (base_asset, ((meta_json->>'expiry')))
        WHERE market = 'option'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_instrument_snapshots_option_expiry", table_name="instrument_snapshots")

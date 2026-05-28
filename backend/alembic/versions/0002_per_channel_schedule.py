"""per-channel schedule columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-28

Adds three columns to `channels` so each channel's refresh cadence can be
edited from /admin/channels without redeploying:

    schedule_kind      VARCHAR(16) NOT NULL DEFAULT 'interval'  -- 'interval' | 'daily'
    interval_minutes   INTEGER     NULL                          -- used when kind='interval'
    daily_time_cn      VARCHAR(5)  NULL                          -- HH:MM in Asia/Shanghai

Backfill on upgrade uses the same defaults that lived in
app/scheduler.REFRESH_MINUTES and CHANNEL_CRONS before this revision, so
existing installs keep their previous cadence.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Mirror the previously-hardcoded values so existing rows keep their cadence
# after the upgrade. Keep in sync with seed.py CHANNELS until the dust settles.
INTERVAL_DEFAULTS: dict[str, int] = {
    "midmarket": 60,
    "wise": 10,
    "boc": 15,
    "visa": 30,
    "mastercard": 30,
    "cimb": 180,
}
DAILY_DEFAULTS: dict[str, str] = {
    # UnionPay locks MYR at 11:00 Beijing; we fetch at 11:30 to give margin.
    "unionpay": "11:30",
}


def upgrade() -> None:
    with op.batch_alter_table("channels") as batch:
        batch.add_column(
            sa.Column(
                "schedule_kind",
                sa.String(length=16),
                nullable=False,
                server_default="interval",
            )
        )
        batch.add_column(sa.Column("interval_minutes", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("daily_time_cn", sa.String(length=5), nullable=True))

    conn = op.get_bind()
    for code, minutes in INTERVAL_DEFAULTS.items():
        conn.execute(
            sa.text(
                "UPDATE channels SET schedule_kind='interval', interval_minutes=:m " "WHERE code=:c"
            ),
            {"m": minutes, "c": code},
        )
    for code, hhmm in DAILY_DEFAULTS.items():
        conn.execute(
            sa.text("UPDATE channels SET schedule_kind='daily', daily_time_cn=:t WHERE code=:c"),
            {"t": hhmm, "c": code},
        )


def downgrade() -> None:
    with op.batch_alter_table("channels") as batch:
        batch.drop_column("daily_time_cn")
        batch.drop_column("interval_minutes")
        batch.drop_column("schedule_kind")

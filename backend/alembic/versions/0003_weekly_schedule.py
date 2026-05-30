"""weekly schedule: add channels.weekdays

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-30

Adds one nullable column to `channels` so a channel can run on selected days
of the week (e.g. Mon–Fri) at a fixed time, instead of every day:

    weekdays  VARCHAR(32)  NULL   -- comma list of mon,tue,wed,thu,fri,sat,sun

Used only when schedule_kind='weekly' (the time still comes from
daily_time_cn). No backfill: existing rows stay interval/daily, so weekdays
is NULL for all of them after the upgrade.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("channels") as batch:
        batch.add_column(sa.Column("weekdays", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("channels") as batch:
        batch.drop_column("weekdays")

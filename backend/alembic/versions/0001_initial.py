"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-28

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "currencies",
        sa.Column("code", sa.String(length=8), primary_key=True),
        sa.Column("name_en", sa.String(length=64), nullable=False),
        sa.Column("name_zh", sa.String(length=64), nullable=False),
    )

    op.create_table(
        "channels",
        sa.Column("code", sa.String(length=32), primary_key=True),
        sa.Column("name_en", sa.String(length=128), nullable=False),
        sa.Column("name_zh", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_msg", sa.Text(), nullable=True),
    )

    op.create_table(
        "rate_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "channel_code", sa.String(length=32), sa.ForeignKey("channels.code"), nullable=False
        ),
        sa.Column(
            "base_currency", sa.String(length=8), sa.ForeignKey("currencies.code"), nullable=False
        ),
        sa.Column(
            "quote_currency", sa.String(length=8), sa.ForeignKey("currencies.code"), nullable=False
        ),
        sa.Column("rate", sa.Numeric(20, 8), nullable=False),
        sa.Column("rate_type", sa.String(length=32), nullable=False),
        sa.Column("fee_estimate", sa.Numeric(20, 8), nullable=True),
        sa.Column("fee_currency", sa.String(length=8), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_rate_snapshots_channel_pair_fetched",
        "rate_snapshots",
        ["channel_code", "base_currency", "quote_currency", "fetched_at"],
    )

    op.create_table(
        "ai_summaries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "base_currency", sa.String(length=8), sa.ForeignKey("currencies.code"), nullable=False
        ),
        sa.Column(
            "quote_currency", sa.String(length=8), sa.ForeignKey("currencies.code"), nullable=False
        ),
        sa.Column("summary_zh", sa.Text(), nullable=False),
        sa.Column("model_used", sa.String(length=128), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_ai_summaries_pair_generated",
        "ai_summaries",
        ["base_currency", "quote_currency", "generated_at"],
    )

    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_encrypted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(length=64), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "scrape_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "channel_code", sa.String(length=32), sa.ForeignKey("channels.code"), nullable=True
        ),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scrape_logs_created", "scrape_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_scrape_logs_created", table_name="scrape_logs")
    op.drop_table("scrape_logs")
    op.drop_table("admin_users")
    op.drop_table("settings")
    op.drop_index("ix_ai_summaries_pair_generated", table_name="ai_summaries")
    op.drop_table("ai_summaries")
    op.drop_index("ix_rate_snapshots_channel_pair_fetched", table_name="rate_snapshots")
    op.drop_table("rate_snapshots")
    op.drop_table("channels")
    op.drop_table("currencies")

"""Idempotent seed: currencies, channels (inactive), admin user, ai.* settings.

Run via:  docker compose exec backend python scripts/seed.py
or:       make seed
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.auth import hash_password
from app.config import get_settings
from app.db import SessionLocal
from app.models.admin_user import AdminUser
from app.models.channel import Channel
from app.models.currency import Currency
from app.services.settings import ensure_default

CURRENCIES = [
    {"code": "CNY", "name_en": "Chinese Yuan", "name_zh": "人民币"},
    {"code": "MYR", "name_en": "Malaysian Ringgit", "name_zh": "马来西亚林吉特"},
]

CHANNELS = [
    {
        "code": "midmarket",
        "name_en": "Mid-market (Frankfurter)",
        "name_zh": "中间市场汇率",
        "source_url": "https://api.frankfurter.dev/v1/latest?from=CNY&to=MYR",
    },
    {
        "code": "boc",
        "name_en": "Bank of China",
        "name_zh": "中国银行",
        "source_url": "https://www.boc.cn/sourcedb/whpj/",
    },
    {
        "code": "unionpay",
        "name_en": "UnionPay International",
        "name_zh": "银联国际",
        "source_url": "https://www.unionpayintl.com/upload/jfimg/",
    },
    {
        "code": "visa",
        "name_en": "Visa",
        "name_zh": "Visa",
        "source_url": "https://www.visa.com.my/support/consumer/travel-support/exchange-rate-calculator.html",
    },
    {
        "code": "mastercard",
        "name_en": "Mastercard",
        "name_zh": "万事达卡",
        "source_url": "https://www.mastercard.co.uk/en-gb/personal/get-support/convert-currency.html",
    },
    {
        "code": "wise",
        "name_en": "Wise",
        "name_zh": "Wise",
        "source_url": "https://api.wise.com/v1/rates?source=CNY&target=MYR",
    },
    {
        "code": "maybank",
        "name_en": "Maybank",
        "name_zh": "马来亚银行",
        "source_url": "https://www.maybank2u.com.my/foreign-exchange-rates",
    },
    {
        "code": "cimb",
        "name_en": "CIMB Bank",
        "name_zh": "联昌国际银行",
        "source_url": "https://www.cimb.com.my/en/personal/help-support/rates/foreign-exchange-counter-rates.html",
    },
]

DEFAULT_SYSTEM_PROMPT_ZH = """你是一个外汇市场分析助手，专门帮助在马来西亚的中国留学生理解人民币兑马币的汇率变化。
根据用户提供的数据，用一句话（不超过 80 字）总结今日趋势。
只描述事实，不给出"建议立即换汇""赶紧"等催促性建议。
不使用表情符号。语气平实。"""

# Note: ai.enabled defaults to "false" so a fresh install never tries to call
# an unconfigured endpoint. Admin flips it to "true" after filling base_url +
# api_key in /admin/ai.
AI_DEFAULTS: list[tuple[str, str]] = [
    ("ai.enabled", "false"),
    ("ai.base_url", ""),
    ("ai.api_key", ""),
    ("ai.model", "gpt-4o-mini"),
    ("ai.system_prompt", DEFAULT_SYSTEM_PROMPT_ZH),
    ("ai.temperature", "0.2"),
    ("ai.max_tokens", "120"),
    ("ai.schedule_cron", "0 9 * * *"),
    ("ai.daily_budget_usd", "0.10"),
    ("ai.cost_per_1k_input", "0.00015"),
    ("ai.cost_per_1k_output", "0.0006"),
]


async def seed() -> None:
    s = get_settings()
    async with SessionLocal() as session:
        # currencies
        for c in CURRENCIES:
            existing = await session.get(Currency, c["code"])
            if existing is None:
                session.add(Currency(**c))

        # channels: only midmarket starts active (Phase 4); admin flips the
        # rest on as their scrapers come online. For existing rows we still
        # refresh display fields (name_en / name_zh / source_url) so renaming
        # propagates on next boot — but `active` is left alone since admin
        # controls it after first run.
        for ch in CHANNELS:
            existing = await session.get(Channel, ch["code"])
            if existing is None:
                session.add(Channel(active=(ch["code"] == "midmarket"), **ch))
            else:
                existing.name_en = ch["name_en"]
                existing.name_zh = ch["name_zh"]
                existing.source_url = ch["source_url"]

        # ai.* defaults
        for key, value in AI_DEFAULTS:
            await ensure_default(session, key, value)

        # admin user
        if not s.admin_username:
            print("[seed] ADMIN_USERNAME is empty; skipping admin seed.", file=sys.stderr)
        else:
            existing = (
                await session.execute(
                    select(AdminUser).where(AdminUser.username == s.admin_username)
                )
            ).scalar_one_or_none()
            if existing is None:
                if not s.admin_password:
                    print(
                        "[seed] ERROR: no admin user yet, and ADMIN_PASSWORD is empty. "
                        "Set ADMIN_PASSWORD in .env, restart, then remove it after first login.",
                        file=sys.stderr,
                    )
                    raise SystemExit(2)
                session.add(
                    AdminUser(
                        username=s.admin_username,
                        password_hash=hash_password(s.admin_password),
                        created_at=datetime.now(UTC),
                    )
                )
                print(f"[seed] created admin user '{s.admin_username}'")
            else:
                print(f"[seed] admin user '{s.admin_username}' already exists; skip")

        await session.commit()
    print("[seed] done.")


if __name__ == "__main__":
    asyncio.run(seed())

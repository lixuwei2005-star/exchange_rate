from __future__ import annotations

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.settings import get_setting


async def get_client(session: AsyncSession) -> AsyncOpenAI:
    """Build an OpenAI-compatible async client from current DB settings.

    Works against any OpenAI-compatible endpoint (DeepSeek, Qwen DashScope,
    Anthropic compat, Moonshot, Zhipu, etc.) — see CLAUDE.md §10.
    """
    base_url = await get_setting(session, "ai.base_url")
    api_key = await get_setting(session, "ai.api_key")
    if not base_url or not api_key:
        raise RuntimeError("AI provider not configured (set ai.base_url and ai.api_key in admin).")
    return AsyncOpenAI(base_url=base_url, api_key=api_key)

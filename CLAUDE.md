# CLAUDE.md

> Project guide for **rate.005917.xyz**. Read this fully at the start of every Claude Code session before touching any code. When you make architectural decisions not covered here, update this file.

---

## 1. Project Overview

A web tool comparing **CNY → MYR** exchange rates across multiple channels (Chinese banks, card networks, remittance services) so Chinese students in Malaysia can pick the best way to convert money.

- **Direction (V1)**: Always **CNY → MYR**. User (or their family in China) starts with CNY and ends up with MYR.
- **Audience**: Chinese students in Malaysia. UI is **Simplified Chinese first**, English secondary.
- **Author**: Xuwei (UKM student, Bangi). Backend on Oracle Cloud Singapore (existing instance, BaoTa-managed Nginx).
- **Domain**: `rate.005917.xyz` (Cloudflare in front, Let's Encrypt SSL via BaoTa).
- **Repository**: code in English; comments may be Chinese where helpful. User-facing strings live in `frontend/lib/i18n/` and default to zh-CN.

---

## 2. Currency Direction & Terminology

**This is the most important section. Get this wrong and every number on the page is wrong. Implementations MUST follow this exactly.**

### 2.1 Use case

The user (or their parent in China) has **CNY** and ends up with **MYR**. We compare how many MYR they receive from the same CNY input across different channels.

### 2.2 Storage convention

In the database, every rate is stored as:

> **rate = MYR per 1 CNY** (always)

A typical value is around `0.65`. This means:

- `base_currency = "CNY"` (always in V1)
- `quote_currency = "MYR"` (always in V1)
- `myr_amount = cny_amount * rate`

Internal storage is **always** this direction, regardless of how the source channel quotes it. Scrapers are responsible for normalizing.

### 2.3 Display convention

The homepage headline shows `1 MYR = X.XXXX CNY` because that reads naturally for someone living in Malaysia. **This is purely a display transformation**: `display_value = 1 / rate`. The stored rate stays MYR-per-CNY.

User input: "我有 [N] CNY". Output column: "你能拿到 X MYR", where `X = N * rate * (1 - fee_pct) - flat_fee`.

### 2.4 Critical banking terminology (memorize these)

Always from the **bank's** perspective, not the customer's:

| Term       | Pinyin       | Meaning                                                                 |
|------------|--------------|-------------------------------------------------------------------------|
| 现汇        | xiànhuì      | Cash remittance — electronic money (wire, account balance)              |
| 现钞        | xiànchāo     | Cash banknote — physical paper money. Rates are worse than 现汇         |
| 买入价      | mǎirùjià     | Bid — bank **buys** foreign currency from you (you give foreign, get CNY) |
| 卖出价      | màichūjià    | Ask — bank **sells** foreign currency to you (you give CNY, get foreign) |
| 中行折算价   | zhōngháng zhésuànjià | Reference midpoint, no transaction, accounting only            |

**For CNY → MYR via a Chinese bank: always use 现汇卖出价 (ask)** — the bank is selling MYR to the customer in exchange for CNY.

For Malaysian banks (Maybank, CIMB) the perspective flips:

- They quote in MYR per foreign currency.
- For CNY → MYR, they are **buying** CNY from the customer and giving MYR.
- Use their **CNY TT Buying rate**. "TT" = telegraphic transfer (electronic). Avoid "Currency Notes" rates which are for physical cash and worse.

### 2.5 Per-channel normalization

Each scraper must return rate as **MYR per 1 CNY**. Reference:

| Channel    | Native quote                                  | Field for CNY→MYR                     | To stored rate (MYR per CNY) |
|------------|-----------------------------------------------|---------------------------------------|------------------------------|
| BOC        | CNY per 100 MYR, 4 columns                    | **现汇卖出价**                          | `100 / 现汇卖出价` |
| UnionPay   | Static daily JSON entry `1 transCur = rateData × baseCur` | entry `transCur=MYR, baseCur=CNY` | `1 / rateData` |
| Visa       | `originalValues.fxRateVisa` from cmsapi; **API silently swaps from/to** | trust `originalValues.fromCurrency/toCurrency`, invert if reversed | `fxRateVisa` (no markup) or `1 / fxRateVisa` if direction inverted |
| Mastercard | Similar to Visa                               | CNY → MYR                             | `response_rate` (no markup) |
| Wise       | JSON `{rate}` where 1 source unit = X target  | `source=CNY&target=MYR`               | `response_rate` (already correct) |
| CIMB       | MYR per N units foreign (section heading says `Per N Units of Foreign Currency`) | **CNY row Buying TT column ÷ multiplier** | `buying_tt / multiplier` (CNY is in the per-100 table → ÷100) |
| Public Bank | MYR per N units foreign (multiplier baked into row label, e.g. `100 Chinese Renminbi (Non Trade)`) | **CNY row Buying TT column ÷ multiplier** | `buying_tt / 100` |
| RHB        | MYR per `Unit` foreign; columns `Bank Sell TT/OD \| Bank Buy TT \| Bank Buy OD`; data rows split code+name so they have 1 extra cell vs header | **CNY row Bank Buy TT ÷ Unit** | `bank_buy_tt / 100` (sanity floor widened to 0.45 — RHB's CNY spread is unusually wide) |
| Hong Leong | MYR per N units foreign; **no header row** — each `<td>` is self-labelling (`<div class="left-col">LABEL</div><div class="right-col">VALUE</div>`); CNY row's name cell carries the basis `RINGGIT TO 100 UNITS OF FOREIGN CURRENCY` | **CNY row `Buying (TT)` ÷ multiplier** (match label exactly — row also has `Buying (OD/TC)` + a preferential `Buying`) | `buying_tt / 100` |
| Midmarket  | Frankfurter `base=CNY` → `rates.MYR`          | direct                                | `rates.MYR` |
| Midmarket 2 | exchangerate.fun `base=CNY` → `rates.MYR` (same shape as Frankfurter; verifies `response.base` echoes what we asked) | direct | `rates.MYR` |
| Midmarket 3 | exchangerate-api.com `/v6/{key}/latest/CNY` → `conversion_rates.MYR` (auth via `EXCHANGERATE_API_KEY` env; validates `result=='success'` and `base_code`) | direct | `conversion_rates.MYR` |

### 2.6 Sanity checks (write tests)

- Stored `rate` must be in `[0.5, 0.8]` (MYR per CNY). Outside → reject snapshot, log error.
- For 1000 CNY input, output MYR must be in `[500, 800]`. Outside → reject.
- Spread across channels (max rate − min rate) should be < 5% of mid. Wider → flag, do not auto-reject (could be a real event).

---

## 3. Scope

### V1 (current)

- Direction: **CNY → MYR only**. No toggle.
- Pair: CNY/MYR only.
- Homepage headline: `1 MYR = X.XXXX CNY` (mid-market reference).
- Comparison table: 6–8 channels, sortable, showing "你能拿到 X MYR" for input N CNY. Default input 1000 CNY.
- 30-day chart per channel.
- One-sentence AI trend summary in Chinese (regenerated on configurable cron, default daily).
- **Admin backend** (see §11).
- Mobile-responsive single public page. **No native app.**
- No public user accounts, no signup, no email.

### V2 (architect for, don't build)

- Other pairs (USD/MYR, SGD/MYR, HKD/CNY).
- Direction toggle (MYR → CNY).
- Email / Telegram alerts.
- User-submitted money changer rates.

**Data model and scraper interface must already support multi-currency from day 1.** Do not hardcode "CNY" / "MYR" as the only legal values in business logic — use the `currencies` table.

### Out of scope (never)

- Native apps.
- Actual money transfer.
- Named money changer recommendations (legal risk in MY/CN).
- Investment advice.

---

## 4. Tech Stack

| Layer        | Choice                                                                  |
|--------------|-------------------------------------------------------------------------|
| Backend      | Python 3.11 + FastAPI + pydantic-settings (env config)                  |
| DB           | SQLite (V1), migrate to Postgres in V2                                  |
| ORM          | SQLAlchemy 2.0 async                                                    |
| Migrations   | Alembic                                                                 |
| Scheduler    | APScheduler (in-process AsyncIOScheduler, timezone `Asia/Singapore`)    |
| HTTP client  | httpx async (default); `curl_cffi` only when a host blocks plain httpx via TLS/JA3 fingerprinting (Cloudflare JS challenges). Visa uses it. |
| HTML parse   | BeautifulSoup4 + lxml                                                   |
| Browser      | Playwright — **only** if HTTP-only + `curl_cffi` are both infeasible. Flag in PR. |
| AI client    | `openai` Python SDK (works with any OpenAI-compatible endpoint) — §10   |
| Crypto       | `cryptography` Fernet, for encrypting `settings.value` of API keys      |
| Auth (admin) | JWT in httpOnly cookie (PyJWT) + passlib[bcrypt], single admin user     |
| Rate limit   | slowapi                                                                 |
| Frontend     | Next.js 14 (App Router) + TypeScript strict                             |
| Styling      | Tailwind CSS (no CSS modules)                                           |
| Icons        | lucide-react                                                            |
| Charts       | Recharts                                                                |
| Tests (be)   | pytest + pytest-asyncio + respx                                         |
| Tests (fe)   | Vitest + Testing Library (test Client Components; RSC via Playwright)   |
| Lint/format  | Ruff + Black (Py); ESLint + Prettier (TS)                               |
| Deploy       | Docker Compose on OCI Singapore                                         |
| Proxy        | Nginx managed by BaoTa (config NOT in repo)                             |
| CDN          | Cloudflare                                                              |

**Do not introduce** Django, Flask, Vue, MongoDB, Redis, Celery, Kafka, or the `anthropic` SDK (we use OpenAI-compatible only — see §10). New deps require approval.

---

## 5. Repository Layout

```
rate-005917/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── auth.py                 # JWT helpers for admin
│   │   ├── crypto.py               # Fernet encrypt/decrypt for settings.value
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── api/
│   │   │   ├── public.py           # /api/rates/*, /api/summary, /api/health
│   │   │   └── admin.py            # /api/admin/* (auth required)
│   │   ├── scrapers/
│   │   │   ├── base.py
│   │   │   ├── boc.py
│   │   │   ├── unionpay.py
│   │   │   ├── visa.py
│   │   │   ├── mastercard.py
│   │   │   ├── wise.py
│   │   │   ├── maybank.py
│   │   │   ├── cimb.py
│   │   │   └── midmarket.py
│   │   ├── scheduler.py
│   │   └── services/
│   │       ├── summary.py          # AI summary generation
│   │       ├── conversion.py       # apply fees
│   │       ├── settings.py         # read/write encrypted settings
│   │       └── llm_client.py       # OpenAI-compatible client factory
│   ├── alembic/
│   ├── tests/
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                # public homepage
│   │   ├── admin/
│   │   │   ├── layout.tsx          # auth gate
│   │   │   ├── login/page.tsx
│   │   │   ├── page.tsx            # dashboard
│   │   │   ├── channels/page.tsx
│   │   │   ├── ai/page.tsx
│   │   │   └── logs/page.tsx
│   │   └── api/
│   ├── components/
│   │   ├── public/
│   │   │   ├── RateHeadline.tsx
│   │   │   ├── ChannelTable.tsx
│   │   │   ├── HistoryChart.tsx
│   │   │   └── AmountInput.tsx
│   │   └── admin/
│   │       ├── ChannelRow.tsx
│   │       └── AISettingsForm.tsx
│   ├── lib/
│   │   ├── api.ts
│   │   └── i18n/zh-CN.ts
│   ├── public/
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
├── Makefile
├── CLAUDE.md
└── README.md
```

---

## 6. Data Sources (V1)

See §2 for direction and field selection. URLs below are starting points — verify selectors at impl time.

| Channel        | Code         | Source URL                                                                                          | Refresh | Fragility |
|----------------|--------------|------------------------------------------------------------------------------------------------------|---------|-----------|
| Mid-market     | `midmarket`  | https://api.frankfurter.dev/v1/latest?from=CNY&to=MYR  (was `frankfurter.app/latest`, 301 since 2026-Q1) | 60 min  | Low |
| Mid-market 2   | `midmarket2` | https://api.exchangerate.fun/latest?base=CNY (FreeExchangeRateApi aggregator — independent of Frankfurter; lets us cross-check) | 60 min  | Low |
| Mid-market 3   | `midmarket3` | https://v6.exchangerate-api.com/v6/{key}/latest/CNY (key in `EXCHANGERATE_API_KEY` env; updates once per day per `time_next_update_unix`) | 60 min  | Low |
| Bank of China  | `boc`        | https://www.boc.cn/sourcedb/whpj/                                                                   | 15 min  | Med — HTML may change |
| UnionPay Intl  | `unionpay`   | GET https://www.unionpayintl.com/upload/jfimg/{YYYYMMDD}.json (static daily JSON)                   | daily 11:30 SGT | Low |
| Visa           | `visa`       | https://www.visa.com.my/cmsapi/fx/rates (Cloudflare-protected — use curl_cffi `impersonate='chrome124'`) | 30 min  | Med — Cloudflare JS challenge |
| Mastercard     | `mastercard` | https://www.mastercard.co.uk/en-gb/personal/get-support/convert-currency.html                       | 30 min  | Med |
| Wise           | `wise`       | POST https://api.wise.com/v3/quotes (unauthenticated quote)                                         | 10 min  | Low |
| CIMB           | `cimb`       | https://www.cimb.com.my/en/business/help-and-support/rates-charges/forex-rates.html (server-rendered HTML; the Per-100 wholesale table) | 3 h     | Low |
| Public Bank    | `publicbank` | https://www.pbebank.com/en/rates-charges/forex/ (server-rendered HTML; single forex table, multiplier in row label) | 3 h     | Low |
| RHB            | `rhb`        | https://www.rhbgroup.com/treasury-rates/foreign-exchange/index.html (server-rendered HTML; Cloudflare in front but serves plain GET; `Unit` column + code/name split rows) | 3 h     | Low |
| Hong Leong     | `hlb`        | https://www.hlb.com.my/en/global-markets/forex-rates.html (server-rendered HTML; plain GET works with the project UA — no Cloudflare/Akamai bot wall; self-labelling `left-col`/`right-col` cells, no header row) | 3 h     | Low |

> ⚠️ **Maybank was decommissioned 2026-05-28.** Akamai Bot Manager blocks plain server-side GET (HTTP 403) from OCI's data-center IP range. A Playwright + manual stealth tweaks attempt was implemented and verified end-to-end from OCI; Akamai still served an interstitial instead of the rate table (`'Chinese Renminbi' did not appear within 15s` in the diagnostic). Patchright / paid unblock services (ScrapingBee, ZenRows) were not pursued because CIMB covers the same Malaysian-bank data dimension cleanly. The Playwright-based Maybank scraper lives in git history at commits `f833360..baa596c` if anyone wants to revisit.

> ⚠️ "Refresh" above is our poll cadence, not how often the source itself publishes. Frankfurter is daily (ECB ~CET 16:00); Wise / banks change intraday; Maybank / CIMB update at most a couple of times per business day. Polling faster than the source updates is harmless (deduplicated by `(channel, fetched_at)` uniqueness conceptually — we store every snapshot but the displayed value just stays the same) but doesn't increase actual freshness.

> 📝 **Refresh cadence is per-channel and live-editable** since 2026-05-28. The values above are the *seed defaults* written to `channels.interval_minutes` / `channels.daily_time_cn` on first install. Admin can change either field via `/admin/channels` → "调度" without redeploying; the scheduler reschedules the job in place. `schedule_kind='daily'` runs `CronTrigger(hour, minute, timezone='Asia/Shanghai')` because every daily-style source (UnionPay, etc.) publishes on Beijing wall-clock. The constants `DEFAULT_INTERVAL_MINUTES` in `app/scheduler.py` is a last-resort fallback only.

### Fee model

Homepage shows each channel's pure published rate. No fees are applied or modeled.

---

## 7. Scraper Interface

```python
# backend/app/scrapers/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel

RateType = Literal[
    "bank_ask",      # Chinese bank selling foreign currency for CNY (CNY→foreign)
    "bank_bid",      # Chinese bank buying foreign currency, giving CNY (foreign→CNY)
    "tt_buy",        # MY bank buying foreign, giving MYR (foreign→MYR)
    "tt_sell",       # MY bank selling foreign for MYR (MYR→foreign)
    "card_network",  # Visa/MC/UnionPay network rate
    "p2p",           # Wise et al
    "midmarket",     # reference
]

class ScrapeResult(BaseModel):
    base_currency: str         # ISO 4217, e.g. "CNY"
    quote_currency: str        # ISO 4217, e.g. "MYR"
    rate: Decimal              # quote per 1 base (always normalized)
    rate_type: RateType
    raw_payload: dict          # original response, for debugging
    fee_estimate: Decimal | None = None
    fee_currency: str | None = None

class Scraper(ABC):
    channel_code: str
    timeout_seconds: int = 15

    @abstractmethod
    async def fetch(self, base: str, quote: str) -> ScrapeResult: ...
```

Rules:

- Raise `ScraperError` on any failure. Scheduler catches and logs; no retry within a tick.
- Respect 1 req/min ceiling per source. Don't be a jerk.
- `User-Agent: rate.005917.xyz contact: <Xuwei's email>`.
- **Never use proxies** to bypass IP blocks. If blocked, mark channel stale, log, surface in admin UI.
- After parsing: sanity check rate in expected range (see §2.6). If out of range, raise — likely parser bug.

---

## 8. Database Schema

SQLite for V1, written so Postgres migration is just a connection string change.

```python
# currencies
#   code        VARCHAR PK     # ISO 4217
#   name_en     VARCHAR
#   name_zh     VARCHAR

# channels
#   code              VARCHAR PK
#   name_en           VARCHAR
#   name_zh           VARCHAR
#   source_url        TEXT
#   active            BOOL
#   last_success_at   DATETIME NULL
#   last_error_at     DATETIME NULL
#   last_error_msg    TEXT NULL
#   schedule_kind     VARCHAR(16) NOT NULL DEFAULT 'interval'  # 'interval' | 'daily'
#   interval_minutes  INTEGER NULL                              # used when kind='interval'
#   daily_time_cn     VARCHAR(5) NULL                           # HH:MM, Asia/Shanghai

# rate_snapshots
#   id              INTEGER PK
#   channel_code    FK channels.code
#   base_currency   FK currencies.code     # "CNY" in V1
#   quote_currency  FK currencies.code     # "MYR" in V1
#   rate            DECIMAL(20,8)          # quote per 1 base, always
#   rate_type       VARCHAR                # see RateType literal
#   fee_estimate    DECIMAL(20,8) NULL
#   fee_currency    VARCHAR NULL
#   raw_payload     JSON
#   fetched_at      DATETIME

# ai_summaries
#   id              INTEGER PK
#   base_currency   FK
#   quote_currency  FK
#   summary_zh      TEXT
#   model_used      VARCHAR                # e.g. "gpt-4o-mini" or "qwen2.5:14b"
#   generated_at    DATETIME

# settings
#   key             VARCHAR PK             # e.g. "ai.api_key", "ai.model"
#   value           TEXT                   # JSON-encoded; encrypted if key matches sensitive pattern
#   is_encrypted    BOOL
#   updated_at      DATETIME

# admin_users
#   id              INTEGER PK
#   username        VARCHAR UNIQUE
#   password_hash   VARCHAR                # bcrypt
#   created_at      DATETIME
# Seeded with one user from ADMIN_USERNAME/ADMIN_PASSWORD env vars at first boot.

# scrape_logs
#   id              INTEGER PK
#   channel_code    FK NULL
#   level           VARCHAR                # info|warn|error
#   message         TEXT
#   created_at      DATETIME
```

Indexes:

- `rate_snapshots(channel_code, base_currency, quote_currency, fetched_at DESC)` — hot read path.
- `ai_summaries(base_currency, quote_currency, generated_at DESC)`.
- `scrape_logs(created_at DESC)`.

**Retention**: keep raw `rate_snapshots` for 90 days, then aggregate to daily means and drop originals. Write the aggregation job **before launch**. Keep `scrape_logs` 30 days.

**Encryption**: `settings.value` for keys matching `*.api_key`, `*.secret`, `*.password` is encrypted with Fernet. Encryption key in `.env` (`FERNET_KEY`). Decrypt only when needed in-process. Never log decrypted values. `is_encrypted` flag set automatically by `services/settings.py`.

---

## 9. API

### Public (no auth)

- `GET /api/rates/latest?base=CNY&quote=MYR`
  → `[{channel_code, rate, rate_type, fee_estimate, fee_currency, fetched_at, is_stale}]`
- `GET /api/rates/history?base=CNY&quote=MYR&channel=boc&days=30`
  → `[{date, rate}]`, one point per day (latest snapshot of that day).
- `GET /api/rates/intraday?base=CNY&quote=MYR&channel=wise&hours=72`
  → `[{time, rate}]`, **every** raw snapshot in the window (NOT day-bucketed), ascending, using the channel's headline rate. For the homepage's intraday Wise chart. `hours` ∈ [1, 168].
- `GET /api/summary?base=CNY&quote=MYR`
  → `{summary_zh, generated_at, model_used}`
- `GET /api/config`
  → `{headline_channel}` — which channel feeds the homepage hero. Sourced from the `display.headline_channel` setting (default `midmarket`). Non-sensitive presentation state, no auth.
- `GET /api/health`
  → `{ok, channels: {boc: "fresh"|"stale", ...}}`

### Admin (JWT cookie required)

- `POST /api/admin/login` — body `{username, password}`, sets httpOnly cookie.
- `POST /api/admin/logout`
- `GET  /api/admin/me`
- `GET  /api/admin/channels`
- `PATCH /api/admin/channels/{code}` — toggle active, update name/source_url.
- `POST /api/admin/channels/{code}/scrape-now` — fire and return immediately.
- `GET  /api/admin/settings` — return all settings; sensitive values masked as `"***"`.
- `PUT  /api/admin/settings/{key}` — body `{value}`. If sensitive, encrypt on write.
- `POST /api/admin/ai/test` — round-trip a 1-token ping against the configured LLM. Returns `{ok, latency_ms, model_used, error}`.
- `GET  /api/admin/summaries?limit=20`
- `POST /api/admin/summaries/regenerate` — kick off regen now.
- `GET  /api/admin/logs?limit=200&level=error`

CORS: `https://rate.005917.xyz` only. No `*`.

Rate limit (slowapi): 60 req/min/IP on public, 600 on admin.

---

## 10. AI Summary (swappable provider)

The AI provider is **configured at runtime via the admin backend**, not hardcoded. This lets Xuwei swap between OpenAI, Anthropic's OpenAI-compatible endpoint, DeepSeek, Qwen, Ollama on his RTX 5070 Ti, LM Studio, or any other OpenAI-compatible API without touching code.

### Settings keys (in `settings` table, edited via `/admin/ai`)

| Key                          | Example value                              | Encrypted | Notes |
|------------------------------|--------------------------------------------|-----------|-------|
| `ai.enabled`                 | `true`                                     | no        | Master switch |
| `ai.base_url`                | `https://api.openai.com/v1`                | no        | Should end with `/v1` per OpenAI SDK convention |
| `ai.api_key`                 | `sk-...`                                   | **yes**   | Never returned in plaintext |
| `ai.model`                   | `gpt-4o-mini`                              | no        | Must be valid for the configured endpoint |
| `ai.system_prompt`           | (default below, editable)                  | no        | Multi-line Chinese text |
| `ai.temperature`             | `0.2`                                      | no        | |
| `ai.max_tokens`              | `120`                                      | no        | Hard cap so summary stays short |
| `ai.schedule_cron`           | `0 9 * * *`                                | no        | When scheduler regenerates (SGT timezone) |
| `ai.daily_budget_usd`        | `0.10`                                     | no        | Soft cap; pauses regen when exceeded |
| `ai.cost_per_1k_input`       | `0.00015`                                  | no        | For budget estimation |
| `ai.cost_per_1k_output`      | `0.0006`                                   | no        | For budget estimation |

### Client (OpenAI-compatible)

```python
# backend/app/services/llm_client.py
from openai import AsyncOpenAI
from app.services.settings import get_setting

async def get_client() -> AsyncOpenAI:
    base_url = await get_setting("ai.base_url")
    api_key = await get_setting("ai.api_key")  # auto-decrypts
    return AsyncOpenAI(base_url=base_url, api_key=api_key)
```

The `openai` SDK transparently works against any OpenAI-compatible server. **Do not import the `anthropic` SDK** — one client interface only.

### Summary flow

1. Cron fires (or admin clicks "Regenerate now"), `services/summary.regenerate()` runs.
2. Pull last 30 days of daily-aggregated `boc` + `midmarket` rates.
3. Build a structured user message: today's rate, 7-day change %, 30-day change %, 30-day high/low.
4. Send `[system_prompt, user_message]` to the configured model with `max_tokens` cap.
5. Validate output: ≤ 80 Chinese characters, no emoji, no urgency words ("赶紧", "立刻", "立即"). On violation, retry once; if still bad, keep previous and log.
6. Persist with `model_used`.

### Default system prompt (zh)

```
你是一个外汇市场分析助手，专门帮助在马来西亚的中国留学生理解人民币兑马币的汇率变化。
根据用户提供的数据，用一句话（不超过 80 字）总结今日趋势。
只描述事实，不给出"建议立即换汇""赶紧"等催促性建议。
不使用表情符号。语气平实。
```

### Budget guard

Track per-day cumulative cost in a small in-memory counter (reset at SGT 00:00). If `cost_today > ai.daily_budget_usd`, skip regen and log. Admin can bump the cap from the UI.

---

## 11. Admin Backend

### Goals

- Manage channels, AI config, and inspect errors **without SSHing into the server or editing the DB directly**.
- Simple, ugly, functional. Tailwind defaults are fine; no design polish.

### Pages

| Route               | Purpose                                                                |
|---------------------|------------------------------------------------------------------------|
| `/admin/login`      | Username + password form. POSTs to `/api/admin/login`, redirects.       |
| `/admin`            | Dashboard. Cards: snapshots today, stale channels, last AI summary, recent errors. |
| `/admin/channels`   | Top: **首页大数字汇率来源** selector — picks which active channel feeds the homepage hero (writes `display.headline_channel`). Below: table of code, name_zh, status (fresh/stale/disabled), schedule (每 N 分钟 / 每天 HH:MM 东八区), last success, last error, [调度] inline editor, [Active] toggle, [Scrape now]. Editing schedule re-registers the APScheduler job in place — no restart needed. |
| `/admin/ai`         | Form for all `ai.*` settings. API key field shows `***`; only POSTs new value if user types. [Test connection] button. [Regenerate now]. Shows last 5 summaries. |
| `/admin/logs`       | Last 200 scrape_logs rows, filter by level. Text dump, no fancy viewer. |

### Auth flow

- Single admin user. Seeded at first boot from `ADMIN_USERNAME` + `ADMIN_PASSWORD` env vars (the latter bcrypt-hashed and stored, then the env var should be removed by Xuwei).
- Login returns JWT in httpOnly + Secure + SameSite=Lax cookie. 7-day expiry, sliding refresh on activity.
- Frontend middleware on `/admin/*` redirects to `/admin/login` when no valid cookie.
- Backend middleware on `/api/admin/*` returns 401 when no valid JWT.
- **No password reset** in V1. To reset: SSH in, delete admin user row, set env vars, restart.

### Security

- API keys are encrypted at rest (see §8 encryption note).
- `/api/admin/settings` GET masks any value where `is_encrypted=true` as `"***"`.
- `PUT /api/admin/settings/{key}`: if body is empty string or `"***"`, no-op (means "user didn't change it"). Otherwise encrypt and store.
- HTTPS-only cookies. Behind Cloudflare in production.
- Never log request bodies for `/api/admin/settings*` — they contain secrets.
- Consider Cloudflare Turnstile on `/admin/login` from day 1 (see §17).

---

## 12. Frontend (public homepage)

Server Component with `revalidate = 300` (5 min ISR). A Client Component handles the amount input and chart channel selector.

Mobile-first layout:

1. Header: site title, "数据更新于 N 分钟前", GitHub link.
2. Hero: `1 MYR = X.XXXX CNY` — large. Sourced from the admin-selected `display.headline_channel` (default `midmarket`, fetched via `/api/config`); the label above the number is that channel's `name_zh`. Falls back to midmarket if the chosen channel has no fresh snapshot.
3. Input: "我有 [____] CNY，能换多少 MYR？" — number input, default 1000, debounce 300ms, persists in localStorage.
4. AI summary: one sentence, italic gray, under hero.
5. Comparison table: sortable by "你能拿到". Columns: 渠道, 汇率 (CNY per MYR for display), 手续费, 你能拿到 (MYR), 更新于. Stale rows greyed out with "暂时不可用".
6. Charts: three stacked line charts. Top: **实时趋势** — intraday Wise line with a **24h / 72h toggle** (`/api/rates/intraday`, seeded by `scripts/backfill_wise.py`, kept fresh by the 10-min scraper; numeric time x-axis). Below it: **近 30 日趋势** (days=30) and **近一年趋势** (days=365) — hover tooltip. The two daily/yearly charts use **Single source: UnionPay International** (no channel tab strip) — UnionPay publishes a per-date JSON so history can be backfilled immediately (`scripts/backfill_unionpay.py --days 365`) instead of waiting for the scraper to accumulate it. Plotted as `1 MYR = X CNY` (= 1 / stored MYR-per-CNY rate). Lifecycle: backfill a year **once**, then the daily UnionPay cron appends each new day; the charts just window to the last N days. Retention (§8) only collapses *intra-day duplicates*, and UnionPay has one snapshot/day, so daily points survive indefinitely — no re-backfill needed.
7. Footer: disclaimer (§13), data sources list, last-updated.

**No analytics, no tracking, no Google Fonts, no third-party scripts.** Cloudflare's built-in analytics only.

---

## 13. Constraints, Gotchas, Legal

- **Disclaimer (footer, always visible)**: "本站汇率数据仅供参考，实际换汇以各渠道实时报价为准。本站不构成任何金融建议，不推荐特定换汇渠道。"
- **Show staleness**: every row shows "更新于 N 分钟前" or "暂时不可用". Never silently present 6-hour-old data as current.
- **Graceful degradation**: if all scrapers fail, show last good data with banner "数据更新延迟". Never a 500 on `/`.
- **Privacy**: zero third-party trackers. Self-host fonts.
- **Robots**: allow `/`, disallow `/admin`, `/api`. Submit sitemap after launch.
- **No proxy rotation, no UA rotation, no scraping abuse**: if blocked, mark stale, log, surface in admin.
- **No named money changer recommendations**: legal risk in MY (BNM) and CN (外管). Stick to publishable rates only.

---

## 14. Commands (Makefile)

```
make dev                    # docker-compose up with hot reload
make backend                # uvicorn locally outside docker
make frontend               # next dev locally
make test                   # pytest + vitest
make lint                   # ruff + black --check + eslint + prettier --check
make fmt                    # ruff --fix + black + prettier --write
make migrate                # alembic upgrade head
make seed                   # populate currencies + channels + admin user
make scrape-once            # run all scrapers once
make scrape CHANNEL=boc     # one channel only
make backfill-unionpay      # backfill UnionPay's last 30 days into history (idempotent)
make backfill-wise          # backfill Wise's recent hourly history (idempotent)
make summary-now            # regenerate AI summary now using current admin settings
make logs                   # tail backend logs in production
make deploy                 # ssh OCI, git pull, docker compose up -d --build
```

Add docs to this section when introducing new commands.

---

## 15. Conventions

### Python
- Black, line length 100.
- Ruff with `select = ["E", "F", "I", "B", "UP", "ASYNC"]`.
- Type hints on all public functions. `from __future__ import annotations` at top of every file.
- `Decimal` for money/rates. **Never floats.**
- Async everywhere. No `requests`, no `time.sleep`.

### TypeScript
- `strict: true`, `noUncheckedIndexedAccess: true`.
- No `any`. Use `unknown` + narrowing.
- Server Components by default; `"use client"` only when needed.

### Git
- Commits in English, imperative ("Add BOC scraper").
- Branches: `feat/...`, `fix/...`, `chore/...`.
- One logical change per PR.

### Comments
- Comment **why**, not what.
- Every magic constant: source + date + `# TODO recheck-YYYY-MM`.

---

## 16. Common Tasks (recipes)

### Add a new channel
1. Add to seed: `channels(code, name_en, name_zh, source_url, active=True)`.
2. Create `backend/app/scrapers/<code>.py` extending `Scraper`. **Return rate as MYR per 1 CNY** (or generally, quote per 1 base).
3. Register in `scheduler.py` rotation.
4. Add fee constant in `services/conversion.py` with source comment.
5. Add channel logo SVG to `frontend/public/channels/<code>.svg` (optional, monochrome).
6. Add unit test with `respx` mocking the HTTP source.
7. Update §6 of this file.

### Swap the AI provider
1. Go to `/admin/ai`.
2. Edit `base_url`, `api_key` (paste new value to overwrite), `model`. Save.
3. Click **Test connection** — should round-trip a 1-token ping in < 5s.
4. Click **Regenerate now**. Check `/admin/logs` if it fails.

Examples (project deploys to OCI Singapore — all providers below are cloud-hosted; local-model setups are out of scope):

- **OpenAI**: `base_url=https://api.openai.com/v1`, `model=gpt-4o-mini`.
- **Anthropic via OpenAI-compat**: `base_url=https://api.anthropic.com/v1/`, `model=claude-haiku-4-5-20251001`. Verify the exact compat URL and auth header at impl time.
- **DeepSeek**: `base_url=https://api.deepseek.com/v1`, `model=deepseek-chat`. Cheap, Chinese-friendly.
- **Alibaba DashScope (Qwen)**: `base_url=https://dashscope.aliyuncs.com/compatible-mode/v1`, `model=qwen-turbo`. Works well from China-region servers if you ever move there.
- **Moonshot Kimi**: `base_url=https://api.moonshot.cn/v1`, `model=moonshot-v1-8k`.
- **Zhipu GLM**: `base_url=https://open.bigmodel.cn/api/paas/v4/`, `model=glm-4-flash`.

For the short Chinese trend-summary use case, the smallest/cheapest tier of any of these is fine. Quality difference is invisible in a one-sentence output.

### Add a new currency pair (V2 prep)
1. Insert rows into `currencies`.
2. Verify each scraper's `fetch(base, quote)` handles the new pair — most need per-pair logic.
3. Frontend: move single page to `/[base]/[quote]/page.tsx` dynamic route.

### Debug a broken scraper
1. `make scrape CHANNEL=boc` and watch logs.
2. Inspect `raw_payload` in latest `rate_snapshots` row.
3. If source HTML changed: update parser. **Never** silently fall back to a different source for the same channel code.

### Reset admin password
1. SSH to server.
2. `docker compose exec backend python -c "from app.models import AdminUser; ..."` (or run a small script that deletes the row).
3. Set `ADMIN_USERNAME` / `ADMIN_PASSWORD` in `.env`, `docker compose up -d` — seeder will recreate.
4. Remove the plaintext password from `.env` after first login.

---

## 17. Open Questions

- Logo fair use for bank/network logos in the comparison table — likely OK if small, monochrome, and linking to source.
- Cloudflare Turnstile on `/admin/login` — probably yes from day 1.
- Publish raw snapshot data as CSV/JSON download for transparency?

When answered, delete from here and move the decision to the relevant section above.

---

**Last updated**: 2026-05-27 (revision 3 — dropped local-LLM examples, added Alibaba/Moonshot/Zhipu cloud options)

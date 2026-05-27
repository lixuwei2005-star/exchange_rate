# Prompt 01 — Project Skeleton

> Paste this as your first message to Claude Code in the `rate-005917` repo, after placing `CLAUDE.md` at the repo root.

---

## Task

Read `CLAUDE.md` fully before writing any code. Then build the **project skeleton** — a working, runnable shell that everything else will be added to. **Do not implement scrapers or AI in this task.**

## Goal

A repo where, after one `cp .env.example .env` and `make dev`, both backend and frontend boot cleanly, the database is created and seeded, and I can log into the admin panel and see a placeholder dashboard.

## In scope (build this)

1. **Repo files**
   - `docker-compose.yml` — backend + frontend services with hot reload, named volumes for SQLite and `node_modules`.
   - `Makefile` — every command listed in CLAUDE.md §14. For commands that depend on not-yet-built code (scrape, summary), implement as a placeholder that exits with a clear "not implemented yet" message rather than failing weirdly. `make logs` in this skeleton = `docker compose logs -f backend` (the §14 comment about "production" is a future concern; leave a TODO for the prod variant). Also add `make fernet-key` (see `.env.example` note above).
   - `.env.example` — every env var the code reads, with comments. Include a valid placeholder `FERNET_KEY` (any real Fernet key works; comment "REGENERATE before deploy — see `make fernet-key`"). `ADMIN_USERNAME=admin`, `ADMIN_PASSWORD=changeme`. Also include `ENV=dev` (controls cookie `Secure` flag and CORS allowlist) and `CORS_ALLOW_ORIGINS=http://localhost:3000` (comma-separated; in prod set to `https://rate.005917.xyz`).
   - Makefile must include `make fernet-key` → prints `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` output so Xuwei can paste it into `.env`.
   - `README.md` — ~40–60 lines. Quickstart (`cp .env.example .env && make dev`), point to `CLAUDE.md` for everything else.
   - `.gitignore` — Python + Node + SQLite + `.env` + IDE files.
   - `.editorconfig` — basic.

2. **`backend/`**
   - `pyproject.toml` with all deps from CLAUDE.md §4 (fastapi, sqlalchemy 2.0, alembic, httpx, beautifulsoup4, lxml, openai, cryptography, PyJWT, passlib[bcrypt], pydantic-settings, apscheduler, slowapi, respx, pytest, pytest-asyncio, ruff, black).
   - `Dockerfile` — Python 3.11-slim, multi-stage if it helps cache.
   - `app/main.py` — FastAPI app, slowapi rate limiter mounted. **CORS:** read allowlist from `CORS_ALLOW_ORIGINS` env (comma-separated). Dev default includes `http://localhost:3000`; prod sets it to `https://rate.005917.xyz`. `allow_credentials=True` is required so the admin cookie works across the dev `:3000 → :8000` origins. **Never** use `allow_origins=["*"]` — incompatible with `allow_credentials=True` and forbidden per §9.
   - `app/config.py` — pydantic-settings reading from env.
   - `app/db.py` — async SQLAlchemy engine + session factory.
   - `app/crypto.py` — Fernet wrapper for encrypting/decrypting settings values.
   - `app/auth.py` — bcrypt password hashing (passlib), JWT encode/decode (PyJWT), dependency for protecting admin routes. **Cookie attributes are env-driven:** `Secure=True` only when `ENV != "dev"` (otherwise the cookie won't be set over `http://localhost`), `HttpOnly=True` always, `SameSite="Lax"`, 7-day expiry. Login endpoint sets cookie; logout clears it.
   - `app/models/` — SQLAlchemy 2.0-style models for **every table in §8** (currencies, channels, rate_snapshots, ai_summaries, settings, admin_users, scrape_logs). Indexes per §8.
   - `app/schemas/` — Pydantic response models for everything in §9.
   - `app/api/public.py` — implement `/api/health` (returns `{ok: true, channels: {}}` — channels map empty since none are fresh yet). Stub `/api/rates/latest`, `/api/rates/history`, `/api/summary` returning `503` with `{"detail": "not implemented yet"}`.
   - `app/api/admin.py` — implement `/api/admin/login`, `/logout`, `/me` properly. Stub the rest with `501` responses; include all routes from §9 so the frontend has something to call.
   - `app/services/settings.py` — read/write to `settings` table with automatic Fernet encrypt/decrypt when the key matches `*.api_key`, `*.secret`, or `*.password`. Set `is_encrypted` flag on write.
   - `app/services/llm_client.py` — factory returning an `AsyncOpenAI` instance built from current DB settings. Don't call it from anywhere yet; just have it ready.
   - `app/services/summary.py`, `app/services/conversion.py` — empty stubs with `raise NotImplementedError`.
   - `app/scrapers/base.py` — `Scraper` ABC and `ScrapeResult` Pydantic model exactly as in §7.
   - `app/scrapers/{boc,unionpay,visa,mastercard,wise,maybank,cimb,midmarket}.py` — each subclasses `Scraper` and raises `NotImplementedError` in `fetch()`. Set `channel_code` correctly.
   - `app/scheduler.py` — `AsyncIOScheduler(timezone="Asia/Singapore")` (server is in Singapore; `ai.schedule_cron` in §10 is SGT). Import all scrapers but **does not schedule them yet** (TODO comment + empty rotation list).
   - `alembic/` — initial migration creating all tables.
   - `scripts/seed.py` — seeds `currencies` (CNY, MYR), `channels` (all 8 from §6 with `active=False`), one admin user from env vars (skip if already exists; error clearly if env vars missing on first run), and default `settings` rows for every `ai.*` key in §10. Defaults: `ai.enabled=false` (so a fresh install never calls an unconfigured endpoint), `ai.model=gpt-4o-mini`, `ai.base_url=""` (admin must set), `ai.api_key=""`, `ai.temperature=0.2`, `ai.max_tokens=120`, `ai.schedule_cron="0 9 * * *"`, `ai.system_prompt=` the Chinese default from §10, `ai.daily_budget_usd=0.10`, `ai.cost_per_1k_input=0.00015`, `ai.cost_per_1k_output=0.0006`.
   - `tests/` — at least one passing test per module: `test_health.py`, `test_auth.py` (hashes a password, encodes a JWT, round-trips), `test_settings_encryption.py` (encrypts then decrypts), `test_scraper_base.py` (`ScrapeResult` validates).
   - Ruff + Black config in `pyproject.toml`.

3. **`frontend/`**
   - `package.json` — Next.js 14, TypeScript strict, Tailwind, Recharts, `lucide-react` for icons.
   - `Dockerfile` — Node 20-alpine, dev mode.
   - `tsconfig.json` — strict, `noUncheckedIndexedAccess`.
   - `tailwind.config.ts` — standard.
   - `app/layout.tsx` — root layout with `<html lang="zh-CN">`, system font stack (no Google Fonts per §13).
   - `app/page.tsx` — placeholder homepage, Server Component. Imports a small `<SiteTitle>` **Client Component** (extracted so Vitest can render it — RSC are not testable by Vitest) showing `汇率对比 · rate.005917.xyz`, plus inline "敬请期待" and the disclaimer text from §13 in the footer. All user-facing strings imported from `lib/i18n/zh-CN.ts`.
   - `lib/i18n/zh-CN.ts` — set up the i18n convention from day 1 per CLAUDE.md §1. Export at minimum: `siteTitle`, `comingSoon`, `disclaimer` (the §13 footer text). Subsequent prompts will extend this file rather than hard-coding strings.
   - `app/admin/layout.tsx` — Server Component auth gate: reads the JWT cookie from `cookies()` (Next.js `next/headers`), forwards it as a `Cookie` header when calling backend `/api/admin/me`, redirects to `/admin/login` on 401. **Key point:** Server Components run inside the docker container and reach the backend via `BACKEND_URL_INTERNAL` (e.g. `http://backend:8000`); they do NOT have automatic access to the user's cookie, so it must be read and forwarded explicitly. Never set `cache: 'force-cache'` on admin fetches.
   - `app/admin/login/page.tsx` — Client Component, simple form. `fetch(NEXT_PUBLIC_BACKEND_URL + '/api/admin/login', { method: 'POST', credentials: 'include', ... })` so the backend can set the cookie on the browser. Browser must reach backend at a URL it can see (`http://localhost:8000` in dev). On success redirect to `/admin`. Show error on failure.
   - `app/admin/page.tsx` — dashboard placeholder. Shows "Hello, {username}" and a logout button (logout calls backend with `credentials: 'include'`). No real data yet.
   - `app/admin/channels/page.tsx`, `app/admin/ai/page.tsx`, `app/admin/logs/page.tsx` — placeholder pages saying "Coming soon". Auth-gated via shared layout.
   - `lib/api.ts` — typed fetch wrapper. **Two base URLs:** `BACKEND_URL_INTERNAL` for Server Component / server-side fetches (default `http://backend:8000` in docker, `http://localhost:8000` outside docker), and `NEXT_PUBLIC_BACKEND_URL` for browser-side fetches (default `http://localhost:8000` in dev; in prod both collapse to the same public origin behind Nginx). The wrapper picks the right one based on `typeof window`. All admin calls go through this wrapper with `credentials: 'include'` (browser) or explicit `Cookie` header forwarding (server).
   - `middleware.ts` — Next.js middleware that runs on `/admin/*` paths and redirects to `/admin/login` if no JWT cookie is present (cheap pre-check; backend still verifies on every admin API call).
   - Tests: one Vitest test that renders the `<SiteTitle>` **Client Component** (not the homepage RSC, which Vitest cannot render) and asserts the title text from `lib/i18n/zh-CN.ts` appears.
   - ESLint + Prettier configs.

## Out of scope (DO NOT BUILD)

- Any scraper logic. The scraper files exist as stubs only.
- Any AI integration. `llm_client.py` exists but is never invoked.
- Real homepage UI (the comparison table, chart, AI summary). Just the placeholder.
- Real admin pages beyond login + dashboard placeholder + auth gates.
- Nginx config, Cloudflare config, OCI deploy scripts. Production stuff is out of repo.
- Fee calculations.
- Sample data generation. Only seed `currencies`, `channels` (inactive), `admin_users`, and `settings` defaults.

## Definition of done

Run through this checklist and confirm every line in your final reply:

1. `cp .env.example .env` is the only manual step before `make dev`.
2. `make dev` brings backend up on `:8000` and frontend up on `:3000` with hot reload working.
3. `curl http://localhost:8000/api/health` → `200` with `{"ok": true, "channels": {}}`.
4. Browser at `http://localhost:3000` shows the placeholder homepage with title + disclaimer.
5. Browser at `http://localhost:3000/admin` (not logged in) redirects to `/admin/login`.
6. Logging in with seeded admin credentials sets a cookie and redirects to `/admin`, which shows "Hello, admin" + logout button.
7. Wrong password shows an error message and no cookie is set.
8. Logout clears the cookie and redirects to login.
9. `make migrate` is idempotent (re-running does nothing harmful).
10. `make seed` is idempotent (re-running doesn't duplicate rows or fail on existing admin user).
11. `make test` passes.
12. `make lint` passes (Ruff + Black + ESLint + Prettier all clean).
13. SQLite file is created at a path mounted as a docker volume so it survives container restarts.
14. All tables from CLAUDE.md §8 exist in the DB after `make migrate`.
15. `currencies` has CNY + MYR; `channels` has all 8 from §6 with `active=False`; `admin_users` has the one user; `settings` has all `ai.*` keys with empty/default values (and `ai.enabled=false`).
16. `docker compose down -v && make dev` from a completely clean state (no volumes, no cached SQLite) still satisfies items 1–15. No hidden state required.
17. After login, navigating between `/admin`, `/admin/channels`, `/admin/ai`, `/admin/logs` works without re-login (cookie is honored on every admin API call, server-side and client-side).

## Working style

- Read CLAUDE.md first. If something there is unclear or you think it's wrong, **flag it before working around it** — don't silently deviate.
- Don't add deps that aren't listed in CLAUDE.md §4 without flagging. If you genuinely need one, ask.
- Keep TS simple. No fancy generics, no over-engineered abstractions. This is a small project.
- For Python: `Decimal` for money, `async` everywhere, type hints, `from __future__ import annotations` at top of every file (§15).
- Commit after each logical chunk with conventional commit messages (e.g. `feat(backend): add JWT auth and login endpoint`). Don't push — Xuwei will review locally.
- After every major step (backend boots, frontend boots, login works end-to-end), run `make test` and `make lint`. Fix immediately rather than batching.
- If you finish and any item in "Definition of done" doesn't pass, **say so explicitly** in your final reply. Don't claim done if it isn't.

## Suggested order

1. Repo-level files (`Makefile`, `docker-compose.yml`, `.env.example`, `README.md`, `.gitignore`).
2. Backend: `pyproject.toml` → FastAPI hello world → DB models → Alembic migration → seed script. Verify `make migrate && make seed` runs cleanly.
3. Backend: auth (bcrypt + JWT + login/logout/me endpoints + admin dependency). Verify with curl.
4. Backend: stub all other endpoints. Verify they return 501.
5. Backend: scraper stubs + scheduler shell.
6. Backend: tests + lint config. Verify `make test && make lint`.
7. Frontend: `package.json` → Tailwind + Next.js base → root layout → placeholder homepage. Verify in browser.
8. Frontend: `/admin/login` form → `/admin` dashboard → auth middleware. Verify login flow end-to-end.
9. Frontend: stub `/admin/channels`, `/admin/ai`, `/admin/logs` pages.
10. Frontend: Vitest + ESLint config. Verify `make test && make lint`.
11. Final full `make dev` from clean state. Walk through every line of "Definition of done" and confirm.

## When you finish

Reply with:
1. A short summary of what was built (one paragraph).
2. The "Definition of done" checklist with ✅ or ❌ next to each item, and an explanation for any ❌.
3. Any decisions you made that aren't in CLAUDE.md, so Xuwei can update the doc.
4. Suggested next prompt: build the `midmarket` scraper (simplest source — Frankfurter JSON API) **plus the full wire-up end-to-end**: scheduler ticks the scraper → writes a `rate_snapshots` row → `/api/rates/latest` reads it back → admin "Scrape now" button triggers it manually. This gives one complete vertical slice; subsequent channels then just slot into the existing pipe.

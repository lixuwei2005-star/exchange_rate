.PHONY: dev backend frontend test lint fmt migrate seed scrape-once scrape summary-now logs deploy fernet-key down clean help prod prod-down prod-logs prod-backend-rebuild

# Default target: show help.
help:
	@echo "rate.005917.xyz — common targets"
	@echo ""
	@echo "  make dev          docker compose up (backend + frontend, hot reload)"
	@echo "  make down         docker compose down"
	@echo "  make clean        down + remove named volumes (DESTRUCTIVE)"
	@echo ""
	@echo "  make backend      run backend locally (uvicorn, outside docker)"
	@echo "  make frontend     run frontend locally (next dev)"
	@echo ""
	@echo "  make migrate      alembic upgrade head"
	@echo "  make seed         populate currencies + channels + admin + ai.* settings"
	@echo ""
	@echo "  make test         pytest + vitest"
	@echo "  make lint         ruff + black --check + eslint + prettier --check"
	@echo "  make fmt          ruff --fix + black + prettier --write"
	@echo ""
	@echo "  make scrape-once       (Phase 2+) run all scrapers once"
	@echo "  make scrape CHANNEL=x  (Phase 2+) run one scraper"
	@echo "  make summary-now       (Phase 6+) regenerate AI summary now"
	@echo ""
	@echo "  make logs         docker compose logs -f backend"
	@echo "  make deploy       ssh OCI, git pull, docker compose up -d --build"
	@echo "  make fernet-key   generate a new Fernet key (paste into .env)"
	@echo ""
	@echo "  --- prod-only (run on the OCI server) ---"
	@echo "  make prod-backend-rebuild  rebuild + restart ONLY backend (preserves frontend)"

# ---------------------------------------------------------------------------
# Dev orchestration
# ---------------------------------------------------------------------------

dev:
	docker compose up --build

down:
	docker compose down

clean:
	docker compose down -v

# Production launch (on the OCI server, not your laptop).
prod:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

prod-down:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml down

prod-logs:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f --tail=200

# Rebuild + restart ONLY backend; frontend container is left running.
prod-backend-rebuild:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build backend

# ---------------------------------------------------------------------------
# Local (non-docker) runs
# ---------------------------------------------------------------------------

backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm run dev

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

migrate:
	docker compose exec backend alembic upgrade head

seed:
	docker compose exec backend python scripts/seed.py

# ---------------------------------------------------------------------------
# Tests + lint
# ---------------------------------------------------------------------------

test:
	cd backend && pytest -q
	cd frontend && npm test -- --run

lint:
	cd backend && ruff check . && black --check .
	cd frontend && npx eslint . --ext .ts,.tsx && npx prettier --check .

fmt:
	cd backend && ruff check --fix . && black .
	cd frontend && npx prettier --write .

# ---------------------------------------------------------------------------
# Scraper / AI placeholders — will be wired up in later phases.
# ---------------------------------------------------------------------------

scrape-once:
	docker compose exec backend python -c "import asyncio; from app.services.scraping import run_scraper; from app.scrapers import ALL_SCRAPERS; asyncio.run(asyncio.gather(*(run_scraper(c) for c in ALL_SCRAPERS)))"

scrape:
	@if [ -z "$(CHANNEL)" ]; then echo "usage: make scrape CHANNEL=boc"; exit 2; fi
	docker compose exec backend python -c "import asyncio; from app.services.scraping import run_scraper; print(asyncio.run(run_scraper('$(CHANNEL)')))"

summary-now:
	docker compose exec backend python -c "import asyncio; from app.services.summary import regenerate; r=asyncio.run(regenerate('CNY','MYR')); print(r.summary_zh if r else 'no output (see /admin/logs)')"

# ---------------------------------------------------------------------------
# Ops
# ---------------------------------------------------------------------------

logs:
	docker compose logs -f backend
	# Note: prod variant (tail systemd-journal / Nginx) is a TODO once deployed.

deploy:
	@echo "[not implemented yet] deploy = ssh OCI && git pull && docker compose up -d --build. (Phase 10+)"
	@exit 1

# ---------------------------------------------------------------------------
# Secrets helper
# ---------------------------------------------------------------------------

fernet-key:
	@python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

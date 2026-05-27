.PHONY: dev backend frontend test lint fmt migrate seed scrape-once scrape summary-now logs deploy fernet-key down clean help

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

# ---------------------------------------------------------------------------
# Dev orchestration
# ---------------------------------------------------------------------------

dev:
	docker compose up --build

down:
	docker compose down

clean:
	docker compose down -v

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
	@echo "[not implemented yet] scrape-once will run all active scrapers once. (Phase 4+)"
	@exit 1

scrape:
	@if [ -z "$(CHANNEL)" ]; then echo "usage: make scrape CHANNEL=boc"; exit 2; fi
	@echo "[not implemented yet] scrape CHANNEL=$(CHANNEL). (Phase 4+)"
	@exit 1

summary-now:
	@echo "[not implemented yet] summary-now regenerates the AI summary. (Phase 6+)"
	@exit 1

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

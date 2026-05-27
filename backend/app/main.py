from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api.admin import router as admin_router
from app.api.public import router as public_router
from app.config import get_settings
from app.scheduler import shutdown as scheduler_shutdown
from app.scheduler import start as scheduler_start

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler_start()
    try:
        yield
    finally:
        scheduler_shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Rate limiter (CLAUDE.md §9). Public uses default 60/min; admin 600/min.
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):  # type: ignore[override]
    return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)


# CORS — strict allowlist driven by env (§9 + the dev/prod split in CLAUDE.md).
# `allow_credentials=True` is required so the admin cookie works on cross-origin
# dev (localhost:3000 -> localhost:8000). With credentials, "*" is forbidden.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(public_router)
app.include_router(admin_router)


@app.get("/")
async def root() -> dict:
    return {"ok": True, "service": settings.app_name}

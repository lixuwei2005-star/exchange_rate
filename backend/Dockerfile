FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# System deps for lxml + cryptography
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential libxml2-dev libxslt1-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e ".[dev]"

# Install Chromium for the maybank scraper. --with-deps pulls in the apt
# packages Chromium needs (libnss3, libatk1.0-0, libgtk-3-0, libxss1, etc.).
# This adds ~500 MB to the image. If you don't need maybank, you can drop
# this RUN line and the scraper will fall back to its httpx path (which is
# blocked by Akamai from OCI, but works in other environments).
RUN python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN mkdir -p /data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

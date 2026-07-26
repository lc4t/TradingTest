FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_PREFERENCE=only-system \
    UV_NO_SYNC=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates build-essential \
 && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --upgrade pip && pip install uv

# Install Python deps first for better layer caching.
# .python-version is copied here so the build-time venv matches what
# `uv run` will resolve at runtime — avoiding a venv rebuild on first run.
# README.md is included because pyproject.toml's `readme = ...` requires it.
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --no-dev --frozen --no-install-project

# Copy the rest of the backend
COPY . .
# Install the trading package itself now that source is in place.
RUN uv sync --no-dev --frozen

# The frontend is deployed separately; keep the image lean.
RUN rm -rf frontend tests

CMD ["uv", "run", "python", "fetcher.py", "--help"]

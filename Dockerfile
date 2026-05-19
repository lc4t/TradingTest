FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates build-essential \
 && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --upgrade pip && pip install uv

# Install Python deps first for better layer caching
COPY pyproject.toml ./
COPY uv.lock* ./
RUN uv sync --no-dev --frozen || uv sync --no-dev

# Copy the rest of the backend
COPY . .

# Drop frontend out of the backend image — it is deployed separately to Cloudflare Pages
RUN rm -rf frontend

CMD ["uv", "run", "python", "fetcher.py", "--help"]

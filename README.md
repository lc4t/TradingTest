# TradingTest

A quantitative trading toolkit that handles **market-data sync** and **backtesting**,
with a static Next.js frontend that can be published to **Cloudflare Pages** via GitHub Actions.

> Open-source. No API keys, credentials, or personal info are bundled — see `.env.example` for the
> configuration surface.

## Features

- Pull historical OHLCV data from multiple sources (yfinance, adata, …)
- Persist data into MySQL via SQLAlchemy
- Backtest strategies (MA cross, chandelier stop, ADR, parameter sweeps) on top of `backtrader`
- Export rich JSON reports for the frontend
- Static Next.js dashboard, deployable to Cloudflare Pages
- Daily signal digest pushable to PushGo / SMTP

## Project layout

```
.
├── *.py                     # backend: fetcher, backtest, db, notify, …
├── templates/               # Jinja2 templates (HTML report)
├── tests/                   # pytest suite
├── frontend/                # Next.js static site (Cloudflare Pages target)
├── Dockerfile               # backend image (published to GHCR)
├── pyproject.toml           # uv-managed Python project
└── .github/workflows/       # CI: Docker build + Cloudflare Pages deploy
```

## Quick start (backend)

Prerequisite: [`uv`](https://docs.astral.sh/uv/) and Python 3.13+.

```bash
uv sync
cp .env.example .env   # fill in DB / SMTP / PushGo as needed
```

### Sync historical data

```bash
uv run python fetcher.py --start-date 2023-01-01 --end-date 2023-12-31 --symbol <SYMBOL>
# Omitting --symbol/dates reads the configured list from the `symbol_info` table.
```

### Run a backtest

```bash
uv run python backtest.py <SYMBOL> \
  --initial-capital 50000 \
  --start-date 2022-01-01 \
  --use-ma --ma-short 5 --ma-long 8 \
  --use-chandelier --chandelier-multiplier 1.5 --chandelier-period 15 \
  --output-json frontend/public/data/<SYMBOL>.json
```

Parameter sweeps are supported via ranges (e.g. `--ma-long 8-15`).

### Daily signal digest

```bash
uv run python daily_signal_digest.py
# Optional: --data-dir frontend/public/data --date 2026-03-10 --dry-run
```

PushGo / SMTP credentials are read from environment variables — see `.env.example`.

## Frontend (Cloudflare Pages)

```bash
cd frontend
yarn install
yarn build   # static export to ./out
```

Local development server (with backend JSON data in `frontend/public/data/`):

```bash
cd frontend
./deploy_to_worker.sh dev      # serves on http://localhost:8787
```

Production deploy is handled by `.github/workflows/cloudflare-pages.yml` on every push to `main`.
Configure these GitHub repository secrets/variables:

| Kind     | Name                     | Purpose                                                |
| -------- | ------------------------ | ------------------------------------------------------ |
| secret   | `CLOUDFLARE_API_TOKEN`   | API token with `Pages:Edit` permission                 |
| secret   | `CLOUDFLARE_ACCOUNT_ID`  | Cloudflare account id                                  |
| variable | `CLOUDFLARE_PAGES_PROJECT` | Optional, defaults to `tradingtest`                  |
| variable | `NEXT_PUBLIC_GA_ID`      | Optional, Google Analytics measurement id              |

## Docker image

The backend is built and pushed to **GHCR** by `.github/workflows/docker-build.yml`:

```
ghcr.io/<owner>/tradingtest-<branch>:<short-sha>
ghcr.io/<owner>/tradingtest-<branch>:latest
```

Pull and run:

```bash
docker run --rm --env-file .env ghcr.io/<owner>/tradingtest-main:latest \
  uv run python fetcher.py --help
```

## Tests

```bash
uv run pytest
uv run pytest --cov=. --cov-report=term-missing
```

## License

MIT

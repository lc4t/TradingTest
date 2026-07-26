# Trading Frontend

Static Next.js dashboard for the Trading backend. Built with `output: 'export'` so it can be
hosted on Cloudflare Pages (or any static host).

## Local dev

```bash
yarn install
./deploy_to_worker.sh dev      # builds + serves via wrangler on :8787
```

## Build & deploy

CI in `.github/workflows/cloudflare-pages.yml` handles production deploys. To deploy manually:

```bash
./deploy_to_worker.sh deploy
```

## Data

Backtest JSON reports go into `public/data/<SYMBOL>.json`. The dashboard reads them through the
`/api/trade-data` route (in dev) or the static export (in production).

## Environment

| Var                      | Purpose                                      |
| ------------------------ | -------------------------------------------- |
| `NEXT_PUBLIC_BUILD_TIME` | Injected by CI; shown in the footer          |
| `NEXT_PUBLIC_GA_ID`      | Optional, Google Analytics measurement id    |

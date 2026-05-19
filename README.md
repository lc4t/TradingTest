# TradingTest

一个量化交易工具集：**行情数据同步** + **策略回测**，附带一个可独立部署的 Next.js 前端。

> 开源仓库。代码中不包含任何 API key、密码或个人信息——所有可配置项都在 `.env.example` 里列明。

## 功能

- 多数据源拉取历史 OHLCV 行情（yfinance / adata / …）
- 通过 SQLAlchemy 持久化到 MySQL
- 基于 `backtrader` 的策略回测，内置双均线、吊灯止损、ADR、参数寻优等
- 输出结构化 JSON 报告，供前端展示
- 静态 Next.js 仪表盘，可发布到任意静态主机（Cloudflare Pages / Vercel / 自托管均可）
- 当日信号汇总，可通过 PushGo / SMTP 推送

## 仓库结构

```
.
├── *.py                     # 后端：fetcher / backtest / db / notify / …
├── templates/               # Jinja2 模板（HTML 报告）
├── tests/                   # pytest 测试
├── frontend/                # Next.js 静态站点（独立部署）
├── Dockerfile               # 后端镜像（发布到 GHCR）
├── pyproject.toml           # 由 uv 管理的 Python 项目
└── .github/workflows/       # CI：构建并推送 Docker 镜像
```

## 后端快速上手

依赖：[`uv`](https://docs.astral.sh/uv/) 与 Python 3.13+。

```bash
uv sync
cp .env.example .env   # 按需填入 DB / SMTP / PushGo
```

### 同步历史行情

```bash
uv run python fetcher.py --start-date 2023-01-01 --end-date 2023-12-31 --symbol <SYMBOL>
# 不指定 --symbol/--end-date 时，会从数据库 symbol_info 表中读取标的列表
```

### 运行回测

```bash
uv run python backtest.py <SYMBOL> \
  --initial-capital 50000 \
  --start-date 2022-01-01 \
  --use-ma --ma-short 5 --ma-long 8 \
  --use-chandelier --chandelier-multiplier 1.5 --chandelier-period 15 \
  --output-json data/<SYMBOL>.json
```

参数支持 range 形式做网格寻优，例如 `--ma-long 8-15`。

### 当日信号汇总

```bash
uv run python daily_signal_digest.py --data-dir data
# 可选参数：--date 2026-03-10 --dry-run --max-retries 3 --retry-delay 5
```

PushGo / SMTP 凭据从环境变量读取，见 `.env.example`。

## Docker 镜像

后端镜像由 [.github/workflows/docker-build.yml](.github/workflows/docker-build.yml) 自动构建并推送到 GHCR：

```
ghcr.io/<owner>/tradingtest-<branch>:<short-sha>
ghcr.io/<owner>/tradingtest-<branch>:latest
```

本地运行示例：

```bash
docker pull ghcr.io/<owner>/tradingtest-main:latest
docker run --rm --env-file .env ghcr.io/<owner>/tradingtest-main:latest \
  uv run python fetcher.py --help
```

镜像内布局：

| 路径               | 内容                                    |
| ------------------ | --------------------------------------- |
| `/app/*.py`        | 所有后端 Python 源文件                  |
| `/app/templates/`  | Jinja2 模板                             |
| `/app/.venv/`      | 构建时安装好的虚拟环境                  |
| ~~`/app/frontend/`~~ | **不包含**——前端独立部署，不进镜像 |

> 注意：仓库的 `frontend/` 不会被打进镜像；如果你的工作流需要部署前端，请在另一个流程里完成。

## 前端

源代码位于 [`frontend/`](frontend/)，是一个 Next.js 14 静态导出（`output: 'export'`）项目。
本仓库目前**不**自动部署前端——你可以在自己的工作流中执行：

```bash
cd frontend
yarn install
yarn build         # 产物在 frontend/out/
```

然后用 `wrangler pages deploy`、`vercel deploy`、或任意静态托管即可。

## 测试

```bash
uv run pytest
uv run pytest --cov=. --cov-report=term-missing
```

## License

MIT

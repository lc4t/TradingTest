# Trading

量化交易工具集：**行情数据同步** + **策略回测**，配有一个独立部署的 Next.js 前端。

> 完全开源，代码内不包含 API key / 密码 / 个人信息——可配置项见 `.env.example`。

## 内置策略

- **双均线 + 吊灯/ADR 止损**（1.0 版即有，单标的）—— 见 [`trading/strategies/dual_ma.py`](trading/strategies/dual_ma.py)
- **动量轮动**（2.0 新增，多标的）—— 两个变体：
  - `MomentumBasket`：用户为每个候选标的预设目标权重，动量过阈值的留，其余转现金。
  - `MomentumTopN`：每期取动量最强的 N 个，等权持有。

## 仓库结构

```
.
├── trading/                # Python 包
│   ├── api.py                  # 用户态门面 run_backtest / MomentumBasket / ...
│   ├── data/                   # 数据仓库（MySQL）+ fetcher
│   ├── strategies/             # base / signals / dual_ma / momentum / momentum_rotation
│   ├── engine/                 # single / multi / sweep
│   ├── analysis/               # metrics / report
│   ├── io/                     # notify / json_export / csv_export / rotation_export / digest
│   ├── cli/                    # argparse 入口
│   └── templates/              # Jinja2 报告模板
├── notebooks/quickstart.ipynb  # Jupyter 示例
├── frontend/                   # Next.js 静态站点（独立部署）
├── tests/                      # pytest
├── scripts/                    # 一次性脚本（csvfilter 等）
├── Dockerfile                  # 后端镜像（GHCR）
├── pyproject.toml              # uv-managed Python 项目
└── .github/workflows/          # CI: 构建并推送 Docker 镜像
```

> 根目录的 `backtest.py` / `fetcher.py` 是 **向后兼容 shim**——
> 老的工作流命令仍能直接使用，内部转发到 `trading.cli.*`。

## 安装

依赖：[`uv`](https://docs.astral.sh/uv/) 与 Python 3.13+。

```bash
uv sync
cp .env.example .env   # 按需填入 DB / SMTP / PushGo
```

## CLI 用法（与 1.0 兼容）

```bash
# 同步历史行情
uv run python -m trading.cli.fetcher --start-date 2024-12-01

# 单标的回测（双均线 + 吊灯）
uv run python -m trading.cli.backtest 159915.SZ \
  --initial-capital 50000 \
  --start-date 2022-01-01 \
  --use-ma --ma-short 5 --ma-long 8 \
  --use-chandelier --chandelier-multiplier 1.5 --chandelier-period 15 \
  --output-json data/159915.SZ.json
```

## 交易信号日报

当 `data/*.json`（及 `data/rotation/*.json`）已生成后，运行独立汇总命令，把当天所有标的/策略的状态汇总后推送到 PushGo。

在 `.env` 中配置：

```bash
PUSHGO_CHANNEL_ID=your-channel-id
PUSHGO_PASSWORD=your-channel-password
# 可选，默认使用官方网关
PUSHGO_URL=https://gateway.pushgo.dev/push
```

```bash
uv run python -m trading.cli.digest --data-dir frontend/data
```

可选参数：

- `--date 2026-03-10`（默认 Asia/Shanghai 当天）
- `--pushgo-url https://gateway.pushgo.dev/push`
- `--max-retries 3` / `--retry-delay 5`
- `--dry-run`（只输出标题和正文，不推送，本地验证格式用）

行为说明：

- 只汇总 `reportDate` 等于目标日期的 JSON（单标的在 `data-dir` 下，轮动策略在 `data-dir/rotation` 下）
- 标题只统计 `买入`/`卖出`，`持有`/`观望` 仍会展示详情
- 没有任何当天 JSON 时，会发送一条"无任何数据可用"的通知
- PushGo 推送失败会按参数重试；超过重试次数后命令非零退出

## 交互式 API（2.0 新增）

```python
from trading import run_backtest, MomentumBasket, MomentumTopN, Schedule

# 加权篮子
result = run_backtest(
    strategy=MomentumBasket(
        weights={
            "159915.SZ": 0.4,
            "513100.SH": 0.4,
            "518880.SH": 0.2,
        },
        momentum_fn="simple_return",
        lookback=63,
        threshold=0.0,                              # 动量为负转现金
        schedule=Schedule.monthly_nth_trading_day(1),
    ),
    start="2022-01-01",
    initial_capital=50_000,
)

print(result.summary())
result.trades         # → DataFrame
result.metrics        # → dict
result.next_signal    # → dict
result.plot()         # → matplotlib figure
```

详见 [`notebooks/quickstart.ipynb`](notebooks/quickstart.ipynb)。

## 动量轮动策略参数

### `MomentumBasket(weights, momentum_fn, lookback, threshold, schedule, cooldown_days)`

| 参数              | 类型              | 默认值                  | 说明 |
| ----------------- | ----------------- | ----------------------- | ---- |
| `weights`         | `dict[str,float]` | —                       | `{symbol: 目标权重}`。所有权重之和必须 ≤ 1.0；未占满的部分自动为现金底仓。允许负权重值会被拒绝。 |
| `momentum_fn`     | `str` 或 callable | `"simple_return"`       | 动量计算函数，见下表。也可传入自定义 `(closes, lookback) -> float`。 |
| `lookback`        | `int`             | `63`                    | 动量回望窗口（交易日）。3 个月 ≈ 63 ，6 个月 ≈ 120，1 年 ≈ 252。 |
| `threshold`       | `float`           | `-0.99`                 | 动量准入门槛。`momentum < threshold` 的标的转现金。默认 -0.99 ≈ 不过滤；改成 `0.0` 就成了 "不买入下跌标的"。 |
| `schedule`        | `Schedule`        | `every_n_trading_days(1)` | 调仓日历，见下方表格。 |
| `cooldown_days`   | `int`             | `0`                     | 一次 rebalance 后强制等待 N 个交易日。0 = 不限制。 |

### `MomentumTopN(universe, top_n, cash_buffer, momentum_fn, lookback, threshold, schedule, cooldown_days)`

| 参数             | 类型           | 默认值                    | 说明 |
| ---------------- | -------------- | ------------------------- | ---- |
| `universe`       | `list[str]`    | —                         | 候选标的列表。 |
| `top_n`          | `int`          | `1`                       | 每期持有几个标的（等权）。 |
| `cash_buffer`    | `float`        | `0.0`                     | 永久保留的现金比例（0 ≤ x < 1）。 |
| 其余参数同上     |                |                           |      |

### 动量算法（5 种）

| `momentum_fn` key | 算法                                      | 适用场景 |
| ----------------- | ----------------------------------------- | -------- |
| `simple_return`   | `close[t] / close[t-N] - 1`               | 最经典、最普遍。|
| `log_return`      | `ln(close[t] / close[t-N])`               | 对极端涨跌不敏感，适合横截面比较。|
| `sharpe`          | `年化日均对数收益 / 年化日波动`           | 偏好"稳定上涨"而不是"暴涨"。|
| `weighted`        | 指数衰减加权对数收益（默认 `half_life=21` 交易日） | 强调近期表现，老数据权重快速衰减。|
| `dual_12_1`       | `12 个月对数收益 − 最近 1 个月对数收益`   | Asness 等经典论文，抑制短期反转噪声。默认 `lookback=252, short_skip=21`。|

### 调仓日历 (`Schedule`)

| 工厂                                       | 含义 |
| ------------------------------------------ | ---- |
| `Schedule.every_n_trading_days(n)`         | 每 N 个交易日触发。首日必触发。**默认 `n=1`**。 |
| `Schedule.weekly(weekday=1)`               | 每周特定工作日（ISO：周一=1...周五=5）。 |
| `Schedule.weekly_nth_trading_day(n=1)`     | 每周第 N 个交易日。 |
| `Schedule.monthly(day=1)`                  | 每月某个**自然日**当天首个交易日（含或之后）。 |
| `Schedule.monthly_nth_trading_day(n=1)`    | 每月第 N 个交易日。 |

### 执行细节

- **回测引擎**：基于 [backtrader](https://www.backtrader.com/)，每根 K 线代表一个交易日。
- **执行时机**：rebalance 信号在当日收盘后产生，订单默认在 **次日开盘** 成交（backtrader 默认行为）。
- **手续费**：通过 `commission_rate` 参数设置，默认 `0.0001`（万分之一）。

## Docker 镜像

后端镜像由 [.github/workflows/docker-build.yml](.github/workflows/docker-build.yml) 自动构建并推送到 GHCR：

```
ghcr.io/lc4t/trading-<branch>:<short-sha>
ghcr.io/lc4t/trading-<branch>:latest
```

- `main` / `1.0` / `2.0.0.dev`  三个分支都会自动构建。
- 1.0 是当前稳定分支；2.0.0.dev 在开发中。

### 镜像内布局

| 路径 | 内容 |
| ---- | ---- |
| `/app/trading/` | 全部 Python 源码（包） |
| `/app/.venv/` | 构建时安装好的虚拟环境 |
| `/app/{backtest,fetcher}.py` | 向后兼容的 CLI shim |
| ~~`/app/frontend/`~~ | **不打入镜像**——前端独立部署 |

## 测试

```bash
uv run pytest
uv run pytest --cov=trading --cov-report=term-missing
```

## 路线图

- [x] 1.0：双均线策略 + 参数寻优
- [x] 2.0.0.dev：动量轮动（MomentumBasket / MomentumTopN）+ 用户态 API + Jupyter
- [ ] 2.0：上线后停留为稳定版
- [ ] 后续：更多策略（趋势 / 反转 / 配对交易），更丰富的资金管理

## License

MIT

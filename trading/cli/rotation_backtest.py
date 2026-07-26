"""rotation 回测 CLI：跑一次动量轮动，输出前端可消费的 rotation-v1 JSON.

示例:

    uv run python -m trading.cli.rotation_backtest \
        --strategy-id momentum-top1 \
        --strategy-name "动量轮动 Top-1" \
        --universe 159915.SZ,513100.SH,518880.SH \
        --start-date 2022-01-01 \
        --initial-capital 50000 \
        --output-json frontend/public/data/rotation/momentum-top1.json
"""
from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path

from loguru import logger

from ..api import (
    MomentumBasket,
    MomentumTopN,
    run_backtest,
)
from ..data.repository import DBClient
from ..io.rotation_export import format_rotation_for_json
from ..strategies.momentum import MOMENTUM_FUNCTIONS, Schedule


def _configure_logger(debug: bool) -> None:
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if debug else "INFO")
    logger.add("logs/rotation_backtest.log", level="INFO", rotation="100MB", compression="zip")


def _parse_schedule(spec: str) -> Schedule:
    """字符串 → Schedule。

    支持:
      "daily" / "every_n:5" / "weekly:1" / "weekly_nth:1"
      "monthly:1" / "monthly_nth:1"
    """
    if spec == "daily":
        return Schedule.every_n_trading_days(1)
    if ":" not in spec:
        raise ValueError(f"无法解析 schedule={spec!r}")
    kind, arg = spec.split(":", 1)
    n = int(arg)
    if kind == "every_n":
        return Schedule.every_n_trading_days(n)
    if kind == "weekly":
        return Schedule.weekly(weekday=n)
    if kind == "weekly_nth":
        return Schedule.weekly_nth_trading_day(n=n)
    if kind == "monthly":
        return Schedule.monthly(day=n)
    if kind == "monthly_nth":
        return Schedule.monthly_nth_trading_day(n=n)
    raise ValueError(f"未知 schedule kind: {kind}")


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="动量轮动回测 + rotation-v1 JSON 输出")
    parser.add_argument("--strategy-id", required=True, help="URL slug, 用于前端路由")
    parser.add_argument("--strategy-name", required=True, help="显示名称")
    parser.add_argument(
        "--universe", required=True,
        help="逗号分隔的标的列表，例如 159915.SZ,513100.SH,518880.SH",
    )
    parser.add_argument(
        "--weights",
        help="可选: 逗号分隔的权重（与 universe 顺序对齐，例如 0.4,0.4,0.2）。"
             "提供权重 = MomentumBasket 模式；省略 = MomentumTopN 模式。",
    )
    parser.add_argument("--top-n", type=int, default=1, help="TopN 模式时的 N（默认 1）")
    parser.add_argument(
        "--cash-buffer", type=float, default=0.05,
        help="TopN 模式现金缓冲，默认 0.05 (95%% 仓位)",
    )
    parser.add_argument(
        "--momentum-fn", default="simple_return",
        choices=sorted(MOMENTUM_FUNCTIONS),
        help="动量函数 key",
    )
    parser.add_argument("--lookback", type=int, default=23, help="动量回望窗口（交易日）")
    parser.add_argument(
        "--threshold", type=float, default=-0.99,
        help="绝对动量阈值；动量 < threshold 的标的转现金",
    )
    parser.add_argument(
        "--schedule", default="daily",
        help='调仓日历: "daily" / "every_n:N" / "weekly:1..5" / "weekly_nth:N" '
             '/ "monthly:N" / "monthly_nth:N"',
    )
    parser.add_argument("--cooldown-days", type=int, default=0, help="一次调仓后冷却天数")
    parser.add_argument(
        "--trend-filter-ma", type=int, default=None,
        help="趋势过滤：仅在收盘价 > N 日均线时持有（默认关闭）",
    )
    parser.add_argument("--start-date", required=True, help="回测起始 YYYY-MM-DD")
    parser.add_argument("--end-date", help="回测终止 YYYY-MM-DD，省略=今天")
    parser.add_argument("--initial-capital", type=float, default=50_000)
    parser.add_argument("--commission-rate", type=float, default=0.0001)
    parser.add_argument(
        "--benchmark", default="000300.SS",
        help="基准代码，留空字符串 \"\" 关闭",
    )
    parser.add_argument("--risk-free-rate", type=float, default=0.03)
    parser.add_argument("--output-json", required=True, help="JSON 输出路径")
    parser.add_argument("--debug", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    _configure_logger(args.debug)

    universe = [s.strip() for s in args.universe.split(",") if s.strip()]
    schedule = _parse_schedule(args.schedule)
    weights_dict: dict[str, float] | None = None

    if args.weights:
        ws = [float(x) for x in args.weights.split(",")]
        if len(ws) != len(universe):
            raise SystemExit("--weights 的数量必须与 --universe 对齐")
        weights_dict = dict(zip(universe, ws))
        strategy = MomentumBasket(
            weights=weights_dict,
            momentum_fn=args.momentum_fn,
            lookback=args.lookback,
            threshold=args.threshold,
            schedule=schedule,
            cooldown_days=args.cooldown_days,
            trend_filter_ma=args.trend_filter_ma,
        )
    else:
        strategy = MomentumTopN(
            universe=universe,
            top_n=args.top_n,
            cash_buffer=args.cash_buffer,
            momentum_fn=args.momentum_fn,
            lookback=args.lookback,
            threshold=args.threshold,
            schedule=schedule,
            cooldown_days=args.cooldown_days,
            trend_filter_ma=args.trend_filter_ma,
        )

    benchmark = args.benchmark.strip() or None

    result = run_backtest(
        strategy=strategy,
        start=args.start_date,
        end=args.end_date,
        initial_capital=args.initial_capital,
        commission_rate=args.commission_rate,
        benchmark=benchmark,
        risk_free_rate=args.risk_free_rate,
    )

    config = {
        "universe": universe,
        "weights": weights_dict,
        "mode": "basket" if weights_dict else "top_n",
        "topN": args.top_n if not weights_dict else None,
        "cashBuffer": args.cash_buffer if not weights_dict else None,
        "momentumFn": args.momentum_fn,
        "lookback": args.lookback,
        "threshold": args.threshold,
        "schedule": args.schedule,
        "cooldownDays": args.cooldown_days,
        "trendFilterMa": args.trend_filter_ma,
        "initialCapital": args.initial_capital,
        "commissionRate": args.commission_rate,
        "benchmark": benchmark,
        "riskFreeRate": args.risk_free_rate,
    }

    payload = format_rotation_for_json(
        result.raw,
        strategy_id=args.strategy_id,
        strategy_name=args.strategy_name,
        config=config,
        db_client=DBClient(),
    )

    out = Path(args.output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    logger.info(f"已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

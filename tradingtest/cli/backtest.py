"""backtest CLI — argparse 层。

行为与 1.0 版本完全一致；调用迁移后的 SingleBacktestEngine / sweep。
"""
from __future__ import annotations

import json
import os
import sys
from argparse import ArgumentParser
from datetime import datetime

from loguru import logger

from ..data.repository import DBClient
from ..engine.single import SingleBacktestEngine
from ..engine.sweep import run_parameter_combinations
from ..io.csv_export import export_results_to_csv
from ..io.json_export import format_for_json, get_stock_name
from ..io.notify import NotifyManager, create_backtest_result
from .printers import (
    format_params_string,
    print_best_results,
    print_combination_result,
    print_metrics,
    print_next_signal,
    print_parameter_summary,
    print_trades,
)


def _configure_logger(debug: bool) -> None:
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if debug else "INFO")
    logger.add("logs/backtest.log", level="INFO", rotation="1000MB", compression="zip")


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="股票回测工具")
    parser.add_argument("symbol", help="股票代码")
    parser.add_argument("--start-date", required=True, help="开始日期 (YYYY-MM-DD)")
    parser.add_argument(
        "--end-date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="结束日期 (YYYY-MM-DD)，默认为今天",
    )
    parser.add_argument("--initial-capital", type=float, default=100000, help="初始资金")
    parser.add_argument(
        "--commission-rate", type=float, default=0.0001,
        help="手续费率，默认 0.0001 (万一)",
    )
    parser.add_argument(
        "--position-size", type=float, default=0.95,
        help="资金使用比例，默认 0.95",
    )

    parser.add_argument("--use-ma", action="store_true", help="使用双均线策略")
    parser.add_argument("--ma-short", type=str, default="5", help="短期均线周期，支持范围")
    parser.add_argument("--ma-long", type=str, default="20", help="长期均线周期，支持范围")
    parser.add_argument("--use-chandelier", action="store_true", help="使用吊灯止损")
    parser.add_argument("--chandelier-period", type=str, default="22", help="ATR 周期")
    parser.add_argument("--chandelier-multiplier", type=str, default="3.0", help="ATR 乘数")
    parser.add_argument("--use-adr", action="store_true", help="使用 ADR 止损")
    parser.add_argument("--adr-period", type=str, default="20", help="ADR 周期")
    parser.add_argument("--adr-multiplier", type=str, default="1.0", help="ADR 乘数")

    parser.add_argument("--trade-start-time", help="每日交易开始时间 (HH:MM:SS)")
    parser.add_argument("--trade-end-time", help="每日交易结束时间 (HH:MM:SS)")

    parser.add_argument("--notify", choices=["email", "wecom", "all"], help="通知方式")
    parser.add_argument("--email-to", help="邮件接收者，逗号分隔")

    parser.add_argument("--yes", "-y", action="store_true", help="跳过所有确认")
    parser.add_argument("--workers", type=int, help="并行进程数")
    parser.add_argument("--debug", action="store_true", help="启用调试日志")
    parser.add_argument("--output-json", type=str, help="输出结果到指定的 JSON 文件")
    parser.add_argument(
        "--benchmark", type=str, default="000300.SS",
        help="市场基准代码，默认 000300.SS (沪深300)",
    )
    parser.add_argument(
        "--risk-free-rate", type=float, default=0.03,
        help="无风险利率，默认 0.03",
    )
    parser.add_argument(
        "--output-csv", type=str, default="backtest_results.csv",
        help="输出回测结果到 CSV 文件",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _configure_logger(args.debug)

    db_client = DBClient()
    latest_data = db_client.query_latest_by_symbol(args.symbol)
    if latest_data:
        args.end_date = latest_data["date"].strftime("%Y-%m-%d")
        logger.info(f"使用数据库中的最新日期: {args.end_date}")

    has_ranges = any(
        "-" in str(getattr(args, name))
        for name in [
            "ma_short", "ma_long",
            "chandelier_period", "chandelier_multiplier",
            "adr_period", "adr_multiplier",
        ]
    )

    if has_ranges:
        results = _run_sweep(args, db_client)
        if args.notify:
            results = results["best_annual_return"]["full_result"]
    else:
        results = _run_single(args, db_client)

    if args.output_json:
        _write_json(args, results, has_ranges, db_client)


def _run_sweep(args, db_client: DBClient) -> dict:
    base_params = {
        "use_ma": args.use_ma,
        "use_chandelier": args.use_chandelier,
        "use_adr": args.use_adr,
        "trade_start_time": args.trade_start_time,
        "trade_end_time": args.trade_end_time,
    }
    market_params = {"benchmark": args.benchmark, "risk_free_rate": args.risk_free_rate}

    param_ranges: dict = {}
    if args.use_ma:
        param_ranges.update({"ma_short": args.ma_short, "ma_long": args.ma_long})
    if args.use_chandelier:
        param_ranges.update(
            {
                "chandelier_period": args.chandelier_period,
                "chandelier_multiplier": args.chandelier_multiplier,
            }
        )
    if args.use_adr:
        param_ranges.update(
            {"adr_period": args.adr_period, "adr_multiplier": args.adr_multiplier}
        )

    results = run_parameter_combinations(
        db_client=db_client,
        symbol=args.symbol,
        start_date=datetime.strptime(args.start_date, "%Y-%m-%d"),
        end_date=datetime.strptime(args.end_date, "%Y-%m-%d"),
        initial_capital=args.initial_capital,
        commission_rate=args.commission_rate,
        base_params=base_params,
        market_params=market_params,
        param_ranges=param_ranges,
        max_workers=args.workers,
    )

    export_results_to_csv(results["combinations"], args.output_csv)

    if args.debug:
        logger.info("调试模式开启，输出所有参数组合结果")
        for idx, result in enumerate(results["combinations"], 1):
            logger.info(f"\n\n{'='*20} 参数组合 {idx} {'='*20}")
            logger.info(f"参数: {format_params_string(result['params'])}")
            full_result = result["full_result"]
            metrics = full_result["metrics"]
            print_metrics(metrics)
            print_combination_result(idx, result)
            print_next_signal(full_result["next_signal"])
            print_trades(full_result["all_trades"])
            logger.info("\n" + "=" * 50)
        print_parameter_summary(results["combinations"])
        print_best_results(results)

    return results


def _run_single(args, db_client: DBClient) -> dict:
    params: dict = {
        "initial_capital": args.initial_capital,
        "commission_rate": args.commission_rate,
        "use_ma": args.use_ma,
        "use_chandelier": args.use_chandelier,
        "use_adr": args.use_adr,
        "trade_start_time": args.trade_start_time,
        "trade_end_time": args.trade_end_time,
        "benchmark": args.benchmark,
        "risk_free_rate": args.risk_free_rate,
    }

    if args.use_ma:
        params.update(
            {
                "short_period": int(float(args.ma_short)),
                "long_period": int(float(args.ma_long)),
            }
        )
    if args.use_chandelier:
        params.update(
            {
                "chandelier_period": int(float(args.chandelier_period)),
                "chandelier_multiplier": float(args.chandelier_multiplier),
            }
        )
    if args.use_adr:
        params.update(
            {
                "adr_period": int(float(args.adr_period)),
                "adr_multiplier": float(args.adr_multiplier),
            }
        )

    engine = SingleBacktestEngine(db_client)
    results = engine.run(
        symbol=args.symbol,
        start_date=datetime.strptime(args.start_date, "%Y-%m-%d"),
        end_date=datetime.strptime(args.end_date, "%Y-%m-%d"),
        params=params,
    )
    results.update(params)

    logger.info("\n=== 回测结果 ===")
    logger.info(f"初始资金: {results['initial_capital']:.2f}")
    logger.info(f"最终权益: {results['final_value']:.2f}")
    logger.info(f"总收益率: {results['total_return']:.2f}%")
    print_metrics(results["metrics"])
    print_combination_result(1, results)
    print_next_signal(results["next_signal"])
    print_trades(results["all_trades"])

    if args.notify:
        _maybe_notify(args, results)
    return results


def _maybe_notify(args, results: dict) -> None:
    notify_methods = []
    if args.notify in ["email", "all"] and args.email_to:
        os.environ["EMAIL_RECIPIENTS"] = args.email_to
        notify_methods.append("email")
    if args.notify in ["wecom", "all"]:
        notify_methods.append("wecom")
    if not notify_methods:
        return

    notify_manager = NotifyManager(notify_methods)
    backtest_result = create_backtest_result(
        results,
        {
            "symbol": args.symbol,
            "start_date": datetime.strptime(args.start_date, "%Y-%m-%d"),
            "end_date": datetime.strptime(args.end_date, "%Y-%m-%d"),
            "use_ma": args.use_ma,
            "ma_short": args.ma_short,
            "ma_long": args.ma_long,
            "use_chandelier": args.use_chandelier,
            "chandelier_period": args.chandelier_period,
            "chandelier_multiplier": args.chandelier_multiplier,
            "use_adr": args.use_adr,
            "adr_period": args.adr_period,
            "adr_multiplier": args.adr_multiplier,
        },
    )

    print("\n=== 邮件内容预览 ===")
    print(notify_manager.get_message_preview(backtest_result))
    if not args.yes:
        confirm = input("是否发送邮件？(y/N) ")
        if confirm.lower() != "y":
            logger.info("取消发送邮件")
            return

    if notify_manager.send_report(backtest_result):
        logger.info("Report sent successfully")
    else:
        logger.error("Failed to send report")


def _write_json(args, results: dict, has_ranges: bool, db_client: DBClient) -> None:
    if has_ranges:
        best_result = results["best_annual_return"]["full_result"]
    else:
        best_result = results

    stock_name = get_stock_name(db_client, args.symbol)
    params_dict = {
        "symbol": args.symbol,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "initial_capital": args.initial_capital,
        "use_ma": args.use_ma,
        "ma_short": args.ma_short,
        "ma_long": args.ma_long,
        "use_chandelier": args.use_chandelier,
        "chandelier_period": args.chandelier_period,
        "chandelier_multiplier": args.chandelier_multiplier,
        "use_adr": args.use_adr,
        "adr_period": args.adr_period,
        "adr_multiplier": args.adr_multiplier,
    }

    json_data = format_for_json(
        best_result["metrics"],
        best_result["all_trades"],
        best_result["next_signal"],
        params_dict,
        args.symbol,
        stock_name,
        args.initial_capital,
    )

    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
        logger.info(f"结果已输出到 JSON 文件: {args.output_json}")


if __name__ == "__main__":
    main()

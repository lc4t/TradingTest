"""CLI 表格打印工具。仅供命令行使用，逻辑层不应依赖。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List

from loguru import logger
from tabulate import tabulate

SEPARATOR_WIDTH = 60
SECTION_SEPARATOR = "=" * SEPARATOR_WIDTH
SUBSECTION_SEPARATOR = "-" * SEPARATOR_WIDTH


def format_value(v):
    """处理值，确保 JSON 可序列化。"""
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float):
        return round(v, 3)
    return v


def format_params_string(params: dict) -> str:
    """格式化参数字符串，只显示启用的参数。"""
    parts: list[str] = []
    if params.get("use_ma"):
        parts.append(f"MA={params['short_period']}/{params['long_period']}")
    if params.get("use_chandelier"):
        parts.append(f"ATR={params['chandelier_multiplier']}x{params['chandelier_period']}")
    if params.get("use_adr"):
        parts.append(f"ADR={params['adr_multiplier']}x{params['adr_period']}")
    return ", ".join(parts)


def print_metrics(metrics: Dict):
    """打印性能指标三列布局。"""
    logger.info(f"\n{SECTION_SEPARATOR}")
    logger.info(f"{'性能指标':^{SEPARATOR_WIDTH}}")
    logger.info(SECTION_SEPARATOR)

    metrics_layout = [
        ("最新净值", f"{metrics['latest_nav']:>12.2f}",
         "年化收益率", f"{metrics['annual_return']:>12.2f}%",
         "复合年化收益", f"{metrics['cagr']:>12.2f}%"),
        ("总交易次数", f"{metrics['total_trades']:>12d}",
         "胜率", f"{metrics['win_rate']:>12.2f}%",
         "盈亏比", f"{metrics['profit_factor']:>12.2f}"),
        ("盈利交易", f"{metrics['won_trades']:>12d}",
         "亏损交易", f"{metrics['lost_trades']:>12d}",
         "总盈亏", f"{metrics['total_pnl']:>12.2f}"),
        ("平均盈利", f"{metrics['avg_won']:>12.2f}",
         "平均亏损", f"{metrics['avg_lost']:>12.2f}",
         "持仓比例", f"{metrics['holding_ratio']:>12.2f}%"),
        ("年化波动率", f"{metrics['volatility']:.2f}%",
         "最大回撤", f"{metrics['max_drawdown']:.2f}%",
         "最大亏损金额", f"{metrics['max_loss_amount']:.2f}"),
        ("最大亏损比例", f"{metrics['max_loss_pct']:.2f}%",
         "夏普比率", f"{metrics['sharpe_ratio']:.2f}",
         "索提诺比率", f"{metrics['sortino_ratio']:.2f}"),
        ("卡玛比率", f"{metrics['calmar_ratio']:.2f}",
         "VWR", f"{metrics['vwr']:.2f}",
         "SQN", f"{metrics['sqn']:.2f}"),
        ("最大连胜", f"{metrics['max_consecutive_wins']:>12d}",
         "最大连亏", f"{metrics['max_consecutive_losses']:>12d}",
         "平均持仓", f"{metrics['avg_holding_period']:>12}天"),
        ("运行天数", f"{metrics['running_days']:>12d}",
         "开始日期", f"{metrics['start_date'].strftime('%Y-%m-%d'):>12}",
         "结束日期", f"{metrics['end_date'].strftime('%Y-%m-%d'):>12}"),
        ("波动率", f"{metrics.get('volatility', 0):>12.2f}%",
         "Beta系数", f"{metrics.get('beta', 0):>12.2f}",
         "Alpha", f"{metrics.get('alpha', 0):>12.2f}%"),
        ("Beta参考", f"{str(metrics.get('benchmark_symbol', 'N/A')):>12}",
         "Beta状态", f"{metrics.get('beta_status', 'N/A'):>12}",
         "最大亏损比例", f"{metrics.get('max_loss_pct', 0):>12.2f}%"),
    ]
    for row in metrics_layout:
        logger.info(
            f"{row[0]:<12}{row[1]:<16}{row[2]:<12}{row[3]:<16}{row[4]:<12}{row[5]}"
        )

    if "yearly_returns" in metrics:
        logger.info(SUBSECTION_SEPARATOR)
        logger.info("年度收益率:")
        for year, return_rate in metrics["yearly_returns"].items():
            logger.info(f"{year}年: {return_rate:>12.2f}%")

    if "monthly_returns" in metrics:
        logger.info(SUBSECTION_SEPARATOR)
        logger.info("月度收益率:")
        for month, return_rate in metrics["monthly_returns"].items():
            logger.info(f"{month}: {return_rate:>12.2f}%")


def print_combination_result(idx: int, result: dict):
    """格式化打印单个参数组合的结果。"""
    logger.info(f"\n{SECTION_SEPARATOR}")
    logger.info(f"{'参数组合 ' + str(idx):^{SEPARATOR_WIDTH}}")
    logger.info(SECTION_SEPARATOR)

    if "params" not in result:
        metrics = result.get("metrics", {})
    else:
        metrics = result.get("full_result", {}).get("metrics", {})

    params_str = format_params_string(result.get("params", result))
    logger.info(f"参数配置: {params_str}")
    logger.info(SUBSECTION_SEPARATOR)

    table_data = [
        ["年化收益率", f"{metrics.get('annual_return', 0):.2f}%"],
        ["最大回撤", f"{metrics.get('max_drawdown', 0):.2f}%"],
        ["夏普比率", f"{metrics.get('sharpe_ratio', 0):.2f}"],
        ["波动率", f"{metrics.get('volatility', 0):.2f}%"],
        ["Beta系数", f"{metrics.get('beta', 0):.2f}"],
        ["Alpha", f"{metrics.get('alpha', 0):.2f}%"],
        ["最大亏损金额", f"{metrics.get('max_loss_amount', 0):.2f}"],
        ["最大亏损比例", f"{metrics.get('max_loss_pct', 0):.2f}%"],
        ["总交易次数", str(metrics.get("total_trades", 0))],
        ["胜率", f"{metrics.get('win_rate', 0):.2f}%"],
        ["盈亏比", f"{metrics.get('profit_factor', 0):.2f}"],
        ["Calmar比率", f"{metrics.get('calmar_ratio', 0):.2f}"],
        ["VWR", f"{metrics.get('vwr', 0):.2f}"],
        ["SQN", f"{metrics.get('sqn', 0):.2f}"],
    ]
    logger.info(
        "\n" + tabulate(table_data, headers=["指标", "值"], tablefmt="simple",
                         colalign=("left", "right"))
    )

    if metrics.get("start_date") and metrics.get("end_date"):
        logger.info(SUBSECTION_SEPARATOR)
        logger.info(
            f"交易区间: {metrics['start_date'].strftime('%Y-%m-%d')} - "
            f"{metrics['end_date'].strftime('%Y-%m-%d')}"
        )


def print_next_signal(next_signal: dict):
    """格式化打印下一交易日信号。"""
    logger.info(f"\n{SECTION_SEPARATOR}")
    logger.info(f"{'下一交易日信号':^{SEPARATOR_WIDTH}}")
    logger.info(SECTION_SEPARATOR)
    logger.info(f"建议动作: {next_signal['action']:>12}")

    if next_signal["position_info"]:
        pos_info = next_signal["position_info"]
        logger.info(SUBSECTION_SEPARATOR)
        logger.info("当前持仓信息:")
        info_layout = [
            ("买入日期", pos_info["entry_date"]),
            ("买入价格", f"{pos_info['entry_price']:.3f}"),
            ("买入金额", f"{pos_info['position_value']:.2f}"),
            ("持仓数量", str(pos_info["position_size"])),
            ("当前价格", f"{pos_info['current_price']:.3f}"),
            ("当前市值", f"{pos_info['current_value']:.2f}"),
            (
                "浮动盈亏",
                f"{pos_info['unrealized_pnl']:.2f} "
                f"({pos_info['unrealized_pnl_pct']:.2f}%)",
            ),
        ]
        for label, value in info_layout:
            logger.info(f"{label:>12}: {value}")


def print_trades(trades: List[dict], title: str = "交易记录"):
    """格式化打印交易记录。"""
    logger.info(f"\n=== {title} ===")
    if not trades:
        logger.info("没有交易记录")
        return

    headers = ["日期", "动作", "价格", "数量", "交易金额", "手续费", "盈亏", "总资产", "信号原因"]
    table_data = [
        [
            trade["date"],
            trade["action"],
            f"{trade['price']:.3f}",
            trade["size"],
            f"{trade['value']:.2f}",
            f"{trade['commission']:.2f}",
            f"{trade['pnl']:.2f}",
            f"{trade['total_value']:.2f}",
            trade["signal_reason"],
        ]
        for trade in trades
    ]
    logger.info(tabulate(table_data, headers=headers, tablefmt="grid"))


def print_parameter_summary(combinations: List[dict]):
    """格式化打印参数组合汇总。"""
    logger.info("\n=== 参数组合汇总（按年化收益率排序）===")
    headers = ["参数组合", "年化收益率(%)", "最大回撤(%)", "交易次数", "首次交易", "最后交易"]

    sorted_combinations = sorted(combinations, key=lambda x: x["annual_return"], reverse=False)
    table_data = []
    for result in sorted_combinations:
        params_str = format_params_string(result["params"])
        table_data.append(
            [
                params_str,
                f"{result['annual_return']:.2f}",
                f"{result['max_drawdown']:.2f}",
                result["total_trades"],
                result["first_trade"],
                result["last_trade"],
            ]
        )
    logger.info(tabulate(table_data, headers=headers, tablefmt="grid"))


def print_best_results(results: Dict):
    """打印最佳结果。"""
    if not results.get("combinations"):
        logger.warning("没有有效的回测结果")
        return

    best_return = results.get("best_annual_return")
    if best_return:
        logger.info("\n=== 最佳年化收益率组合 ===")
        logger.info(f"参数: {format_params_string(best_return['params'])}")
        logger.info(f"年化收益率: {best_return['annual_return']:.2f}%")
        logger.info(f"最大回撤: {best_return['max_drawdown']:.2f}%")
        logger.info(f"交易次数: {best_return['total_trades']}")

    min_dd = results.get("min_drawdown")
    if min_dd:
        logger.info("\n=== 最小回撤组合 ===")
        logger.info(f"参数: {format_params_string(min_dd['params'])}")
        logger.info(f"年化收益率: {min_dd['annual_return']:.2f}%")
        logger.info(f"最大回撤: {min_dd['max_drawdown']:.2f}%")
        logger.info(f"交易次数: {min_dd['total_trades']}")

    best_sharpe = results.get("best_sharpe")
    if best_sharpe:
        logger.info("\n=== 最佳夏普比率组合 ===")
        logger.info(f"参数: {format_params_string(best_sharpe['params'])}")
        logger.info(f"年化收益率: {best_sharpe['annual_return']:.2f}%")
        logger.info(f"最大回撤: {best_sharpe['max_drawdown']:.2f}%")
        logger.info(
            f"夏普比率: {best_sharpe['full_result']['metrics']['sharpe_ratio']:.2f}"
        )
        logger.info(f"交易次数: {best_sharpe['total_trades']}")

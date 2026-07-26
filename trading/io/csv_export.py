"""把多参数寻优结果导出为 CSV。"""
from __future__ import annotations

from typing import Dict, List

import pandas as pd
from loguru import logger


_COLUMN_ORDER = [
    "短期均线周期", "长期均线周期", "吊灯周期", "吊灯乘数", "ADR周期", "ADR乘数",
    "年化收益率(%)", "总盈亏(元)", "复合年化收益率(%)",
    "最大回撤(%)", "波动率(%)", "Beta系数", "Alpha(%)",
    "最大亏损金额(元)", "最大亏损比例(%)",
    "夏普比率", "索提诺比率", "卡玛比率", "VWR", "SQN",
    "总交易次数", "胜率(%)", "盈亏比",
    "平均盈利(元)", "平均亏损(元)",
    "最大连续盈利次数", "最大连续亏损次数",
    "开始日期", "结束日期", "运行天数",
]


def export_results_to_csv(combinations: List[Dict], output_file: str) -> None:
    """将参数组合回测结果导出为 CSV 文件。"""
    rows = []
    for result in combinations:
        metrics = result.get("full_result", {}).get("metrics", {})
        params = result.get("params", {})
        rows.append(
            {
                "短期均线周期": params.get("short_period"),
                "长期均线周期": params.get("long_period"),
                "吊灯周期": params.get("chandelier_period"),
                "吊灯乘数": params.get("chandelier_multiplier"),
                "ADR周期": params.get("adr_period"),
                "ADR乘数": params.get("adr_multiplier"),
                "年化收益率(%)": metrics.get("annual_return"),
                "总盈亏(元)": metrics.get("total_pnl"),
                "复合年化收益率(%)": metrics.get("cagr"),
                "最大回撤(%)": metrics.get("max_drawdown"),
                "波动率(%)": metrics.get("volatility"),
                "Beta系数": metrics.get("beta"),
                "Alpha(%)": metrics.get("alpha"),
                "最大亏损金额(元)": metrics.get("max_loss_amount"),
                "最大亏损比例(%)": metrics.get("max_loss_pct"),
                "夏普比率": metrics.get("sharpe_ratio"),
                "索提诺比率": metrics.get("sortino_ratio"),
                "卡玛比率": metrics.get("calmar_ratio"),
                "VWR": metrics.get("vwr"),
                "SQN": metrics.get("sqn"),
                "总交易次数": metrics.get("total_trades"),
                "胜率(%)": metrics.get("win_rate"),
                "盈亏比": metrics.get("profit_factor"),
                "平均盈利(元)": metrics.get("avg_won"),
                "平均亏损(元)": metrics.get("avg_lost"),
                "最大连续盈利次数": metrics.get("max_consecutive_wins"),
                "最大连续亏损次数": metrics.get("max_consecutive_losses"),
                "开始日期": metrics["start_date"].strftime("%Y-%m-%d")
                if metrics.get("start_date") else None,
                "结束日期": metrics["end_date"].strftime("%Y-%m-%d")
                if metrics.get("end_date") else None,
                "运行天数": metrics.get("running_days"),
            }
        )

    df = pd.DataFrame(rows)[_COLUMN_ORDER]
    df.to_csv(output_file, index=False, float_format="%.4f", encoding="utf-8")
    logger.info(f"回测结果已保存到 CSV 文件: {output_file}")

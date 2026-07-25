// 把 rotation-v1（动量轮动策略）数据映射成跟单标的 QuantTradeReport 完全一致的形状，
// 这样动量策略可以复用同一套展示组件，不用额外的 /rotation 路由和专属卡片样式。

type RotationAction = "HOLD" | "ROTATE" | "EXIT"

export interface RotationData {
  schemaVersion: string
  strategyId: string
  strategyName: string
  reportDate: string
  dateRange: { start: string; end: string }
  summary: {
    initialCapital: number
    finalValue: number
    totalReturnPct: number
    annualReturn: number
    maxDrawdown: number
    sharpe: number
    volatility: number
  }
  currentHolding: {
    symbol: string
    name: string
    since: string
    entryPrice: number
    currentPrice: number
    size: number
    marketValue: number
    unrealizedPnl: number
    unrealizedPnlPct: number
  } | null
  nextSignal: {
    action: RotationAction
    reason: string
    rotateFrom: string | null
    rotateTo: string | null
    evaluatedAt: string
  }
  rotations: Array<{
    symbol: string
    entryDate: string
    exitDate: string
    entryPrice: number
    exitPrice: number
    size: number
    holdingDays: number
    periodReturnPct: number
    pnl: number
  }>
  annualReturns: Array<{ year: number; value: number }>
  metrics: {
    returnMetrics: Array<{ name: string; value: number | string; description?: string }>
    riskMetrics: Array<{ name: string; value: number | string; description?: string }>
    riskAdjustedMetrics: Array<{ name: string; value: number | string; description?: string }>
    tradingMetrics: Array<{ name: string; value: number | string; description?: string }>
  }
}

function todayAction(data: RotationData): "买入" | "卖出" | "持有" | "观察" {
  const holding = data.currentHolding
  if (holding && holding.since === data.reportDate) return "买入"
  if (!holding) {
    const soldToday = data.rotations.some((r) => r.exitDate === data.reportDate)
    return soldToday ? "卖出" : "观察"
  }
  return "持有"
}

export function rotationToTradeData(data: RotationData) {
  const holding = data.currentHolding
  const action = todayAction(data)

  const positionInfo = holding
    ? {
        entryDate: holding.since,
        entryPrice: holding.entryPrice,
        quantity: holding.size,
        currentValue: holding.marketValue,
        profitLoss: holding.unrealizedPnl,
        profitLossPercentage: holding.unrealizedPnlPct,
      }
    : null

  const sortedRotations = [...data.rotations].sort(
    (a, b) => new Date(a.exitDate).getTime() - new Date(b.exitDate).getTime()
  )
  let runningTotal = data.summary.initialCapital
  const recentTrades = sortedRotations.flatMap((r) => {
    const buyRow = {
      date: r.entryDate,
      action: "BUY",
      price: r.entryPrice,
      quantity: r.size,
      value: r.entryPrice * r.size,
      profitLoss: 0,
      totalValue: runningTotal,
      reason: "轮动买入",
    }
    runningTotal += r.pnl
    const sellRow = {
      date: r.exitDate,
      action: "SELL",
      price: r.exitPrice,
      quantity: r.size,
      value: r.exitPrice * r.size,
      profitLoss: r.pnl,
      profitLossPercentage: r.periodReturnPct,
      totalValue: runningTotal,
      reason: `轮动卖出（持有${r.holdingDays}天）`,
      entryPrice: r.entryPrice,
    }
    return [buyRow, sellRow]
  })

  return {
    symbol: data.strategyId,
    name: data.strategyName,
    reportDate: data.reportDate,
    dateRange: data.dateRange,
    latestSignal: {
      action,
      asset: holding ? `${holding.name}(${holding.symbol})` : "空仓",
      timestamp: data.reportDate,
      price: holding ? holding.currentPrice : undefined,
    },
    positionInfo,
    annualReturns: data.annualReturns,
    returnMetrics: data.metrics.returnMetrics,
    riskMetrics: data.metrics.riskMetrics,
    riskAdjustedMetrics: data.metrics.riskAdjustedMetrics,
    tradingMetrics: data.metrics.tradingMetrics,
    positionMetrics: [],
    benchmarkMetrics: [],
    timeMetrics: [],
    recentTrades,
    strategyParameters: [],
    showStrategyParameters: false,
  }
}

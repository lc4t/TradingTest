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

// rotation-v1 JSON 的 currentHolding.name / universeRanking.name 在没有配置 DB 名称查询时
// 会直接回退成 symbol 本身（比如 "518880.SS"），页面上就看不出持有的到底是黄金 ETF 还是别的。
// 轮动候选池固定且很小，这里直接兜底一份中文名，遇到 name === symbol 时用它替换。
const KNOWN_SYMBOL_NAMES: Record<string, string> = {
  "159915.SZ": "创业板ETF",
  "513100.SS": "国泰纳斯达克100ETF",
  "513100.SH": "国泰纳斯达克100ETF",
  "518880.SS": "华安易富黄金ETF",
  "518880.SH": "华安易富黄金ETF",
}

function resolveSymbolName(symbol: string, rawName?: string): string {
  if (rawName && rawName !== symbol) return rawName
  return KNOWN_SYMBOL_NAMES[symbol] || symbol
}

// 策略名里常年带着完整候选池，比如"动量轮动 Top-1（创业板/纳指/黄金）"——放进按钮/标题会很长，
// 且候选池是固定配置，不是"现在持有什么"的答案。标题只保留策略名前缀，实际持仓另外拼出来。
function baseStrategyName(strategyName: string): string {
  return strategyName.split(/[（(]/)[0].trim() || strategyName
}

function formatShortDate(dateStr: string): string {
  const d = new Date(dateStr.slice(0, 10))
  return `${d.getMonth() + 1}/${d.getDate()}`
}

interface RotationTradeRow {
  date: string
  action: "BUY" | "SELL"
  price: number
  quantity: number
  value: number
  profitLoss: number
  profitLossPercentage?: number
  totalValue: number
  reason: string
  entryPrice?: number
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
  const heldName = holding ? resolveSymbolName(holding.symbol, holding.name) : null
  const base = baseStrategyName(data.strategyName)

  // 名字里不重复"持有/买入"这类动作词——徽章（action）已经说了一遍，这里只负责回答
  // "持有的是谁"。入场日期、持有天数已经在下面的"当前持仓"卡片里有专门字段，不用再挤进标题。
  let displayName = `${base} · 空仓`
  if (holding) {
    displayName = `${base} · ${heldName}`
  } else {
    const soldToday = data.rotations.find((r) => r.exitDate === data.reportDate)
    if (soldToday) {
      displayName = `${base} · 已清仓${resolveSymbolName(soldToday.symbol)}`
    }
  }

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

  // 买入、卖出各占一行（不合并成一行），标的名称+代码写进 reason 里保证一眼看出是哪个
  // 标的；卖出行的 reason 回指"此前哪天买入、持有几天"，跟对应买入行做文字上的配对——
  // 同一段持仓的买卖是 Top-1 轮动，中间不会插进第三个标的，天然是紧挨着的两行。
  // 额外补一行"当前持仓"的买入记录——不然还在持有中的仓位永远不会出现在 rotations
  // 里（那里只收录已经平仓的），交易记录里就看不到最新一次买入。
  const sortedRotations = [...data.rotations].sort(
    (a, b) => new Date(a.exitDate).getTime() - new Date(b.exitDate).getTime()
  )
  let runningTotal = data.summary.initialCapital
  const recentTrades: RotationTradeRow[] = sortedRotations.flatMap((r) => {
    const label = `${resolveSymbolName(r.symbol)}（${r.symbol}）`
    const buyRow: RotationTradeRow = {
      date: r.entryDate,
      action: "BUY",
      price: r.entryPrice,
      quantity: r.size,
      value: r.entryPrice * r.size,
      profitLoss: 0,
      totalValue: runningTotal,
      reason: `${label} 轮动买入`,
    }
    runningTotal += r.pnl
    const sellRow: RotationTradeRow = {
      date: r.exitDate,
      action: "SELL",
      price: r.exitPrice,
      quantity: r.size,
      value: r.exitPrice * r.size,
      profitLoss: r.pnl,
      profitLossPercentage: r.periodReturnPct,
      totalValue: runningTotal,
      reason: `${label} 轮动卖出（${formatShortDate(r.entryDate)}买入，持有${r.holdingDays}天）`,
      entryPrice: r.entryPrice,
    }
    return [buyRow, sellRow]
  })
  if (holding) {
    const label = `${heldName}（${holding.symbol}）`
    recentTrades.push({
      date: holding.since,
      action: "BUY",
      price: holding.entryPrice,
      quantity: holding.size,
      value: holding.entryPrice * holding.size,
      profitLoss: 0,
      totalValue: runningTotal + holding.unrealizedPnl,
      reason: `${label} 轮动买入（持有中）`,
    })
  }

  return {
    symbol: data.strategyId,
    name: displayName,
    reportDate: data.reportDate,
    dateRange: data.dateRange,
    latestSignal: {
      action,
      asset: holding ? `${heldName}（${holding.symbol}）` : "空仓",
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

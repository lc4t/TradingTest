"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { ScrollArea } from "@/components/ui/scroll-area"

type Action = "HOLD" | "ROTATE" | "EXIT"

export interface RotationData {
  schemaVersion: string
  strategyId: string
  strategyName: string
  reportDate: string
  config: {
    universe: string[]
    weights: Record<string, number> | null
    mode: "basket" | "top_n"
    topN: number | null
    cashBuffer: number | null
    momentumFn: string
    lookback: number
    threshold: number
    schedule: string
    cooldownDays: number
    initialCapital: number
    commissionRate: number
    benchmark: string | null
    riskFreeRate: number
  }
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
    action: Action
    reason: string
    rotateFrom: string | null
    rotateTo: string | null
    evaluatedAt: string
  }
  universeRanking: Array<{
    symbol: string
    name: string
    momentum: number | null
    currentPrice: number
    targetWeight: number
    selected: boolean
    rank: number
  }>
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

const ACTION_LABEL: Record<Action, string> = {
  HOLD: "持有",
  ROTATE: "换股",
  EXIT: "空仓",
}
const ACTION_VARIANT: Record<Action, "buy" | "sell" | "watch"> = {
  HOLD: "buy",
  ROTATE: "sell",
  EXIT: "watch",
}

function fmtPct(v: number, digits = 2): string {
  const sign = v > 0 ? "+" : ""
  return `${sign}${v.toFixed(digits)}%`
}
/** 对总是非负的比例（回撤、波动率）不要加 "+"。 */
function fmtAbsPct(v: number, digits = 2): string {
  return `${v.toFixed(digits)}%`
}
function fmtMoney(v: number): string {
  return `¥${v.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`
}
function fmtDate(s: string): string {
  if (!s) return s
  return s.slice(0, 10)
}

export default function RotationReport({ data }: { data: RotationData }) {
  const recentRotations = [...data.rotations].slice(-20).reverse()
  return (
    <div className="space-y-4">
      {/* Header card */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-baseline gap-3">
            <CardTitle className="text-2xl">{data.strategyName}</CardTitle>
            <span className="text-sm text-muted-foreground">{data.strategyId}</span>
            <span className="ml-auto text-sm text-muted-foreground">
              报告日期: {data.reportDate}
            </span>
          </div>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-muted-foreground">
            候选: {data.config.universe.join(" / ")}
            <span className="mx-2">·</span>
            动量: <code>{data.config.momentumFn}</code> / lookback={data.config.lookback}d
            <span className="mx-2">·</span>
            调仓: {data.config.schedule}
            <span className="mx-2">·</span>
            {data.config.mode === "top_n" ? (
              <>Top-{data.config.topN} 等权 (cash={data.config.cashBuffer})</>
            ) : (
              <>加权篮子</>
            )}
            <span className="mx-2">·</span>
            区间: {data.dateRange.start} → {data.dateRange.end}
          </div>
        </CardContent>
      </Card>

      {/* Summary + Current + Next */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>综合表现</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <Row label="初始资金" value={fmtMoney(data.summary.initialCapital)} />
            <Row label="最终权益" value={fmtMoney(data.summary.finalValue)} />
            <Row label="总收益率" value={fmtPct(data.summary.totalReturnPct)} bold />
            <Row label="年化收益率" value={fmtPct(data.summary.annualReturn)} bold />
            <Row label="最大回撤" value={fmtAbsPct(data.summary.maxDrawdown)} />
            <Row label="夏普比率" value={data.summary.sharpe.toFixed(2)} />
            <Row label="波动率" value={fmtAbsPct(data.summary.volatility)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>当前持仓</CardTitle>
          </CardHeader>
          <CardContent className="text-sm">
            {data.currentHolding ? (
              <div className="space-y-2">
                <div className="text-lg font-semibold">
                  {data.currentHolding.name}{" "}
                  <span className="text-sm text-muted-foreground">
                    ({data.currentHolding.symbol})
                  </span>
                </div>
                <Row label="持有自" value={fmtDate(data.currentHolding.since)} />
                <Row label="入场价" value={data.currentHolding.entryPrice.toFixed(3)} />
                <Row label="当前价" value={data.currentHolding.currentPrice.toFixed(3)} />
                <Row label="持仓数量" value={data.currentHolding.size.toLocaleString()} />
                <Row label="市值" value={fmtMoney(data.currentHolding.marketValue)} />
                <Row
                  label="浮动盈亏"
                  value={`${fmtMoney(data.currentHolding.unrealizedPnl)} (${fmtPct(
                    data.currentHolding.unrealizedPnlPct
                  )})`}
                  bold
                />
              </div>
            ) : (
              <div className="text-muted-foreground">当前空仓</div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>下次预期动作</CardTitle>
              <Badge variant={ACTION_VARIANT[data.nextSignal.action]}>
                {ACTION_LABEL[data.nextSignal.action]}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="text-sm space-y-2">
            <div>{data.nextSignal.reason}</div>
            {data.nextSignal.action === "ROTATE" && (
              <div className="text-base font-mono">
                {data.nextSignal.rotateFrom ?? "(空仓)"} → {data.nextSignal.rotateTo}
              </div>
            )}
            <div className="text-muted-foreground">
              评估时间: {data.nextSignal.evaluatedAt}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Universe ranking */}
      <Card>
        <CardHeader>
          <CardTitle>候选标的动量排名</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>排名</TableHead>
                <TableHead>名称</TableHead>
                <TableHead>代码</TableHead>
                <TableHead className="text-right">动量</TableHead>
                <TableHead className="text-right">最新价</TableHead>
                <TableHead className="text-right">目标权重</TableHead>
                <TableHead>状态</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.universeRanking.map((row) => (
                <TableRow key={row.symbol}>
                  <TableCell>{row.rank}</TableCell>
                  <TableCell className="font-medium">{row.name}</TableCell>
                  <TableCell className="font-mono text-xs">{row.symbol}</TableCell>
                  <TableCell
                    className={`text-right ${
                      row.momentum !== null && row.momentum > 0
                        ? "text-green-600"
                        : "text-red-600"
                    }`}
                  >
                    {row.momentum === null ? "—" : fmtPct(row.momentum * 100, 2)}
                  </TableCell>
                  <TableCell className="text-right">{row.currentPrice.toFixed(3)}</TableCell>
                  <TableCell className="text-right">
                    {(row.targetWeight * 100).toFixed(1)}%
                  </TableCell>
                  <TableCell>
                    {row.selected ? <Badge variant="buy">持有</Badge> : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Detail metrics */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <MetricsCard title="收益指标" rows={data.metrics.returnMetrics} />
        <MetricsCard title="风险指标" rows={data.metrics.riskMetrics} />
        <MetricsCard title="风险调整" rows={data.metrics.riskAdjustedMetrics} />
        <MetricsCard title="交易统计" rows={data.metrics.tradingMetrics} />
      </div>

      {/* Annual returns */}
      {data.annualReturns.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>年度收益率</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {data.annualReturns.map((r) => (
                <div
                  key={r.year}
                  className={`rounded-md border px-3 py-2 text-sm ${
                    r.value >= 0 ? "border-green-200 bg-green-50" : "border-red-200 bg-red-50"
                  }`}
                >
                  <div className="text-xs text-muted-foreground">{r.year}</div>
                  <div className="font-semibold">{fmtPct(r.value)}</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Rotation history */}
      <Card>
        <CardHeader>
          <CardTitle>持仓段历史（最近 20 次）</CardTitle>
        </CardHeader>
        <CardContent>
          <ScrollArea className="h-[400px]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>标的</TableHead>
                  <TableHead>入场</TableHead>
                  <TableHead>出场</TableHead>
                  <TableHead className="text-right">持有天数</TableHead>
                  <TableHead className="text-right">入场价</TableHead>
                  <TableHead className="text-right">出场价</TableHead>
                  <TableHead className="text-right">单段收益</TableHead>
                  <TableHead className="text-right">盈亏</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentRotations.map((r, i) => (
                  <TableRow key={`${r.symbol}-${r.entryDate}-${i}`}>
                    <TableCell className="font-mono text-xs">{r.symbol}</TableCell>
                    <TableCell>{fmtDate(r.entryDate)}</TableCell>
                    <TableCell>{fmtDate(r.exitDate)}</TableCell>
                    <TableCell className="text-right">{r.holdingDays}</TableCell>
                    <TableCell className="text-right">{r.entryPrice.toFixed(3)}</TableCell>
                    <TableCell className="text-right">{r.exitPrice.toFixed(3)}</TableCell>
                    <TableCell
                      className={`text-right font-medium ${
                        r.periodReturnPct >= 0 ? "text-green-600" : "text-red-600"
                      }`}
                    >
                      {fmtPct(r.periodReturnPct)}
                    </TableCell>
                    <TableCell
                      className={`text-right ${
                        r.pnl >= 0 ? "text-green-600" : "text-red-600"
                      }`}
                    >
                      {fmtMoney(r.pnl)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  )
}

function Row({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className={bold ? "font-semibold" : ""}>{value}</span>
    </div>
  )
}

function MetricsCard({
  title,
  rows,
}: {
  title: string
  rows: Array<{ name: string; value: number | string; description?: string }>
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent className="text-sm space-y-1">
        {rows.map((r) => (
          <div key={r.name} className="flex justify-between" title={r.description}>
            <span className="text-muted-foreground">{r.name}</span>
            <span className="font-medium">
              {typeof r.value === "number" ? r.value.toLocaleString("zh-CN") : r.value}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

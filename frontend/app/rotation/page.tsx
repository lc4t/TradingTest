"use client"

import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import RotationReport, { type RotationData } from "@/components/RotationReport"
import { config } from "../../utils/config"

export default function RotationPage() {
  const [reports, setReports] = useState<RotationData[]>([])
  const [selected, setSelected] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    ;(async () => {
      try {
        const r = await fetch("/api/rotation-data")
        if (!r.ok) throw new Error("Failed to fetch rotation data")
        const data = (await r.json()) as RotationData[]
        if (!Array.isArray(data) || data.length === 0) {
          throw new Error("暂无轮动策略报告")
        }
        setReports(data)
      } catch (e) {
        setError(e instanceof Error ? e.message : "加载失败")
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  if (loading)
    return (
      <div className="flex min-h-screen items-center justify-center">Loading...</div>
    )
  if (error)
    return (
      <div className="flex min-h-screen items-center justify-center text-red-600">
        {error}
      </div>
    )
  if (reports.length === 0) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        暂无轮动策略
      </div>
    )
  }

  const current = reports[selected]
  return (
    <main className="min-h-screen bg-background p-4">
      <Card className="mb-4">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>动量轮动策略</CardTitle>
            <div className="rounded-md bg-muted px-3 py-1 text-sm text-muted-foreground">
              构建时间:{" "}
              {new Date(config.buildTime).toLocaleString("zh-CN", {
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
                hour12: false,
              })}
            </div>
          </div>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {reports.map((r, idx) => (
            <Button
              key={r.strategyId}
              onClick={() => setSelected(idx)}
              variant={
                idx === selected
                  ? r.nextSignal.action === "ROTATE"
                    ? "sell"
                    : r.nextSignal.action === "EXIT"
                    ? "watch"
                    : "buy"
                  : "watch"
              }
            >
              {r.strategyName}
            </Button>
          ))}
        </CardContent>
      </Card>

      <RotationReport data={current} />
    </main>
  )
}

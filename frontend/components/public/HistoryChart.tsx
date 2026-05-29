"use client";

import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api, type HistoryPoint } from "@/lib/api";
import { zhCN } from "@/lib/i18n/zh-CN";

// The trend chart shows a single source — UnionPay International. Its data is
// published as a per-date JSON, so we can backfill a full 30-day history
// immediately (scripts/backfill_unionpay.py) instead of waiting for our
// scraper to accumulate one day at a time. Values are shown as `1 MYR = X CNY`
// to match the rest of the site; the stored rate is MYR per 1 CNY, so we plot
// 1 / rate.
const CHANNEL = "unionpay";

type Props = {
  /** Window length in days (e.g. 30 or 365). */
  days: number;
  /** Heading shown above the chart. */
  title: string;
};

type Point = { date: string; value: number };

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { value?: number }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const v = payload[0]?.value;
  if (typeof v !== "number") return null;
  return (
    <div className="rounded-md border border-neutral-200 bg-white px-3 py-2 text-xs shadow-sm">
      <div className="text-neutral-500">{label}</div>
      <div className="mt-0.5 font-medium">1 MYR = {v.toFixed(4)} CNY</div>
    </div>
  );
}

export default function HistoryChart({ days, title }: Props) {
  const [points, setPoints] = useState<HistoryPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    api
      .ratesHistory(CHANNEL, days, "CNY", "MYR")
      .then((data) => {
        if (!cancelled) setPoints(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) setErr(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  // Stored rate is MYR per 1 CNY; the site displays 1 MYR = X CNY ⇒ plot 1/rate.
  const data: Point[] = points
    .map((p) => {
      const r = parseFloat(p.rate);
      return r > 0 ? { date: p.date, value: 1 / r } : null;
    })
    .filter((d): d is Point => d !== null);

  return (
    <section className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm md:p-5">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        <span className="text-xs text-neutral-400">{zhCN.chartSource}</span>
      </div>
      <div className="h-64 w-full">
        {loading ? (
          <div className="flex h-full items-center justify-center text-sm text-neutral-400">
            {zhCN.loadingDots}
          </div>
        ) : err ? (
          <div className="flex h-full items-center justify-center text-sm text-red-600">{err}</div>
        ) : data.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-neutral-400">
            {zhCN.noHistoryData}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={48} />
              <YAxis
                tick={{ fontSize: 11 }}
                domain={["auto", "auto"]}
                width={70}
                tickFormatter={(v) => Number(v).toFixed(4)}
              />
              <Tooltip content={<CustomTooltip />} />
              <Line type="monotone" dataKey="value" stroke="#111" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
      <p className="mt-2 text-xs text-neutral-400">{zhCN.chartUnit}</p>
    </section>
  );
}

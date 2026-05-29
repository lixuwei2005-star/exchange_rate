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

import { api, type IntradayPoint } from "@/lib/api";
import { zhCN } from "@/lib/i18n/zh-CN";

// Short-window trend from Wise, which we poll every ~10 min — fine enough for
// an intraday line. Toggle between the last 24h and 72h. Values shown as
// `1 MYR = X CNY` (= 1 / stored MYR-per-CNY rate) to match the rest of the
// site. Seeded by scripts/backfill_wise.py (hourly history) and kept fresh by
// the scraper.
const CHANNEL = "wise";
const RANGES = [24, 72] as const;

type Point = { t: number; value: number };

function fmtTime(ms: number, withDate: boolean): string {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, "0");
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return withDate ? `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm}` : hm;
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: { payload?: Point }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0]?.payload;
  if (!p) return null;
  return (
    <div className="rounded-md border border-neutral-200 bg-white px-3 py-2 text-xs shadow-sm">
      <div className="text-neutral-500">{fmtTime(p.t, true)}</div>
      <div className="mt-0.5 font-medium">1 MYR = {p.value.toFixed(4)} CNY</div>
    </div>
  );
}

export default function IntradayChart() {
  const [hours, setHours] = useState<number>(24);
  const [points, setPoints] = useState<IntradayPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    api
      .ratesIntraday(CHANNEL, hours, "CNY", "MYR")
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
  }, [hours]);

  // Stored rate is MYR per 1 CNY; the site displays 1 MYR = X CNY ⇒ plot 1/rate.
  const data: Point[] = points
    .map((p) => {
      const r = parseFloat(p.rate);
      return r > 0 ? { t: new Date(p.time).getTime(), value: 1 / r } : null;
    })
    .filter((d): d is Point => d !== null);

  const withDate = hours > 24;

  return (
    <section className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm md:p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold tracking-tight">{zhCN.chartTitleIntraday}</h2>
          <span className="text-xs text-neutral-400">{zhCN.chartSourceWise}</span>
        </div>
        <div className="flex gap-1">
          {RANGES.map((h) => (
            <button
              key={h}
              type="button"
              onClick={() => setHours(h)}
              className={`rounded px-2 py-1 text-xs ${
                h === hours
                  ? "bg-neutral-900 text-white"
                  : "border border-neutral-300 bg-white text-neutral-700 hover:bg-neutral-100"
              }`}
            >
              {h} {zhCN.unitHour}
            </button>
          ))}
        </div>
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
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                tick={{ fontSize: 11 }}
                minTickGap={50}
                tickFormatter={(v) => fmtTime(Number(v), withDate)}
              />
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

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

type Props = {
  channels: { code: string; name_zh: string }[];
};

export default function HistoryChart({ channels }: Props) {
  const initial = channels[0]?.code ?? "midmarket";
  const [active, setActive] = useState<string>(initial);
  const [points, setPoints] = useState<HistoryPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    api
      .ratesHistory(active, 30, "CNY", "MYR")
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
  }, [active]);

  const data = points.map((p) => ({ date: p.date, rate: parseFloat(p.rate) }));

  return (
    <section className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm md:p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold tracking-tight">{zhCN.chartTitle}</h2>
        <div className="flex flex-wrap gap-1">
          {channels.map((c) => (
            <button
              key={c.code}
              type="button"
              onClick={() => setActive(c.code)}
              className={`rounded px-2 py-1 text-xs ${
                c.code === active
                  ? "bg-neutral-900 text-white"
                  : "border border-neutral-300 bg-white text-neutral-700 hover:bg-neutral-100"
              }`}
            >
              {c.name_zh}
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
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} domain={["auto", "auto"]} width={70} />
              <Tooltip formatter={(v) => Number(v).toFixed(6)} />
              <Line type="monotone" dataKey="rate" stroke="#111" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
      <p className="mt-2 text-xs text-neutral-400">{zhCN.chartUnit}</p>
    </section>
  );
}

"use client";

import { useMemo, useState } from "react";

import type { LatestRate } from "@/lib/api";
import { grossCnyToMyr } from "@/lib/format";
import { zhCN } from "@/lib/i18n/zh-CN";

type SortKey = "receive" | "channel";

type Props = {
  rows: LatestRate[];
  amountCny: number;
};

/**
 * Minimal "你能拿到" table. Pure amount × stored_rate, no fee math, no live
 * Wise re-quote — rate freshness is shown in the table above, fees can be
 * looked up at the channel directly. Keeping this surface small avoids
 * misleading approximations.
 */
export default function ChannelTable({ rows, amountCny }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("receive");
  const [desc, setDesc] = useState(true);

  const enriched = useMemo(() => {
    return rows.map((r) => ({
      ...r,
      myr: r.is_stale ? null : grossCnyToMyr(amountCny, r.rate),
    }));
  }, [rows, amountCny]);

  const sorted = useMemo(() => {
    const arr = [...enriched];
    arr.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "receive") {
        cmp = (a.myr ?? -1) - (b.myr ?? -1);
      } else {
        cmp = a.channel_name_zh.localeCompare(b.channel_name_zh, "zh");
      }
      return desc ? -cmp : cmp;
    });
    return arr;
  }, [enriched, sortKey, desc]);

  function onSort(k: SortKey) {
    if (k === sortKey) setDesc((d) => !d);
    else {
      setSortKey(k);
      setDesc(true);
    }
  }

  return (
    <div className="overflow-x-auto rounded-2xl border border-neutral-200 bg-white shadow-sm">
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase tracking-wider text-neutral-400">
          <tr>
            <Th onClick={() => onSort("channel")} active={sortKey === "channel"} desc={desc}>
              {zhCN.tableHeaderChannel}
            </Th>
            <Th
              onClick={() => onSort("receive")}
              active={sortKey === "receive"}
              desc={desc}
              align="right"
            >
              {zhCN.tableHeaderReceive}
            </Th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr
              key={r.channel_code}
              className={`border-t border-neutral-100 ${r.is_stale ? "text-neutral-400" : ""}`}
            >
              <td className="px-4 py-3">{r.channel_name_zh}</td>
              <td className="px-4 py-3 text-right font-medium tabular-nums">
                {r.is_stale ? zhCN.unavailable : r.myr?.toFixed(2)}
              </td>
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={2} className="px-3 py-6 text-center text-neutral-500">
                {zhCN.unavailable}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Th({
  children,
  onClick,
  active,
  desc,
  align = "left",
}: {
  children: React.ReactNode;
  onClick: () => void;
  active: boolean;
  desc: boolean;
  align?: "left" | "right";
}) {
  return (
    <th className={`px-4 py-2.5 font-medium ${align === "right" ? "text-right" : "text-left"}`}>
      <button
        type="button"
        onClick={onClick}
        className={`inline-flex items-center gap-1 hover:text-neutral-700 ${
          active ? "text-neutral-700" : ""
        }`}
      >
        {children}
        {active && <span aria-hidden>{desc ? "▼" : "▲"}</span>}
      </button>
    </th>
  );
}

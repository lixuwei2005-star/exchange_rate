"use client";

import { useMemo, useState } from "react";

import {
  convertCnyToMyr,
  displayCnyPerMyr,
  feeForChannel,
  feeLabel,
  relativeTimeZh,
} from "@/lib/format";
import type { LatestRate } from "@/lib/api";
import { zhCN } from "@/lib/i18n/zh-CN";

type SortKey = "receive" | "channel" | "updated";

type Props = {
  rows: LatestRate[];
  amountCny: number;
};

export default function ChannelTable({ rows, amountCny }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("receive");
  const [desc, setDesc] = useState(true);

  const enriched = useMemo(() => {
    return rows.map((r) => {
      const fee = feeForChannel(r.channel_code);
      const myr = r.is_stale ? null : convertCnyToMyr(amountCny, r.rate, fee);
      return { ...r, myr };
    });
  }, [rows, amountCny]);

  const sorted = useMemo(() => {
    const arr = [...enriched];
    arr.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "receive") {
        cmp = (a.myr ?? -1) - (b.myr ?? -1);
      } else if (sortKey === "channel") {
        cmp = a.channel_name_zh.localeCompare(b.channel_name_zh, "zh");
      } else {
        cmp = new Date(a.fetched_at).getTime() - new Date(b.fetched_at).getTime();
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
    <div className="overflow-x-auto rounded-lg border border-neutral-200 bg-white">
      <table className="w-full text-sm">
        <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500">
          <tr>
            <Th onClick={() => onSort("channel")} active={sortKey === "channel"} desc={desc}>
              {zhCN.tableHeaderChannel}
            </Th>
            <th className="px-3 py-2 text-right">{zhCN.tableHeaderRate}</th>
            <th className="px-3 py-2 text-right">{zhCN.tableHeaderFee}</th>
            <Th
              onClick={() => onSort("receive")}
              active={sortKey === "receive"}
              desc={desc}
              align="right"
            >
              {zhCN.tableHeaderReceive}
            </Th>
            <Th
              onClick={() => onSort("updated")}
              active={sortKey === "updated"}
              desc={desc}
              align="right"
            >
              {zhCN.tableHeaderUpdated}
            </Th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr
              key={r.channel_code}
              className={`border-t border-neutral-100 ${r.is_stale ? "text-neutral-400" : ""}`}
            >
              <td className="px-3 py-2">{r.channel_name_zh}</td>
              <td className="px-3 py-2 text-right tabular-nums">{displayCnyPerMyr(r.rate)}</td>
              <td className="px-3 py-2 text-right">{feeLabel(r.channel_code)}</td>
              <td className="px-3 py-2 text-right tabular-nums">
                {r.is_stale ? zhCN.unavailable : r.myr?.toFixed(2)}
              </td>
              <td className="px-3 py-2 text-right text-xs text-neutral-500">
                {r.is_stale ? zhCN.unavailable : relativeTimeZh(r.fetched_at)}
              </td>
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={5} className="px-3 py-6 text-center text-neutral-500">
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
    <th className={`px-3 py-2 ${align === "right" ? "text-right" : "text-left"}`}>
      <button
        type="button"
        onClick={onClick}
        className={`inline-flex items-center gap-1 hover:text-neutral-900 ${
          active ? "text-neutral-900" : ""
        }`}
      >
        {children}
        {active && <span aria-hidden>{desc ? "▼" : "▲"}</span>}
      </button>
    </th>
  );
}

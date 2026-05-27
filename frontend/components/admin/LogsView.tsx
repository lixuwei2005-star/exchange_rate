"use client";

import { useEffect, useState } from "react";

import { api, type AdminLog } from "@/lib/api";

const LEVELS = [
  { value: "", label: "全部" },
  { value: "info", label: "info" },
  { value: "warn", label: "warn" },
  { value: "error", label: "error" },
];

function levelClass(level: string) {
  if (level === "error") return "text-red-700";
  if (level === "warn") return "text-amber-700";
  return "text-neutral-600";
}

export default function LogsView({
  initial,
  initialLevel,
}: {
  initial: AdminLog[];
  initialLevel: string;
}) {
  const [level, setLevel] = useState(initialLevel);
  const [rows, setRows] = useState<AdminLog[]>(initial);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (level === initialLevel) return; // initial render already has data
    setBusy(true);
    api.admin
      .logs(undefined, level || undefined, 200)
      .then(setRows)
      .finally(() => setBusy(false));
  }, [level, initialLevel]);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm">
        <span className="text-neutral-500">Level:</span>
        {LEVELS.map((l) => (
          <button
            key={l.value}
            type="button"
            onClick={() => setLevel(l.value)}
            className={`rounded px-2 py-1 ${
              level === l.value ? "bg-neutral-900 text-white" : "bg-white text-neutral-700 border"
            }`}
          >
            {l.label}
          </button>
        ))}
        {busy && <span className="text-xs text-neutral-400">加载中...</span>}
      </div>

      <pre className="max-h-[70vh] overflow-auto rounded-lg border border-neutral-200 bg-white p-3 font-mono text-xs">
        {rows.length === 0 ? (
          <span className="text-neutral-500">无日志</span>
        ) : (
          rows.map((r) => (
            <div key={r.id}>
              <span className="text-neutral-400">
                {new Date(r.created_at).toLocaleString("zh-CN")}
              </span>{" "}
              <span className={levelClass(r.level)}>[{r.level}]</span>{" "}
              <span className="text-neutral-500">{r.channel_code ?? "-"}</span> {r.message}
            </div>
          ))
        )}
      </pre>
    </div>
  );
}

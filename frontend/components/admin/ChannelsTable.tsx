"use client";

import { useState } from "react";

import { api, type AdminChannel } from "@/lib/api";

function statusBadge(c: AdminChannel) {
  if (!c.active) return <span className="text-neutral-400">disabled</span>;
  if (!c.last_success_at) return <span className="text-amber-700">stale</span>;
  return <span className="text-emerald-700">fresh</span>;
}

export default function ChannelsTable({ initial }: { initial: AdminChannel[] }) {
  const [rows, setRows] = useState<AdminChannel[]>(initial);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function toggleActive(c: AdminChannel) {
    setBusy(c.code);
    setErr(null);
    try {
      const next = await api.admin.patchChannel(c.code, { active: !c.active });
      setRows((rs) => rs.map((r) => (r.code === c.code ? next : r)));
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function scrapeNow(c: AdminChannel) {
    setBusy(c.code);
    setErr(null);
    try {
      await api.admin.scrapeNow(c.code);
      // refresh row so last_success_at updates
      const refreshed = await api.admin.channels();
      setRows(refreshed);
    } catch (e) {
      setErr(`${c.code}: ${String(e)}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-200 bg-white">
      {err && (
        <div className="border-b border-red-200 bg-red-50 p-2 text-sm text-red-700">{err}</div>
      )}
      <table className="w-full text-sm">
        <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500">
          <tr>
            <th className="px-3 py-2">Code</th>
            <th className="px-3 py-2">中文名</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Last success</th>
            <th className="px-3 py-2">Last error</th>
            <th className="px-3 py-2 text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.code} className="border-t border-neutral-100">
              <td className="px-3 py-2 font-mono text-xs">{c.code}</td>
              <td className="px-3 py-2">{c.name_zh}</td>
              <td className="px-3 py-2">{statusBadge(c)}</td>
              <td className="px-3 py-2 text-xs text-neutral-500">
                {c.last_success_at ? new Date(c.last_success_at).toLocaleString("zh-CN") : "—"}
              </td>
              <td className="px-3 py-2 text-xs text-red-600">
                {c.last_error_msg ? c.last_error_msg.slice(0, 80) : "—"}
              </td>
              <td className="px-3 py-2 text-right">
                <div className="inline-flex gap-2">
                  <button
                    type="button"
                    disabled={busy === c.code}
                    onClick={() => toggleActive(c)}
                    className="rounded border border-neutral-300 bg-white px-2 py-1 text-xs hover:bg-neutral-100 disabled:opacity-60"
                  >
                    {c.active ? "Disable" : "Enable"}
                  </button>
                  <button
                    type="button"
                    disabled={busy === c.code}
                    onClick={() => scrapeNow(c)}
                    className="rounded bg-neutral-900 px-2 py-1 text-xs text-white disabled:opacity-60"
                  >
                    Scrape now
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

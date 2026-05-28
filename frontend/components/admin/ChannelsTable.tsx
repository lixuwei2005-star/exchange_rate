"use client";

import { Fragment, useState } from "react";

import { api, type AdminChannel, type ChannelScheduleKind } from "@/lib/api";

function statusBadge(c: AdminChannel) {
  if (!c.active) return <span className="text-neutral-400">disabled</span>;
  if (!c.last_success_at) return <span className="text-amber-700">stale</span>;
  return <span className="text-emerald-700">fresh</span>;
}

function scheduleLabel(c: AdminChannel) {
  if (c.schedule_kind === "daily" && c.daily_time_cn) {
    return `每天 ${c.daily_time_cn}（东八区）`;
  }
  if (c.schedule_kind === "interval" && c.interval_minutes) {
    return `每 ${c.interval_minutes} 分钟`;
  }
  // schedule kind says daily but no time, or interval but no minutes —
  // the scheduler falls back to 60 min. Show the same so admin knows what
  // is actually running.
  return c.schedule_kind === "daily" ? "未设置（默认 60 分钟）" : "默认（60 分钟）";
}

// HH:MM in 00:00–23:59.
const HHMM_RE = /^([01]?\d|2[0-3]):([0-5]\d)$/;

type EditorState = {
  kind: ChannelScheduleKind;
  intervalText: string; // text so user can type freely; parsed on save
  dailyText: string;
};

function initialEditor(c: AdminChannel): EditorState {
  return {
    kind: c.schedule_kind,
    intervalText: c.interval_minutes ? String(c.interval_minutes) : "60",
    dailyText: c.daily_time_cn ?? "09:00",
  };
}

export default function ChannelsTable({ initial }: { initial: AdminChannel[] }) {
  const [rows, setRows] = useState<AdminChannel[]>(initial);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editor, setEditor] = useState<EditorState | null>(null);

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
      const refreshed = await api.admin.channels();
      setRows(refreshed);
    } catch (e) {
      setErr(`${c.code}: ${String(e)}`);
    } finally {
      setBusy(null);
    }
  }

  function startEdit(c: AdminChannel) {
    setEditing(c.code);
    setEditor(initialEditor(c));
    setErr(null);
  }

  function cancelEdit() {
    setEditing(null);
    setEditor(null);
  }

  async function saveEdit(c: AdminChannel) {
    if (!editor) return;
    setErr(null);

    if (editor.kind === "interval") {
      const n = Number(editor.intervalText);
      if (!Number.isInteger(n) || n < 1 || n > 1440) {
        setErr("间隔分钟需在 1 到 1440 之间");
        return;
      }
      setBusy(c.code);
      try {
        const next = await api.admin.patchChannel(c.code, {
          schedule_kind: "interval",
          interval_minutes: n,
        });
        setRows((rs) => rs.map((r) => (r.code === c.code ? next : r)));
        cancelEdit();
      } catch (e) {
        setErr(String(e));
      } finally {
        setBusy(null);
      }
    } else {
      const v = editor.dailyText.trim();
      if (!HHMM_RE.test(v)) {
        setErr("时间格式需为 HH:MM（00:00 – 23:59）");
        return;
      }
      setBusy(c.code);
      try {
        const next = await api.admin.patchChannel(c.code, {
          schedule_kind: "daily",
          daily_time_cn: v,
        });
        setRows((rs) => rs.map((r) => (r.code === c.code ? next : r)));
        cancelEdit();
      } catch (e) {
        setErr(String(e));
      } finally {
        setBusy(null);
      }
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
            <th className="px-3 py-2">Schedule</th>
            <th className="px-3 py-2">Last success</th>
            <th className="px-3 py-2">Last error</th>
            <th className="px-3 py-2 text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const isEditing = editing === c.code && editor !== null;
            return (
              <Fragment key={c.code}>
                <tr className="border-t border-neutral-100 align-top">
                  <td className="px-3 py-2 font-mono text-xs">{c.code}</td>
                  <td className="px-3 py-2">{c.name_zh}</td>
                  <td className="px-3 py-2">{statusBadge(c)}</td>
                  <td className="px-3 py-2 text-xs text-neutral-700">{scheduleLabel(c)}</td>
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
                        disabled={busy === c.code || isEditing}
                        onClick={() => startEdit(c)}
                        className="rounded border border-neutral-300 bg-white px-2 py-1 text-xs hover:bg-neutral-100 disabled:opacity-60"
                      >
                        调度
                      </button>
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
                {isEditing && editor && (
                  <tr className="border-t border-neutral-100 bg-neutral-50">
                    <td colSpan={7} className="px-3 py-3">
                      <div className="flex flex-col gap-3">
                        <div className="text-xs text-neutral-600">
                          配置 <span className="font-mono">{c.code}</span> 的刷新策略。时间使用
                          <span className="font-medium"> 东八区 (UTC+8) </span>
                          —— Asia/Shanghai。
                        </div>
                        <div className="flex flex-wrap items-center gap-4">
                          <label className="inline-flex items-center gap-2 text-sm">
                            <input
                              type="radio"
                              name={`kind-${c.code}`}
                              checked={editor.kind === "interval"}
                              onChange={() => setEditor({ ...editor, kind: "interval" })}
                            />
                            固定间隔
                          </label>
                          <label className="inline-flex items-center gap-2 text-sm">
                            <input
                              type="radio"
                              name={`kind-${c.code}`}
                              checked={editor.kind === "daily"}
                              onChange={() => setEditor({ ...editor, kind: "daily" })}
                            />
                            每日定时
                          </label>
                        </div>
                        {editor.kind === "interval" ? (
                          <div className="flex items-center gap-2 text-sm">
                            <span className="text-neutral-600">每</span>
                            <input
                              type="number"
                              min={1}
                              max={1440}
                              step={1}
                              value={editor.intervalText}
                              onChange={(e) =>
                                setEditor({ ...editor, intervalText: e.target.value })
                              }
                              className="w-24 rounded border border-neutral-300 px-2 py-1"
                            />
                            <span className="text-neutral-600">分钟刷新一次（范围 1–1440）</span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2 text-sm">
                            <span className="text-neutral-600">每天</span>
                            <input
                              type="time"
                              value={editor.dailyText}
                              onChange={(e) => setEditor({ ...editor, dailyText: e.target.value })}
                              className="rounded border border-neutral-300 px-2 py-1"
                            />
                            <span className="text-neutral-600">刷新一次（东八区）</span>
                          </div>
                        )}
                        <div className="flex gap-2">
                          <button
                            type="button"
                            disabled={busy === c.code}
                            onClick={() => saveEdit(c)}
                            className="rounded bg-neutral-900 px-3 py-1 text-xs text-white disabled:opacity-60"
                          >
                            保存
                          </button>
                          <button
                            type="button"
                            disabled={busy === c.code}
                            onClick={cancelEdit}
                            className="rounded border border-neutral-300 bg-white px-3 py-1 text-xs hover:bg-neutral-100 disabled:opacity-60"
                          >
                            取消
                          </button>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

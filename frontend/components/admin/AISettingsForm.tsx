"use client";

import { useState } from "react";

import { api, type AdminSetting, type AdminSummary, type AITestResult } from "@/lib/api";

type Props = {
  initial: AdminSetting[];
  summaries: AdminSummary[];
};

const FIELD_LABELS: Record<string, string> = {
  "ai.enabled": "启用 AI 摘要 (true / false)",
  "ai.base_url": "Base URL（OpenAI 兼容，需以 /v1 结尾）",
  "ai.api_key": "API Key（保存后不再可见，留空表示不修改）",
  "ai.model": "Model 名（如 gpt-4o-mini / deepseek-chat / qwen-turbo）",
  "ai.system_prompt": "System prompt（中文，多行）",
  "ai.temperature": "Temperature",
  "ai.max_tokens": "max_tokens",
  "ai.daily_budget_usd": "每日预算（USD）",
  "ai.cost_per_1k_input": "输入价格 / 1k tokens (USD)",
  "ai.cost_per_1k_output": "输出价格 / 1k tokens (USD)",
};

const MULTILINE_KEYS = new Set(["ai.system_prompt"]);

// These two are edited via the dedicated 定时生成 panel below, not the
// generic field list (which would show a raw cron string + true/false).
const SCHEDULE_ENABLED_KEY = "ai.schedule_enabled";
const SCHEDULE_CRON_KEY = "ai.schedule_cron";
const SCHEDULE_KEYS = new Set([SCHEDULE_ENABLED_KEY, SCHEDULE_CRON_KEY]);

const WEEKDAYS: { value: string; label: string }[] = [
  { value: "*", label: "每天" },
  { value: "mon", label: "每周一" },
  { value: "tue", label: "每周二" },
  { value: "wed", label: "每周三" },
  { value: "thu", label: "每周四" },
  { value: "fri", label: "每周五" },
  { value: "sat", label: "每周六" },
  { value: "sun", label: "每周日" },
];
const WEEKDAY_VALUES = new Set(WEEKDAYS.map((w) => w.value));

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** Parse a "M H * * D" cron into the friendly day + HH:MM controls. */
function parseCron(cron: string): { day: string; time: string } {
  const parts = cron.trim().split(/\s+/);
  if (parts.length === 5) {
    const m = Number(parts[0]);
    const h = Number(parts[1]);
    const dow = (parts[4] ?? "*").toLowerCase();
    const day = WEEKDAY_VALUES.has(dow) ? dow : "*";
    if (Number.isFinite(m) && Number.isFinite(h)) {
      return { day, time: `${pad2(h)}:${pad2(m)}` };
    }
  }
  return { day: "*", time: "09:00" };
}

/** Build a standard 5-field cron (SGT) from the friendly controls. A weekly
 *  schedule uses a day-of-week abbreviation (mon..sun) so APScheduler reads it
 *  unambiguously (its numeric day-of-week differs from standard cron). */
function composeCron(day: string, time: string): string {
  const [hh, mm] = time.split(":");
  const hour = Number(hh);
  const minute = Number(mm);
  const dow = WEEKDAY_VALUES.has(day) ? day : "*";
  return `${Number.isFinite(minute) ? minute : 0} ${Number.isFinite(hour) ? hour : 9} * * ${dow}`;
}

export default function AISettingsForm({ initial, summaries }: Props) {
  const [rows, setRows] = useState<AdminSetting[]>(initial);
  const [dirty, setDirty] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [test, setTest] = useState<AITestResult | null>(null);

  // Schedule panel state, derived from the current settings once.
  const cronInit = initial.find((s) => s.key === SCHEDULE_CRON_KEY)?.value ?? "0 9 * * *";
  const enabledInit =
    (initial.find((s) => s.key === SCHEDULE_ENABLED_KEY)?.value ?? "false") === "true";
  const parsed = parseCron(cronInit);
  const [schedEnabled, setSchedEnabled] = useState(enabledInit);
  const [schedDay, setSchedDay] = useState(parsed.day);
  const [schedTime, setSchedTime] = useState(parsed.time);

  function updateSchedule(next: { enabled?: boolean; day?: string; time?: string }) {
    const enabled = next.enabled ?? schedEnabled;
    const day = next.day ?? schedDay;
    const time = next.time ?? schedTime;
    if (next.enabled !== undefined) setSchedEnabled(next.enabled);
    if (next.day !== undefined) setSchedDay(next.day);
    if (next.time !== undefined) setSchedTime(next.time);
    setDirty((d) => ({
      ...d,
      [SCHEDULE_ENABLED_KEY]: enabled ? "true" : "false",
      [SCHEDULE_CRON_KEY]: composeCron(day, time),
    }));
  }

  function valueFor(s: AdminSetting): string {
    if (s.key in dirty) return dirty[s.key] ?? "";
    return s.is_encrypted ? "" : s.value;
  }

  function setField(key: string, value: string) {
    setDirty((d) => ({ ...d, [key]: value }));
  }

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      for (const [key, value] of Object.entries(dirty)) {
        const next = await api.admin.putSetting(key, value);
        setRows((rs) => rs.map((r) => (r.key === key ? next : r)));
      }
      setDirty({});
      setMsg("已保存");
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runTest() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.admin.aiTest();
      setTest(r);
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function regenerate() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.admin.regenerateSummary();
      setMsg(`已重新生成：${r.summary}`);
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  const visibleRows = rows.filter((s) => !SCHEDULE_KEYS.has(s.key));

  return (
    <div className="space-y-6">
      <div className="space-y-4 rounded-lg border border-neutral-200 bg-white p-4">
        {visibleRows.map((s) => {
          const label = FIELD_LABELS[s.key] ?? s.key;
          const placeholder = s.is_encrypted && s.value === "***" ? "已保存（留空表示不修改）" : "";
          if (MULTILINE_KEYS.has(s.key)) {
            return (
              <label key={s.key} className="block">
                <span className="block text-xs text-neutral-600">{label}</span>
                <textarea
                  value={valueFor(s)}
                  placeholder={placeholder}
                  onChange={(e) => setField(s.key, e.target.value)}
                  rows={5}
                  className="mt-1 block w-full rounded border border-neutral-300 px-3 py-2 font-mono text-sm"
                />
              </label>
            );
          }
          return (
            <label key={s.key} className="block">
              <span className="block text-xs text-neutral-600">{label}</span>
              <input
                type={s.is_encrypted ? "password" : "text"}
                value={valueFor(s)}
                placeholder={placeholder}
                onChange={(e) => setField(s.key, e.target.value)}
                className="mt-1 block w-full rounded border border-neutral-300 px-3 py-2 font-mono text-sm"
              />
            </label>
          );
        })}

        {/* 定时自动生成：开关 + 每周固定时间（写入 ai.schedule_enabled / ai.schedule_cron） */}
        <div className="space-y-3 rounded border border-neutral-200 bg-neutral-50 p-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={schedEnabled}
              onChange={(e) => updateSchedule({ enabled: e.target.checked })}
            />
            <span className="font-medium">定时自动生成摘要</span>
          </label>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <select
              value={schedDay}
              disabled={!schedEnabled}
              onChange={(e) => updateSchedule({ day: e.target.value })}
              className="rounded border border-neutral-300 px-2 py-1 disabled:opacity-50"
            >
              {WEEKDAYS.map((w) => (
                <option key={w.value} value={w.value}>
                  {w.label}
                </option>
              ))}
            </select>
            <input
              type="time"
              value={schedTime}
              disabled={!schedEnabled}
              onChange={(e) => updateSchedule({ time: e.target.value })}
              className="rounded border border-neutral-300 px-2 py-1 disabled:opacity-50"
            />
            <span className="text-xs text-neutral-500">（新加坡时区 SGT）</span>
          </div>
          <p className="text-xs text-neutral-400">
            开启后按上面设定的时间自动重新生成摘要；关闭则只能手动「立即生成摘要」。改完记得点保存。
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={busy || Object.keys(dirty).length === 0}
            onClick={save}
            className="rounded bg-neutral-900 px-3 py-1.5 text-sm text-white disabled:opacity-60"
          >
            保存
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={runTest}
            className="rounded border border-neutral-300 bg-white px-3 py-1.5 text-sm disabled:opacity-60"
          >
            测试连接
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={regenerate}
            className="rounded border border-neutral-300 bg-white px-3 py-1.5 text-sm disabled:opacity-60"
          >
            立即生成摘要
          </button>
          {msg && <span className="text-sm text-neutral-700">{msg}</span>}
        </div>
        {test && (
          <pre className="overflow-auto rounded border border-neutral-200 bg-neutral-50 p-2 text-xs">
            {JSON.stringify(test, null, 2)}
          </pre>
        )}
      </div>

      <div className="rounded-lg border border-neutral-200 bg-white p-4">
        <h2 className="mb-2 text-sm font-semibold">最近 5 条摘要</h2>
        {summaries.length === 0 && <p className="text-sm text-neutral-500">还没有摘要。</p>}
        <ul className="space-y-2 text-sm">
          {summaries.map((s) => (
            <li key={s.id} className="border-t border-neutral-100 pt-2">
              <p>{s.summary_zh}</p>
              <p className="text-xs text-neutral-500">
                {s.model_used} · {new Date(s.generated_at).toLocaleString("zh-CN")}
              </p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

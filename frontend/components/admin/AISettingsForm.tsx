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
  "ai.schedule_cron": "Cron 表达式（SGT 时区）",
  "ai.daily_budget_usd": "每日预算（USD）",
  "ai.cost_per_1k_input": "输入价格 / 1k tokens (USD)",
  "ai.cost_per_1k_output": "输出价格 / 1k tokens (USD)",
};

const MULTILINE_KEYS = new Set(["ai.system_prompt"]);

export default function AISettingsForm({ initial, summaries }: Props) {
  const [rows, setRows] = useState<AdminSetting[]>(initial);
  const [dirty, setDirty] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [test, setTest] = useState<AITestResult | null>(null);

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

  return (
    <div className="space-y-6">
      <div className="space-y-4 rounded-lg border border-neutral-200 bg-white p-4">
        {rows.map((s) => {
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

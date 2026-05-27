"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import SiteTitle from "@/components/public/SiteTitle";
import { apiFetch, HttpError } from "@/lib/api";
import { zhCN } from "@/lib/i18n/zh-CN";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await apiFetch<{ ok: boolean }>("/api/admin/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      router.replace("/admin");
      router.refresh();
    } catch (err) {
      if (err instanceof HttpError) setError(zhCN.loginFailed);
      else setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-4">
      <div className="mb-8 text-center">
        <SiteTitle size="md" />
        <p className="mt-2 text-sm text-neutral-500">{zhCN.adminLogin}</p>
      </div>
      <form onSubmit={onSubmit} className="space-y-4 rounded-lg border bg-white p-6">
        <label className="block">
          <span className="text-sm text-neutral-700">{zhCN.username}</span>
          <input
            type="text"
            autoComplete="username"
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="mt-1 block w-full rounded border border-neutral-300 px-3 py-2"
          />
        </label>
        <label className="block">
          <span className="text-sm text-neutral-700">{zhCN.password}</span>
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 block w-full rounded border border-neutral-300 px-3 py-2"
          />
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded bg-neutral-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {busy ? zhCN.loadingDots : zhCN.loginButton}
        </button>
      </form>
    </main>
  );
}

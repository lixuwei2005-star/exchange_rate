"use client";

import { useState } from "react";

import { apiFetch } from "@/lib/api";
import { zhCN } from "@/lib/i18n/zh-CN";

export default function LogoutButton() {
  const [busy, setBusy] = useState(false);
  const onClick = async () => {
    setBusy(true);
    try {
      await apiFetch<{ ok: boolean }>("/api/admin/logout", { method: "POST" });
    } catch {
      // ignore — even if the call fails, push the user to the login screen
    } finally {
      window.location.href = "/admin/login";
    }
  };
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className="rounded border border-neutral-300 bg-white px-3 py-1.5 text-sm hover:bg-neutral-100 disabled:opacity-60"
    >
      {busy ? zhCN.loadingDots : zhCN.logoutButton}
    </button>
  );
}

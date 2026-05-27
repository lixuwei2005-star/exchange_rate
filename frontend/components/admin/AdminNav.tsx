import Link from "next/link";

import LogoutButton from "@/components/admin/LogoutButton";

const ITEMS = [
  { href: "/admin", label: "Dashboard" },
  { href: "/admin/channels", label: "Channels" },
  { href: "/admin/ai", label: "AI" },
  { href: "/admin/logs", label: "Logs" },
];

export default function AdminNav({ username }: { username: string }) {
  return (
    <header className="border-b border-neutral-200 bg-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-5">
          <Link href="/admin" className="text-sm font-semibold">
            管理后台
          </Link>
          <nav className="flex gap-3 text-sm">
            {ITEMS.map((i) => (
              <Link key={i.href} href={i.href} className="text-neutral-700 hover:text-neutral-900">
                {i.label}
              </Link>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-neutral-500">{username}</span>
          <LogoutButton />
        </div>
      </div>
    </header>
  );
}

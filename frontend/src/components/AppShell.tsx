/**
 * src/components/AppShell.tsx
 * ===========================
 * Mission-control shell: left rail navigation + live agent status header.
 */
"use client";

import clsx from "clsx";
import {
  LayoutDashboard,
  Users,
  Send,
  MessageSquare,
  Calendar,
  LogOut,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, tokenStore, type User } from "@/lib/api";

const NAV = [
  { href: "/dashboard", label: "Mission Control", icon: LayoutDashboard },
  { href: "/leads", label: "Leads", icon: Users },
  { href: "/campaigns", label: "Campaigns", icon: Send },
  { href: "/replies", label: "Reply Queue", icon: MessageSquare },
  { href: "/meetings", label: "Meetings", icon: Calendar },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    if (!tokenStore.getAccess()) {
      router.replace("/login");
      return;
    }
    api.me().then(setUser).catch(() => router.replace("/login"));
  }, [router]);

  const logout = () => {
    tokenStore.clear();
    router.replace("/login");
  };

  return (
    <div className="flex min-h-screen panel-grid">
      {/* Left rail */}
      <aside className="flex w-60 flex-col border-r border-ink-600/60 bg-ink-950/80 backdrop-blur">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <span className="live-dot" aria-hidden />
          <div className="leading-tight">
            <div className="font-mono text-sm font-semibold tracking-tight text-mist-100">
              SALES&nbsp;AGENT
            </div>
            <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-signal-dim">
              autonomous · live
            </div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-2">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={clsx(
                  "mb-1 flex items-center gap-3 rounded-panel px-3 py-2.5 text-sm transition-colors",
                  active
                    ? "bg-signal/10 text-signal"
                    : "text-mist-400 hover:bg-ink-800 hover:text-mist-200",
                )}
              >
                <Icon size={17} strokeWidth={2} />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-ink-600/60 px-3 py-3">
          {user && (
            <div className="mb-2 px-2">
              <div className="truncate text-sm text-mist-200">{user.full_name}</div>
              <div className="truncate font-mono text-[11px] text-mist-500">{user.email}</div>
            </div>
          )}
          <button
            onClick={logout}
            className="flex w-full items-center gap-3 rounded-panel px-3 py-2 text-sm text-mist-400 transition-colors hover:bg-ink-800 hover:text-coral"
          >
            <LogOut size={16} />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-x-hidden">{children}</main>
    </div>
  );
}

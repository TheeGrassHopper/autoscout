"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useSession, signOut } from "next-auth/react";
import { type Stats, type PipelineStatus, getStats, getPipelineStatus } from "@/lib/api";

const baseNav = [
  { href: "/",         label: "Dashboard", icon: "🏠" },
  { href: "/deals",    label: "Deals",     icon: "🔥" },
  { href: "/market",   label: "Market",    icon: "📊" },
  { href: "/searches", label: "Searches",  icon: "🔍" },
  { href: "/runs",     label: "Run Logs",  icon: "📋" },
  { href: "/profile",  label: "Profile",   icon: "👤" },
];

function minutesAgo(isoString: string): number {
  return Math.floor((Date.now() - new Date(isoString).getTime()) / 60_000);
}

export default function Sidebar() {
  const path = usePathname();
  const router = useRouter();
  const { data: session } = useSession();
  const user = session?.user ?? null;
  const [nav, setNav] = useState(baseNav);
  const [stats, setStats] = useState<Stats | null>(null);
  const [pipeline, setPipeline] = useState<PipelineStatus | null>(null);

  useEffect(() => {
    if (user?.role === "admin") {
      setNav([...baseNav, { href: "/admin", label: "Admin", icon: "🛡️" }]);
    } else {
      setNav(baseNav);
    }
  }, [user?.role]);

  // Poll stats + pipeline status every 10 seconds
  useEffect(() => {
    let cancelled = false;

    async function fetchData() {
      try {
        const [s, p] = await Promise.all([getStats(), getPipelineStatus()]);
        if (!cancelled) {
          setStats(s);
          setPipeline(p);
        }
      } catch {
        // silently ignore network errors during polling
      }
    }

    fetchData();
    const id = setInterval(fetchData, 10_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const logout = async () => {
    await signOut({ callbackUrl: "/login" });
  };

  // Pipeline status label + dot color
  function PipelineDot() {
    if (!pipeline) return null;

    if (pipeline.running) {
      return (
        <div className="flex items-center gap-2 px-4 pb-3">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500" />
          </span>
          <span className="text-xs text-blue-400">Pipeline running</span>
        </div>
      );
    }

    if (pipeline.last_run) {
      const mins = minutesAgo(pipeline.last_run);
      const label = mins < 1 ? "just now" : mins === 1 ? "1 min ago" : `${mins} min ago`;
      return (
        <div className="flex items-center gap-2 px-4 pb-3">
          <span className="inline-flex rounded-full h-2 w-2 bg-slate-500" />
          <span className="text-xs text-slate-500">Last run {label}</span>
        </div>
      );
    }

    return (
      <div className="flex items-center gap-2 px-4 pb-3">
        <span className="inline-flex rounded-full h-2 w-2 bg-slate-600" />
        <span className="text-xs text-slate-500">Never run</span>
      </div>
    );
  }

  return (
    <>
      {/* ── Desktop sidebar ─────────────────────────────────────────────── */}
      <aside className="hidden md:flex w-56 flex-shrink-0 bg-slate-900 text-white flex-col">
        <div className="px-6 py-6 border-b border-slate-700">
          <div className="text-xl font-bold tracking-tight">AutoScout AI</div>
          <div className="text-xs text-slate-400 mt-0.5">Vehicle Deal Hunter</div>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1">
          {nav.map(({ href, label, icon }) => {
            const active = path === href;

            // Badge for Deals
            const showDealsBadge = href === "/deals" && stats && stats.great_deals > 0;

            return (
              <Link
                key={href}
                href={href}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  active
                    ? "bg-slate-700 text-white"
                    : "text-slate-400 hover:text-white hover:bg-slate-800"
                }`}
              >
                <span className="text-base">{icon}</span>
                <span className="flex-1">{label}</span>
                {showDealsBadge && (
                  <span className="ml-auto text-[10px] font-bold bg-emerald-500 text-white px-1.5 py-0.5 rounded-full">
                    {stats!.great_deals}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>

        {/* Pipeline status dot */}
        <PipelineDot />

        <div className="px-4 py-4 border-t border-slate-700 space-y-2">
          {user && (
            <div className="text-xs text-slate-400 truncate px-1">{user.email}</div>
          )}
          <button
            onClick={logout}
            className="w-full text-left px-3 py-2 text-xs text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors"
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* ── Mobile bottom tab bar ────────────────────────────────────────── */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-40 bg-slate-900 border-t border-slate-700 flex safe-bottom">
        {nav.map(({ href, label, icon }) => {
          const active = path === href;

          const showDealsBadge = href === "/deals" && stats && stats.great_deals > 0;

          return (
            <Link
              key={href}
              href={href}
              className={`flex-1 flex flex-col items-center justify-center py-3 gap-0.5 text-xs font-medium transition-colors relative ${
                active ? "text-white" : "text-slate-400"
              }`}
            >
              <span className="relative text-xl leading-none">
                {icon}
                {showDealsBadge && (
                  <span className="absolute -top-1 -right-2 text-[9px] font-bold bg-emerald-500 text-white min-w-[14px] h-[14px] flex items-center justify-center rounded-full px-0.5">
                    {stats!.great_deals}
                  </span>
                )}
              </span>
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );
}

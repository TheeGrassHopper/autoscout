"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { type AuthUser, clearAuth, getUser } from "@/lib/auth";

const nav = [
  { href: "/", label: "Dashboard", icon: "⚡" },
  { href: "/deals", label: "Deals", icon: "🔍" },
  { href: "/searches", label: "Searches", icon: "🔖" },
  { href: "/messages", label: "Messages", icon: "💬" },
];

export default function Sidebar() {
  const path = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    setUser(getUser());
  }, []);

  const logout = () => {
    clearAuth();
    router.push("/login");
  };

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
                {label}
              </Link>
            );
          })}
        </nav>

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
          return (
            <Link
              key={href}
              href={href}
              className={`flex-1 flex flex-col items-center justify-center py-3 gap-0.5 text-xs font-medium transition-colors ${
                active ? "text-white" : "text-slate-400"
              }`}
            >
              <span className="text-xl leading-none">{icon}</span>
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );
}

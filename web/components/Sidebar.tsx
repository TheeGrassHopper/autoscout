"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const nav = [
  { href: "/", label: "Dashboard", icon: "⚡" },
  { href: "/deals", label: "Deals", icon: "🔍" },
  { href: "/messages", label: "Messages", icon: "💬" },
];

export default function Sidebar() {
  const path = usePathname();

  return (
    <aside className="w-56 flex-shrink-0 bg-slate-900 text-white flex flex-col">
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

      <div className="px-6 py-4 border-t border-slate-700">
        <div className="text-xs text-slate-500">
          API: localhost:8000
        </div>
      </div>
    </aside>
  );
}

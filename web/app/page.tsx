"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  type Deal,
  type PipelineStatus,
  type Stats,
  getDeals,
  getPipelineStatus,
  getStats,
  runPipeline,
} from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

const SCORE_COLOR: Record<string, string> = {
  great: "bg-emerald-100 text-emerald-800",
  fair: "bg-amber-100 text-amber-800",
  poor: "bg-red-100 text-red-800",
};

const SCORE_ICON: Record<string, string> = {
  great: "🔥",
  fair: "⚡",
  poor: "❌",
};

function fmt(n?: number | null) {
  if (n == null) return "—";
  return `$${n.toLocaleString()}`;
}

function fmtMi(n?: number | null) {
  if (n == null) return "—";
  return `${n.toLocaleString()} mi`;
}

// ── Stat Card ─────────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent: string;
}) {
  return (
    <div className={`bg-white rounded-xl border-l-4 ${accent} shadow-sm p-5`}>
      <div className="text-3xl font-bold text-slate-900">{value}</div>
      <div className="text-sm text-slate-500 mt-1">{label}</div>
    </div>
  );
}

// ── Pipeline Panel ────────────────────────────────────────────────────────────

function PipelinePanel() {
  const [status, setStatus] = useState<PipelineStatus>({
    running: false,
    last_run: null,
    last_count: 0,
  });
  const [query, setQuery] = useState("");
  const [dryRun, setDryRun] = useState(true);
  const [logs, setLogs] = useState<string[]>([]);
  const logsRef = useRef<HTMLDivElement>(null);

  // Poll status
  useEffect(() => {
    const refresh = async () => {
      try {
        const s = await getPipelineStatus();
        setStatus(s);
      } catch {}
    };
    refresh();
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, []);

  // Subscribe to SSE logs when running
  useEffect(() => {
    if (!status.running) return;
    const es = new EventSource("http://localhost:8000/api/pipeline/logs");
    es.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.line) {
        setLogs((prev) => [...prev.slice(-199), data.line]);
      }
    };
    return () => es.close();
  }, [status.running]);

  // Auto-scroll logs
  useEffect(() => {
    logsRef.current?.scrollTo({ top: logsRef.current.scrollHeight, behavior: "smooth" });
  }, [logs]);

  const start = async () => {
    setLogs([]);
    await runPipeline(query, dryRun);
    setStatus((s) => ({ ...s, running: true }));
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Run Pipeline</h2>
          <p className="text-xs text-slate-400 mt-0.5">
            {status.last_run
              ? `Last run: ${new Date(status.last_run).toLocaleString()} — ${status.last_count} listings`
              : "Never run"}
          </p>
        </div>
        <span
          className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${
            status.running
              ? "bg-blue-100 text-blue-700"
              : "bg-slate-100 text-slate-500"
          }`}
        >
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              status.running ? "bg-blue-500 animate-pulse" : "bg-slate-400"
            }`}
          />
          {status.running ? "Running…" : "Idle"}
        </span>
      </div>

      <div className="flex gap-3 mb-4">
        <input
          className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300"
          placeholder='Search query, e.g. "tacoma" (leave blank for all)'
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={status.running}
        />
        <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => setDryRun(e.target.checked)}
            className="rounded"
            disabled={status.running}
          />
          Dry run
        </label>
        <button
          onClick={start}
          disabled={status.running}
          className="px-5 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-700 disabled:opacity-40 transition-colors"
        >
          {status.running ? "Running…" : "▶ Run"}
        </button>
      </div>

      {logs.length > 0 && (
        <div
          ref={logsRef}
          className="bg-slate-950 text-green-400 text-xs font-mono rounded-lg p-4 h-48 overflow-y-auto space-y-0.5"
        >
          {logs.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Top Deals ─────────────────────────────────────────────────────────────────

function TopDeals({ deals }: { deals: Deal[] }) {
  if (!deals.length) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-8 text-center text-slate-400 text-sm">
        No great deals found yet. Run the pipeline to start scanning.
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
        <h2 className="text-base font-semibold text-slate-900">Top Great Deals</h2>
        <Link href="/deals" className="text-xs text-slate-400 hover:text-slate-700 transition-colors">
          View all →
        </Link>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-gray-50 text-left text-xs text-slate-500 uppercase tracking-wide">
            <th className="px-6 py-3 font-medium">Score</th>
            <th className="px-6 py-3 font-medium">Vehicle</th>
            <th className="px-6 py-3 font-medium">Asking</th>
            <th className="px-6 py-3 font-medium">KBB</th>
            <th className="px-6 py-3 font-medium">Savings</th>
            <th className="px-6 py-3 font-medium">Mileage</th>
            <th className="px-6 py-3 font-medium">Source</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {deals.slice(0, 8).map((d) => (
            <tr key={d.listing_id} className="hover:bg-gray-50 transition-colors">
              <td className="px-6 py-3">
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${SCORE_COLOR[d.deal_class]}`}>
                  {SCORE_ICON[d.deal_class]} {d.total_score}
                </span>
              </td>
              <td className="px-6 py-3">
                <a
                  href={d.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-medium text-slate-900 hover:text-blue-600 line-clamp-1 block max-w-xs"
                >
                  {d.title}
                </a>
                <div className="text-xs text-slate-400">{d.location}</div>
              </td>
              <td className="px-6 py-3 font-medium text-slate-900">{fmt(d.asking_price)}</td>
              <td className="px-6 py-3 text-slate-500">{fmt(d.kbb_value)}</td>
              <td className="px-6 py-3">
                {d.savings > 0 ? (
                  <span className="text-emerald-600 font-medium">▼ {fmt(d.savings)}</span>
                ) : (
                  <span className="text-red-500">▲ {fmt(Math.abs(d.savings))}</span>
                )}
              </td>
              <td className="px-6 py-3 text-slate-500">{fmtMi(d.mileage)}</td>
              <td className="px-6 py-3">
                <span className="inline-block px-2 py-0.5 bg-slate-100 text-slate-600 text-xs rounded">
                  {d.source}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [deals, setDeals] = useState<Deal[]>([]);

  useEffect(() => {
    const load = async () => {
      try {
        const [s, d] = await Promise.all([getStats(), getDeals("great")]);
        setStats(s);
        setDeals(d);
      } catch {
        // API not reachable yet
      }
    };
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="p-8 space-y-6 max-w-7xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Dashboard</h1>
        <p className="text-sm text-slate-500 mt-1">Vehicle deal overview</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <StatCard label="Total Scanned" value={stats?.total_listings ?? 0} accent="border-slate-300" />
        <StatCard label="🔥 Great Deals" value={stats?.great_deals ?? 0} accent="border-emerald-500" />
        <StatCard label="⚡ Fair Deals" value={stats?.fair_deals ?? 0} accent="border-amber-400" />
        <StatCard label="❌ Overpriced" value={stats?.poor_deals ?? 0} accent="border-red-400" />
        <StatCard label="💬 Messages Queued" value={stats?.messages_queued ?? 0} accent="border-blue-400" />
      </div>

      {/* Pipeline */}
      <PipelinePanel />

      {/* Top deals */}
      <TopDeals deals={deals} />
    </div>
  );
}

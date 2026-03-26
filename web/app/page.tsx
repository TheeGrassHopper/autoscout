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
  resetDatabase,
  runPipeline,
  stopPipeline,
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

function StatCard({ label, value, accent }: { label: string; value: number; accent: string }) {
  return (
    <div className={`bg-white rounded-xl border-l-4 ${accent} shadow-sm p-4`}>
      <div className="text-2xl md:text-3xl font-bold text-slate-900">{value}</div>
      <div className="text-xs text-slate-500 mt-1">{label}</div>
    </div>
  );
}

// ── Pipeline Panel ────────────────────────────────────────────────────────────

function PipelinePanel() {
  const [status, setStatus] = useState<PipelineStatus>({
    running: false,
    last_run: null,
    last_count: 0,
    start_time: null,
    elapsed_seconds: null,
    stop_requested: false,
  });
  const [query, setQuery] = useState("");
  const [zipCode, setZipCode] = useState("85288");
  const [radius, setRadius] = useState("500");
  const [dryRun, setDryRun] = useState(true);
  const [includeFb, setIncludeFb] = useState(true);
  const [logs, setLogs] = useState<string[]>([]);
  const logsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const refresh = async () => {
      try { const s = await getPipelineStatus(); setStatus(s); } catch {}
    };
    refresh();
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (!status.running) return;
    const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    const apiKey = process.env.NEXT_PUBLIC_API_KEY ?? "";
    const logsUrl = apiKey
      ? `${base}/api/pipeline/logs?api_key=${encodeURIComponent(apiKey)}`
      : `${base}/api/pipeline/logs`;
    const es = new EventSource(logsUrl);
    es.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.line) setLogs((prev) => [...prev.slice(-199), data.line]);
    };
    return () => es.close();
  }, [status.running]);

  useEffect(() => {
    logsRef.current?.scrollTo({ top: logsRef.current.scrollHeight, behavior: "smooth" });
  }, [logs]);

  const start = async () => {
    setLogs([]);
    await runPipeline(query, dryRun, zipCode, parseInt(radius) || 0, includeFb);
    setStatus((s) => ({ ...s, running: true }));
  };

  const clearDb = async () => {
    if (!confirm("Delete all listings and messages from the database? This cannot be undone.")) return;
    await resetDatabase();
    setLogs([`🗑️ Database cleared`]);
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4 md:p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Run Pipeline</h2>
          <p className="text-xs text-slate-400 mt-0.5">
            {status.last_run
              ? `Last run: ${new Date(status.last_run).toLocaleString()} — ${status.last_count} listings`
              : "Never run"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {status.running && status.elapsed_seconds != null && (
            <span className="text-xs text-slate-400 tabular-nums">{status.elapsed_seconds}s</span>
          )}
          <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${
            status.running ? "bg-blue-100 text-blue-700" : "bg-slate-100 text-slate-500"
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${status.running ? "bg-blue-500 animate-pulse" : "bg-slate-400"}`} />
            {status.stop_requested ? "Stopping…" : status.running ? "Running…" : "Idle"}
          </span>
        </div>
      </div>

      <div className="space-y-3 mb-4">
        {/* Search query */}
        <input
          className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-slate-300"
          placeholder='Search query, e.g. "tacoma" (leave blank for all)'
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={status.running}
        />

        {/* ZIP + Radius + controls row */}
        <div className="flex flex-wrap gap-2 items-center">
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-500 whitespace-nowrap">From ZIP</label>
            <input
              className="w-24 text-sm border border-gray-200 rounded-lg px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-slate-300 font-mono"
              placeholder="85288"
              value={zipCode}
              onChange={(e) => setZipCode(e.target.value)}
              disabled={status.running}
              maxLength={5}
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-500 whitespace-nowrap">Radius (mi)</label>
            <input
              className="w-20 text-sm border border-gray-200 rounded-lg px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-slate-300 font-mono"
              placeholder="500"
              value={radius}
              onChange={(e) => setRadius(e.target.value)}
              disabled={status.running}
              type="number"
              min={10}
              max={500}
            />
          </div>

          <div className="flex-1" />

          <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={includeFb}
              onChange={(e) => setIncludeFb(e.target.checked)}
              className="rounded"
              disabled={status.running}
            />
            Facebook
          </label>
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
            onClick={clearDb}
            disabled={status.running}
            className="px-3 py-2.5 bg-red-50 text-red-600 text-sm font-medium rounded-lg hover:bg-red-100 disabled:opacity-40 transition-colors border border-red-200"
            title="Clear database"
          >
            🗑️
          </button>
          {status.running && (
            <button
              onClick={stopPipeline}
              disabled={status.stop_requested}
              className="px-4 py-2.5 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 disabled:opacity-40 transition-colors"
            >
              {status.stop_requested ? "Stopping…" : "⏹ Stop"}
            </button>
          )}
          <button
            onClick={start}
            disabled={status.running}
            className="px-5 py-2.5 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-700 disabled:opacity-40 transition-colors"
          >
            {status.running ? "Running…" : "▶ Run"}
          </button>
        </div>
      </div>

      {logs.length > 0 && (
        <div
          ref={logsRef}
          className="bg-slate-950 text-green-400 text-xs font-mono rounded-lg p-4 h-40 md:h-48 overflow-y-auto space-y-0.5"
        >
          {logs.map((l, i) => <div key={i}>{l}</div>)}
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
        No great deals yet. Run the pipeline to start scanning.
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
      <div className="px-4 md:px-6 py-4 border-b border-gray-100 flex items-center justify-between">
        <h2 className="text-base font-semibold text-slate-900">Top Great Deals</h2>
        <Link href="/deals" className="text-xs text-slate-400 hover:text-slate-700 transition-colors">
          View all →
        </Link>
      </div>

      {/* Mobile cards */}
      <div className="md:hidden divide-y divide-gray-100">
        {deals.slice(0, 6).map((d) => (
          <div key={d.listing_id} className="p-4 space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${SCORE_COLOR[d.deal_class]}`}>
                {SCORE_ICON[d.deal_class]} {d.total_score}
              </span>
              <span className="text-xs text-slate-400">{d.source}</span>
            </div>
            <a href={d.url} target="_blank" rel="noopener noreferrer"
              className="font-semibold text-slate-900 hover:text-blue-600 block leading-snug">
              {d.title}
            </a>
            <div className="flex items-center gap-3 text-sm">
              <span className="font-medium text-slate-900">{fmt(d.asking_price)}</span>
              {d.profit_estimate != null && (
                <span className={`font-bold text-xs ${d.profit_estimate > 0 ? "text-emerald-600" : "text-red-500"}`}>
                  {d.profit_estimate > 0 ? "+" : ""}{fmt(d.profit_estimate)} profit
                </span>
              )}
              <span className="text-slate-400 text-xs">{fmtMi(d.mileage)}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Desktop table */}
      <table className="hidden md:table w-full text-sm">
        <thead>
          <tr className="bg-gray-50 text-left text-xs text-slate-500 uppercase tracking-wide">
            <th className="px-6 py-3 font-medium">Score</th>
            <th className="px-6 py-3 font-medium">Vehicle</th>
            <th className="px-6 py-3 font-medium">Asking</th>
            <th className="px-6 py-3 font-medium">Carvana</th>
            <th className="px-6 py-3 font-medium">Est. Profit</th>
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
                <a href={d.url} target="_blank" rel="noopener noreferrer"
                  className="font-medium text-slate-900 hover:text-blue-600 line-clamp-1 block max-w-xs">
                  {d.title}
                </a>
                <div className="text-xs text-slate-400">{d.location}</div>
              </td>
              <td className="px-6 py-3 font-medium text-slate-900">{fmt(d.asking_price)}</td>
              <td className="px-6 py-3 text-slate-500">{fmt(d.carvana_value)}</td>
              <td className="px-6 py-3">
                {d.profit_estimate == null ? "—" : d.profit_estimate > 0 ? (
                  <span className="text-emerald-600 font-bold">{fmt(d.profit_estimate)}</span>
                ) : (
                  <span className="text-red-500">{fmt(d.profit_estimate)}</span>
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
      } catch {}
    };
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="p-4 md:p-8 space-y-4 md:space-y-6 max-w-7xl mx-auto">
      <div>
        <h1 className="text-xl md:text-2xl font-bold text-slate-900">Dashboard</h1>
        <p className="text-sm text-slate-500 mt-1">Vehicle deal overview</p>
      </div>

      {/* Stats — 2 cols on mobile, 5 on desktop */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 md:gap-4">
        <StatCard label="Total Scanned" value={stats?.total_listings ?? 0} accent="border-slate-300" />
        <StatCard label="🔥 Great Deals" value={stats?.great_deals ?? 0} accent="border-emerald-500" />
        <StatCard label="⚡ Fair Deals" value={stats?.fair_deals ?? 0} accent="border-amber-400" />
        <StatCard label="❌ Overpriced" value={stats?.poor_deals ?? 0} accent="border-red-400" />
        <StatCard label="💬 Queued" value={stats?.messages_queued ?? 0} accent="border-blue-400" />
      </div>

      <PipelinePanel />
      <TopDeals deals={deals} />
    </div>
  );
}

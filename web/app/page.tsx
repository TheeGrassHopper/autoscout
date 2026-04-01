"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  type Deal,
  type PipelineStatus,
  type Stats,
  type RunFilters,
  getDeals,
  getPipelineStatus,
  getStats,
  resetDatabase,
  runPipeline,
  stopPipeline,
} from "@/lib/api";
import { useSession } from "next-auth/react";

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
  href,
}: {
  label: string;
  value: number;
  accent: string;
  href?: string;
}) {
  const inner = (
    <div className={`bg-white rounded-xl border-l-4 ${accent} shadow-sm p-4 h-full transition-shadow hover:shadow-md`}>
      <div className="text-2xl md:text-3xl font-bold text-slate-900">{value}</div>
      <div className="text-xs text-slate-500 mt-1">{label}</div>
    </div>
  );
  if (href) {
    return <Link href={href} className="block h-full">{inner}</Link>;
  }
  return inner;
}

// ── Top Deal Spotlight ────────────────────────────────────────────────────────

function TopDealSpotlight({ deal }: { deal: Deal | null }) {
  if (!deal) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-8 flex flex-col items-center justify-center text-center h-full min-h-[260px]">
        <div className="text-4xl mb-3">🔍</div>
        <div className="text-slate-600 font-medium">No great deals yet</div>
        <div className="text-slate-400 text-sm mt-1">
          Run the pipeline to start scanning for deals.
        </div>
      </div>
    );
  }

  const belowMarketPct =
    deal.blended_market_value != null && deal.asking_price != null
      ? Math.round((1 - deal.asking_price / deal.blended_market_value) * 100)
      : null;

  const imageUrl = deal.image_urls && deal.image_urls.length > 0 ? deal.image_urls[0] : null;

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden flex flex-col h-full">
      <div className="px-4 md:px-6 py-4 border-b border-gray-100 flex items-center justify-between">
        <h2 className="text-base font-semibold text-slate-900">Top Deal Spotlight</h2>
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${SCORE_COLOR[deal.deal_class]}`}>
          {SCORE_ICON[deal.deal_class]} Score {deal.total_score}
        </span>
      </div>

      {imageUrl && (
        <div className="w-full h-44 overflow-hidden bg-slate-100">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imageUrl}
            alt={deal.title}
            className="w-full h-full object-cover"
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
        </div>
      )}

      <div className="px-4 md:px-6 py-4 flex-1 space-y-2">
        <a
          href={deal.url}
          target="_blank"
          rel="noopener noreferrer"
          className="font-semibold text-slate-900 hover:text-blue-600 leading-snug block line-clamp-2"
        >
          {deal.title}
        </a>

        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xl font-bold text-slate-900">{fmt(deal.asking_price)}</span>
          {belowMarketPct != null && belowMarketPct > 0 ? (
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-100 text-emerald-700 border border-emerald-200">
              {belowMarketPct}% below market
            </span>
          ) : deal.profit_estimate != null ? (
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold border ${
              deal.profit_estimate > 0
                ? "bg-emerald-100 text-emerald-700 border-emerald-200"
                : "bg-red-100 text-red-700 border-red-200"
            }`}>
              {deal.profit_estimate > 0 ? "+" : ""}{fmt(deal.profit_estimate)} profit
            </span>
          ) : null}
        </div>

        <div className="flex flex-wrap gap-3 text-xs text-slate-500">
          {deal.year && <span>{deal.year}</span>}
          {deal.mileage != null && <span>{fmtMi(deal.mileage)}</span>}
          {deal.location && <span>{deal.location}</span>}
        </div>
      </div>

      <div className="px-4 md:px-6 pb-4 flex gap-2">
        <Link
          href="/deals"
          className="flex-1 text-center px-4 py-2 text-sm bg-slate-900 text-white font-medium rounded-lg hover:bg-slate-700 transition-colors"
        >
          View Deal →
        </Link>
      </div>
    </div>
  );
}

// ── Log Line ──────────────────────────────────────────────────────────────────

function LogLine({ line }: { line: string }) {
  let color = "text-slate-300";
  if (/ERROR|❌/.test(line))        color = "text-red-400";
  else if (/WARNING/.test(line))     color = "text-amber-400";
  else if (/✅|complete/i.test(line)) color = "text-emerald-400";
  else if (/⛔|stopped/i.test(line))  color = "text-amber-400";
  return <div className={`${color} leading-relaxed whitespace-pre-wrap break-all`}>{line}</div>;
}

// ── Pipeline Panel ────────────────────────────────────────────────────────────

function PipelinePanel() {
  const { data: session } = useSession();
  const user = session?.user ?? null;
  const isAdmin = user?.role === "admin";
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
  const [radius, setRadius] = useState("100");
  const [dryRun, setDryRun] = useState(true);
  const [includeFb, setIncludeFb] = useState(true);
  const [minYear, setMinYear] = useState("2009");
  const [maxYear, setMaxYear] = useState("2025");
  const [maxPrice, setMaxPrice] = useState("40000");
  const [maxMileage, setMaxMileage] = useState("190000");
  const [logs, setLogs] = useState<string[]>([]);
  const [runError, setRunError] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const logsRef = useRef<HTMLDivElement>(null);
  const prevRunning = useRef(false);

  useEffect(() => {
    const refresh = async () => {
      try { const s = await getPipelineStatus(); setStatus(s); } catch {}
    };
    refresh();
    // Poll fast (3s) when running, 10s when idle (matches sidebar)
    const id = setInterval(refresh, status.running ? 3000 : 10000);
    return () => clearInterval(id);
  }, [status.running]);

  useEffect(() => {
    if (!status.running) {
      prevRunning.current = false;
      return;
    }
    // If we arrived at the page while already running, show reconnect notice
    if (!prevRunning.current) setReconnecting(true);
    prevRunning.current = true;

    const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    const apiKey = process.env.NEXT_PUBLIC_API_KEY ?? "";
    const userToken = session?.accessToken ?? "";
    const params = new URLSearchParams();
    if (apiKey) params.set("api_key", apiKey);
    if (userToken) params.set("token", userToken);
    const logsUrl = `${base}/api/pipeline/logs?${params}`;
    const es = new EventSource(logsUrl);
    es.onopen = () => setReconnecting(false);
    es.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.line) setLogs((prev) => [...prev.slice(-499), data.line]);
    };
    return () => es.close();
  }, [status.running]);

  useEffect(() => {
    logsRef.current?.scrollTo({ top: logsRef.current.scrollHeight, behavior: "smooth" });
  }, [logs]);

  const start = async () => {
    setLogs([]);
    setRunError(null);
    const filters: RunFilters = {
      minYear:    parseInt(minYear)    || undefined,
      maxYear:    parseInt(maxYear)    || undefined,
      maxPrice:   parseInt(maxPrice)   || undefined,
      maxMileage: parseInt(maxMileage) || undefined,
    };
    try {
      await runPipeline(query, dryRun, zipCode, parseInt(radius) || 0, includeFb, filters);
      setStatus((s) => ({ ...s, running: true }));
    } catch (err: unknown) {
      setRunError(err instanceof Error ? err.message : "Failed to start pipeline");
    }
  };

  const clearDb = async () => {
    if (!confirm("Delete all listings and messages from the database? This cannot be undone.")) return;
    await resetDatabase();
    setLogs([`Database cleared`]);
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4 md:p-6 flex flex-col h-full">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Pipeline Control</h2>
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

      <div className="space-y-3 mb-4 flex-1">
        {/* Search query */}
        <input
          className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-slate-300"
          placeholder='Search query, e.g. "tacoma" (leave blank for all)'
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={status.running}
        />

        {/* ZIP + Radius row */}
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
              placeholder="100"
              value={radius}
              onChange={(e) => setRadius(e.target.value)}
              disabled={status.running}
              type="number"
              min={10}
              max={500}
            />
          </div>
        </div>

        {/* Filters row */}
        <div className="flex flex-wrap gap-2 items-center">
          <div className="flex items-center gap-1.5">
            <label className="text-xs text-slate-500 whitespace-nowrap">Year</label>
            <input
              type="number" className="w-20 text-sm border border-gray-200 rounded-lg px-2 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300 font-mono"
              value={minYear} onChange={(e) => setMinYear(e.target.value)}
              disabled={status.running} min={1990} max={2030} placeholder="2009"
            />
            <span className="text-xs text-slate-400">–</span>
            <input
              type="number" className="w-20 text-sm border border-gray-200 rounded-lg px-2 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300 font-mono"
              value={maxYear} onChange={(e) => setMaxYear(e.target.value)}
              disabled={status.running} min={1990} max={2030} placeholder="2025"
            />
          </div>
          <div className="flex items-center gap-1.5">
            <label className="text-xs text-slate-500 whitespace-nowrap">Max $</label>
            <input
              type="number" className="w-24 text-sm border border-gray-200 rounded-lg px-2 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300 font-mono"
              value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)}
              disabled={status.running} min={0} step={1000} placeholder="40000"
            />
          </div>
          <div className="flex items-center gap-1.5">
            <label className="text-xs text-slate-500 whitespace-nowrap">Max mi</label>
            <input
              type="number" className="w-24 text-sm border border-gray-200 rounded-lg px-2 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300 font-mono"
              value={maxMileage} onChange={(e) => setMaxMileage(e.target.value)}
              disabled={status.running} min={0} step={10000} placeholder="190000"
            />
          </div>
        </div>

        {/* Checkboxes + action buttons row */}
        <div className="flex flex-wrap gap-2 items-center">
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
          {isAdmin && (
            <button
              onClick={clearDb}
              disabled={status.running}
              className="px-3 py-2.5 bg-red-50 text-red-600 text-sm font-medium rounded-lg hover:bg-red-100 disabled:opacity-40 transition-colors border border-red-200"
              title="Clear database (admin only)"
            >
              🗑️
            </button>
          )}
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

      {runError && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-3 py-2">
          {runError}
        </div>
      )}

      {(status.running || logs.length > 0) && (
        <div className="mt-4 flex flex-col gap-0">
          {/* Terminal header bar */}
          <div className="flex items-center justify-between bg-slate-800 rounded-t-lg px-3 py-1.5">
            <div className="flex items-center gap-2">
              <div className="flex gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-red-500/60" />
                <span className="w-2.5 h-2.5 rounded-full bg-amber-500/60" />
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/60" />
              </div>
              <span className="text-[10px] text-slate-400 font-mono ml-1">pipeline.log</span>
            </div>
            <div className="flex items-center gap-2">
              {reconnecting && (
                <span className="text-[10px] text-amber-400 font-mono">reconnecting…</span>
              )}
              {status.running && !reconnecting && (
                <span className="flex items-center gap-1 text-[10px] font-semibold text-emerald-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  LIVE
                </span>
              )}
              {!status.running && logs.length > 0 && (
                <span className="text-[10px] text-slate-500 font-mono">{logs.length} lines</span>
              )}
            </div>
          </div>
          {/* Log body */}
          <div
            ref={logsRef}
            className={`bg-slate-950 text-xs font-mono rounded-b-lg px-4 py-3 overflow-y-auto space-y-0.5 transition-all duration-300 ${
              status.running ? "h-64 md:h-80" : "h-48"
            }`}
          >
            {logs.length === 0 ? (
              <div className="text-slate-500 animate-pulse">Waiting for output…</div>
            ) : (
              logs.map((l, i) => <LogLine key={i} line={l} />)
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Top 5 Deals Table ─────────────────────────────────────────────────────────

function TopDealsTable({ deals }: { deals: Deal[] }) {
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
        {deals.slice(0, 5).map((d) => {
          const belowPct =
            d.blended_market_value != null && d.asking_price != null
              ? Math.round((1 - d.asking_price / d.blended_market_value) * 100)
              : null;
          return (
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
                {belowPct != null ? (
                  <span className={`font-bold text-xs ${belowPct > 0 ? "text-emerald-600" : "text-red-500"}`}>
                    {belowPct > 0 ? `${belowPct}% below market` : `${Math.abs(belowPct)}% above market`}
                  </span>
                ) : d.profit_estimate != null ? (
                  <span className={`font-bold text-xs ${d.profit_estimate > 0 ? "text-emerald-600" : "text-red-500"}`}>
                    {d.profit_estimate > 0 ? "+" : ""}{fmt(d.profit_estimate)} profit
                  </span>
                ) : null}
                <span className="text-slate-400 text-xs">{fmtMi(d.mileage)}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Desktop table */}
      <table className="hidden md:table w-full text-sm">
        <thead>
          <tr className="bg-gray-50 text-left text-xs text-slate-500 uppercase tracking-wide">
            <th className="px-6 py-3 font-medium">Score</th>
            <th className="px-6 py-3 font-medium">Vehicle</th>
            <th className="px-6 py-3 font-medium">Asking</th>
            <th className="px-6 py-3 font-medium">Below Market</th>
            <th className="px-6 py-3 font-medium">Mileage</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {deals.slice(0, 5).map((d) => {
            const belowPct =
              d.blended_market_value != null && d.asking_price != null
                ? Math.round((1 - d.asking_price / d.blended_market_value) * 100)
                : null;
            return (
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
                <td className="px-6 py-3">
                  {belowPct != null ? (
                    <span className={`font-bold ${belowPct > 0 ? "text-emerald-600" : "text-red-500"}`}>
                      {belowPct > 0 ? `${belowPct}% below` : `${Math.abs(belowPct)}% above`}
                    </span>
                  ) : d.profit_estimate != null ? (
                    <span className={`font-bold ${d.profit_estimate > 0 ? "text-emerald-600" : "text-red-500"}`}>
                      {d.profit_estimate > 0 ? "+" : ""}{fmt(d.profit_estimate)}
                    </span>
                  ) : (
                    <span className="text-slate-400">—</span>
                  )}
                </td>
                <td className="px-6 py-3 text-slate-500">{fmtMi(d.mileage)}</td>
              </tr>
            );
          })}
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
    const id = setInterval(load, 60000); // 60s — stats don't change that fast
    return () => clearInterval(id);
  }, []);

  const topDeal = deals.length > 0 ? deals[0] : null;

  return (
    <div className="p-4 md:p-8 space-y-4 md:space-y-6 max-w-7xl mx-auto">
      <div>
        <h1 className="text-xl md:text-2xl font-bold text-slate-900">Command Center</h1>
        <p className="text-sm text-slate-500 mt-1">AutoScout AI — vehicle deal overview</p>
      </div>

      {/* Stat cards — 2 cols on mobile, 4 on desktop */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
        <StatCard
          label="🔥 Great Deals"
          value={stats?.great_deals ?? 0}
          accent="border-emerald-500"
          href="/deals"
        />
        <StatCard
          label="⚡ Fair Deals"
          value={stats?.fair_deals ?? 0}
          accent="border-amber-400"
          href="/deals"
        />
        <StatCard
          label="Total Scanned"
          value={stats?.total_listings ?? 0}
          accent="border-slate-300"
        />
      </div>

      {/* 2-column grid: Spotlight + Pipeline */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-6 items-stretch">
        <TopDealSpotlight deal={topDeal} />
        <PipelinePanel />
      </div>

      {/* Top 5 deals table */}
      <TopDealsTable deals={deals} />
    </div>
  );
}

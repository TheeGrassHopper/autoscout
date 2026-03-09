"use client";

import { useEffect, useState } from "react";
import { type Deal, type DealClass, getDeals } from "@/lib/api";

const FILTERS: { label: string; value: string }[] = [
  { label: "All", value: "" },
  { label: "🔥 Great", value: "great" },
  { label: "⚡ Fair", value: "fair" },
  { label: "❌ Poor", value: "poor" },
];

const CLASS_BADGE: Record<DealClass, string> = {
  great: "bg-emerald-100 text-emerald-800",
  fair: "bg-amber-100 text-amber-800",
  poor: "bg-red-100 text-red-800",
};

const CLASS_ICON: Record<DealClass, string> = {
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

// ── Row Detail Drawer ─────────────────────────────────────────────────────────

function DealDrawer({ deal, onClose }: { deal: Deal; onClose: () => void }) {
  const savings = deal.savings ?? (deal.kbb_value ? deal.kbb_value - deal.asking_price : null);

  return (
    <div className="fixed inset-0 z-50 flex" onClick={onClose}>
      <div className="flex-1 bg-black/30" />
      <div
        className="w-[480px] bg-white h-full overflow-y-auto shadow-2xl p-8 space-y-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <div>
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold mb-2 ${CLASS_BADGE[deal.deal_class]}`}>
              {CLASS_ICON[deal.deal_class]} {deal.total_score}/100
            </span>
            <h2 className="text-lg font-bold text-slate-900 leading-snug">{deal.title}</h2>
            <p className="text-sm text-slate-400 mt-1">{deal.location} · {deal.source}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-xl ml-4">✕</button>
        </div>

        {/* Price comparison */}
        <div className="grid grid-cols-2 gap-3">
          {[
            { label: "Asking Price", value: fmt(deal.asking_price), highlight: true },
            { label: "KBB Value", value: fmt(deal.kbb_value) },
            { label: "Mileage", value: fmtMi(deal.mileage) },
            { label: "Year", value: deal.year?.toString() ?? "—" },
          ].map(({ label, value, highlight }) => (
            <div key={label} className="bg-gray-50 rounded-lg p-4">
              <div className="text-xs text-slate-500 mb-1">{label}</div>
              <div className={`text-xl font-bold ${highlight ? "text-slate-900" : "text-slate-700"}`}>
                {value}
              </div>
            </div>
          ))}
        </div>

        {savings != null && (
          <div className={`rounded-lg p-4 ${savings > 0 ? "bg-emerald-50" : "bg-red-50"}`}>
            <div className="text-xs font-medium mb-1 text-slate-500">vs KBB Market Value</div>
            <div className={`text-2xl font-bold ${savings > 0 ? "text-emerald-700" : "text-red-600"}`}>
              {savings > 0 ? `▼ ${fmt(savings)} below market` : `▲ ${fmt(Math.abs(savings))} above market`}
            </div>
          </div>
        )}

        <a
          href={deal.url}
          target="_blank"
          rel="noopener noreferrer"
          className="block w-full text-center py-3 bg-slate-900 text-white font-medium rounded-lg hover:bg-slate-700 transition-colors"
        >
          View Listing ↗
        </a>

        <div className="text-xs text-slate-400 space-y-1">
          <div>First seen: {deal.first_seen ? new Date(deal.first_seen).toLocaleString() : "—"}</div>
          <div>Last seen: {deal.last_seen ? new Date(deal.last_seen).toLocaleString() : "—"}</div>
          <div>ID: {deal.listing_id}</div>
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DealsPage() {
  const [deals, setDeals] = useState<Deal[]>([]);
  const [filter, setFilter] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Deal | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const data = await getDeals(filter || undefined);
        setDeals(data);
      } catch {}
      setLoading(false);
    };
    load();
  }, [filter]);

  const visible = deals.filter((d) =>
    !search ||
    d.title.toLowerCase().includes(search.toLowerCase()) ||
    d.make?.toLowerCase().includes(search.toLowerCase()) ||
    d.model?.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="p-8 space-y-6 max-w-7xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Deals</h1>
        <p className="text-sm text-slate-500 mt-1">{deals.length} listings found</p>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="flex rounded-lg border border-gray-200 overflow-hidden bg-white">
          {FILTERS.map(({ label, value }) => (
            <button
              key={value}
              onClick={() => setFilter(value)}
              className={`px-4 py-2 text-sm font-medium transition-colors ${
                filter === value
                  ? "bg-slate-900 text-white"
                  : "text-slate-600 hover:bg-gray-50"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <input
          className="text-sm border border-gray-200 rounded-lg px-3 py-2 w-64 focus:outline-none focus:ring-2 focus:ring-slate-300 bg-white"
          placeholder="Search make, model, title…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-slate-400 text-sm">Loading…</div>
        ) : visible.length === 0 ? (
          <div className="p-12 text-center text-slate-400 text-sm">
            No deals found. Run the pipeline from the Dashboard.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-left text-xs text-slate-500 uppercase tracking-wide">
                <th className="px-5 py-3 font-medium">Score</th>
                <th className="px-5 py-3 font-medium">Vehicle</th>
                <th className="px-5 py-3 font-medium">Asking</th>
                <th className="px-5 py-3 font-medium">KBB</th>
                <th className="px-5 py-3 font-medium">Savings</th>
                <th className="px-5 py-3 font-medium">Mileage</th>
                <th className="px-5 py-3 font-medium">Location</th>
                <th className="px-5 py-3 font-medium">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {visible.map((d) => {
                const savings = d.savings ?? (d.kbb_value ? d.kbb_value - d.asking_price : null);
                return (
                  <tr
                    key={d.listing_id}
                    className="hover:bg-gray-50 cursor-pointer transition-colors"
                    onClick={() => setSelected(d)}
                  >
                    <td className="px-5 py-3">
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${CLASS_BADGE[d.deal_class]}`}>
                        {CLASS_ICON[d.deal_class]} {d.total_score}
                      </span>
                    </td>
                    <td className="px-5 py-3 max-w-xs">
                      <div className="font-medium text-slate-900 truncate">{d.title}</div>
                      <div className="text-xs text-slate-400">{d.year} · {d.make} {d.model}</div>
                    </td>
                    <td className="px-5 py-3 font-medium text-slate-900">{fmt(d.asking_price)}</td>
                    <td className="px-5 py-3 text-slate-500">{fmt(d.kbb_value)}</td>
                    <td className="px-5 py-3">
                      {savings == null ? "—" : savings > 0 ? (
                        <span className="text-emerald-600 font-medium">▼ {fmt(savings)}</span>
                      ) : (
                        <span className="text-red-500">▲ {fmt(Math.abs(savings))}</span>
                      )}
                    </td>
                    <td className="px-5 py-3 text-slate-500">{fmtMi(d.mileage)}</td>
                    <td className="px-5 py-3 text-slate-500 text-xs">{d.location || "—"}</td>
                    <td className="px-5 py-3">
                      <span className="inline-block px-2 py-0.5 bg-slate-100 text-slate-600 text-xs rounded">
                        {d.source}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {selected && <DealDrawer deal={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import { type Deal, type DealClass, type CarvanaOfferStatus, getDeals, getFavorites, saveFavorite, removeFavorite, startCarvanaOffer, getCarvanaOfferStatus } from "@/lib/api";

const FILTERS: { label: string; value: string }[] = [
  { label: "All", value: "" },
  { label: "🔥 Great", value: "great" },
  { label: "⚡ Fair", value: "fair" },
  { label: "❌ Poor", value: "poor" },
  { label: "⭐ Saved", value: "saved" },
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

const TITLE_BADGE: Record<string, string> = {
  clean:   "bg-emerald-100 text-emerald-800",
  rebuilt: "bg-amber-100 text-amber-800",
  salvage: "bg-red-100 text-red-800",
  lien:    "bg-orange-100 text-orange-800",
  missing: "bg-red-100 text-red-800",
  unknown: "bg-gray-100 text-gray-500",
};

function TitleBadge({ status }: { status?: string | null }) {
  if (!status || status === "unknown") return <span className="text-slate-300 text-xs">—</span>;
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold capitalize ${TITLE_BADGE[status] ?? "bg-gray-100 text-gray-500"}`}>
      {status}
    </span>
  );
}

function timeAgo(dateStr?: string | null): string {
  if (!dateStr) return "—";
  return dateStr;
}

function daysAgo(dateStr?: string | null): string | null {
  if (!dateStr) return null;
  const mdMatch = dateStr.match(/^(\d{1,2})\/(\d{1,2})$/);
  if (mdMatch) {
    const now = new Date();
    const posted = new Date(now.getFullYear(), parseInt(mdMatch[1]) - 1, parseInt(mdMatch[2]));
    if (posted > now) posted.setFullYear(now.getFullYear() - 1);
    const diff = Math.floor((now.getTime() - posted.getTime()) / (1000 * 60 * 60 * 24));
    if (diff === 0) return "today";
    if (diff === 1) return "1 day ago";
    return `${diff} days ago`;
  }
  return null;
}

function carvanaUrl(d: Deal): string {
  const make = (d.make || "").toLowerCase().replace(/\s+/g, "-");
  const model = (d.model || "").toLowerCase().replace(/\s+/g, "-");
  const params = new URLSearchParams();
  if (d.year) { params.set("year-min", String(d.year - 1)); params.set("year-max", String(d.year + 1)); }
  if (d.mileage) params.set("miles-max", String(d.mileage + 20000));
  return `https://www.carvana.com/cars/${make}-${model}?${params}`;
}

function carmaxUrl(d: Deal): string {
  const make = (d.make || "").toLowerCase().replace(/\s+/g, "-");
  const model = (d.model || "").toLowerCase().replace(/\s+/g, "-");
  const params = new URLSearchParams();
  if (d.year) { params.set("year-min", String(d.year - 1)); params.set("year-max", String(d.year + 1)); }
  if (d.mileage) params.set("miles-max", String(d.mileage + 20000));
  return `https://www.carmax.com/cars/${make}/${model}?${params}`;
}

// ── Star Button ───────────────────────────────────────────────────────────────

function StarButton({ listingId, isSaved, onToggle }: {
  listingId: string;
  isSaved: boolean;
  onToggle: (e: React.MouseEvent, id: string) => void;
}) {
  return (
    <button
      onClick={(e) => onToggle(e, listingId)}
      className="text-xl leading-none transition-transform hover:scale-125 active:scale-95"
      title={isSaved ? "Remove from saved" : "Save this listing"}
    >
      {isSaved ? "⭐" : "☆"}
    </button>
  );
}

// ── Deal Drawer (side panel on desktop, bottom sheet on mobile) ───────────────

function CarvanaOfferButton({ deal }: { deal: Deal }) {
  const [job, setJob] = useState<CarvanaOfferStatus>({ status: "not_started", offer: null, error: null, steps: [] });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // Fetch existing job status on mount
    getCarvanaOfferStatus(deal.listing_id).then(setJob);
  }, [deal.listing_id]);

  useEffect(() => {
    if (job.status === "running") {
      pollRef.current = setInterval(async () => {
        const s = await getCarvanaOfferStatus(deal.listing_id);
        setJob(s);
        if (s.status !== "running") clearInterval(pollRef.current!);
      }, 3000);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [job.status, deal.listing_id]);

  const start = async () => {
    setJob({ status: "running", offer: null, error: null, steps: [] });
    await startCarvanaOffer(deal.listing_id);
  };

  if (job.status === "completed" && job.offer) {
    return (
      <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-4 space-y-2">
        <div className="flex items-center gap-2 text-emerald-700 font-semibold">
          <span>✅</span>
          <span>Carvana Cash Offer</span>
        </div>
        <div className="text-3xl font-bold text-emerald-700">{job.offer}</div>
        <div className="text-xs text-emerald-600">Offer retrieved automatically via Carvana's sell flow</div>
        <button onClick={start} className="text-xs text-emerald-600 underline hover:text-emerald-800">Refresh offer</button>
      </div>
    );
  }

  if (job.status === "error") {
    return (
      <div className="rounded-lg bg-red-50 border border-red-200 p-3 space-y-2">
        <div className="text-sm text-red-700 font-medium">Automation error</div>
        <div className="text-xs text-red-500">{job.error}</div>
        <button onClick={start} className="px-3 py-1.5 bg-red-600 text-white text-xs font-semibold rounded hover:bg-red-700">
          Try Again
        </button>
      </div>
    );
  }

  if (job.status === "running") {
    return (
      <div className="rounded-lg bg-blue-50 border border-blue-200 p-4 space-y-2">
        <div className="flex items-center gap-2 text-blue-700 font-semibold text-sm">
          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
          </svg>
          Getting Carvana offer…
        </div>
        {job.steps.length > 0 && (
          <div className="text-xs text-blue-500 font-mono">{job.steps[job.steps.length - 1]}</div>
        )}
      </div>
    );
  }

  return (
    <button
      onClick={start}
      className="w-full flex items-center justify-center gap-2 py-2.5 bg-[#00aed9] text-white text-sm font-semibold rounded-lg hover:opacity-90 active:opacity-80 transition-opacity"
    >
      🤖 Get Carvana Cash Offer (Auto-fill)
    </button>
  );
}

function DealDrawer({ deal, onClose }: { deal: Deal; onClose: () => void }) {
  const savings = deal.savings ?? (deal.kbb_value ? deal.kbb_value - deal.asking_price : null);

  return (
    <div className="fixed inset-0 z-50 flex flex-col md:flex-row" onClick={onClose}>
      {/* Backdrop */}
      <div className="flex-1 bg-black/40" />

      {/* Panel — bottom sheet on mobile, right sidebar on desktop */}
      <div
        className="w-full md:w-[520px] bg-white max-h-[92vh] md:max-h-none md:h-full overflow-y-auto shadow-2xl rounded-t-2xl md:rounded-none p-6 md:p-8 space-y-5"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Drag handle — mobile only */}
        <div className="md:hidden flex justify-center -mt-2 mb-2">
          <div className="w-10 h-1 rounded-full bg-gray-300" />
        </div>

        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0 pr-4">
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold mb-2 ${CLASS_BADGE[deal.deal_class]}`}>
              {CLASS_ICON[deal.deal_class]} {deal.total_score}/100
            </span>
            <h2 className="text-base md:text-lg font-bold text-slate-900 leading-snug">{deal.title}</h2>
            <p className="text-sm text-slate-400 mt-1">{deal.location} · {deal.source}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-xl flex-shrink-0">✕</button>
        </div>

        {/* Price grid */}
        <div className="grid grid-cols-2 gap-2 md:gap-3">
          {[
            { label: "Asking Price", value: fmt(deal.asking_price), highlight: true },
            { label: "Est. Profit", value: deal.profit_estimate != null ? `${fmt(deal.profit_estimate)} (${deal.profit_margin_pct != null ? (deal.profit_margin_pct * 100).toFixed(0) + "%" : "?"})` : "—" },
            { label: "Carvana Retail", value: fmt(deal.carvana_value) },
            { label: "Blended Market", value: fmt(deal.blended_market_value) },
            { label: "Mileage", value: fmtMi(deal.mileage) },
            { label: "Year", value: deal.year?.toString() ?? "—" },
            { label: "Title Status", value: deal.title_status ?? "—" },
          ].map(({ label, value, highlight }) => (
            <div key={label} className="bg-gray-50 rounded-lg p-3 md:p-4">
              <div className="text-xs text-slate-500 mb-1">{label}</div>
              <div className={`text-lg md:text-xl font-bold ${highlight ? "text-slate-900" : "text-slate-700"}`}>
                {value}
              </div>
            </div>
          ))}
        </div>

        {/* vs Market */}
        {savings != null && (
          <div className={`rounded-lg p-4 ${savings > 0 ? "bg-emerald-50" : "bg-red-50"}`}>
            <div className="text-xs font-medium mb-1 text-slate-500">vs Market Value</div>
            <div className={`text-xl md:text-2xl font-bold ${savings > 0 ? "text-emerald-700" : "text-red-600"}`}>
              {savings > 0 ? `▼ ${fmt(savings)} below market` : `▲ ${fmt(Math.abs(savings))} above market`}
            </div>
          </div>
        )}

        {/* Carvana */}
        <div className="rounded-lg border border-gray-100 p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-xs text-slate-500 mb-0.5">Carvana (retail)</div>
              <div className="text-xl font-bold text-slate-800">{fmt(deal.carvana_value)}</div>
            </div>
            <a href={carvanaUrl(deal)} target="_blank" rel="noopener noreferrer"
              className="flex-shrink-0 px-4 py-2 bg-[#00aed9] text-white text-sm font-semibold rounded-lg hover:opacity-90">
              Search ↗
            </a>
          </div>
        </div>

        {/* CarMax */}
        <div className="rounded-lg border border-gray-100 p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-xs text-slate-500 mb-0.5">CarMax</div>
              <div className="text-sm text-slate-400">Browse their inventory</div>
            </div>
            <a href={carmaxUrl(deal)} target="_blank" rel="noopener noreferrer"
              className="flex-shrink-0 px-4 py-2 bg-[#e31837] text-white text-sm font-semibold rounded-lg hover:opacity-90">
              Search ↗
            </a>
          </div>
        </div>

        {/* View listing */}
        <a href={deal.url} target="_blank" rel="noopener noreferrer"
          className="block w-full text-center py-3 bg-slate-900 text-white font-medium rounded-lg hover:bg-slate-700 transition-colors">
          View Listing ↗
        </a>

        {/* VIN block */}
        {deal.vin && (
          <div className="rounded-lg bg-slate-50 border border-slate-200 p-4 space-y-3">
            <div>
              <div className="text-xs text-slate-500 font-medium uppercase tracking-wide mb-1">VIN</div>
              <div className="font-mono text-slate-900 font-bold tracking-widest text-sm break-all">{deal.vin}</div>
            </div>
            {/* Automated Carvana offer */}
            <CarvanaOfferButton deal={deal} />
            {/* Manual links */}
            <div className="flex flex-wrap gap-2">
              <a href={`https://www.carmax.com/car-value/vin/${deal.vin}`} target="_blank" rel="noopener noreferrer"
                className="px-3 py-1.5 bg-[#e31837] text-white text-xs font-semibold rounded hover:opacity-90">
                CarMax Offer ↗
              </a>
              <a href={`https://www.kbb.com/instant-cash-offer/?vin=${deal.vin}`} target="_blank" rel="noopener noreferrer"
                className="px-3 py-1.5 bg-slate-700 text-white text-xs font-semibold rounded hover:opacity-90">
                KBB Value ↗
              </a>
            </div>
          </div>
        )}

        <div className="text-xs text-slate-400 space-y-1">
          <div>Posted: {deal.posted_date ? [deal.posted_date, daysAgo(deal.posted_date)].filter(Boolean).join(" · ") : "—"}</div>
          <div>First seen: {deal.first_seen ? new Date(deal.first_seen).toLocaleString() : "—"}</div>
          <div>Last seen: {deal.last_seen ? new Date(deal.last_seen).toLocaleString() : "—"}</div>
          <div>ID: {deal.listing_id}</div>
        </div>
      </div>
    </div>
  );
}

// ── Mobile Deal Card ──────────────────────────────────────────────────────────

function DealCard({ d, onClick, isSaved, onToggle }: {
  d: Deal;
  onClick: () => void;
  isSaved: boolean;
  onToggle: (e: React.MouseEvent, id: string) => void;
}) {
  return (
    <div onClick={onClick} className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 space-y-2 cursor-pointer active:bg-gray-50">
      <div className="flex items-center justify-between gap-2">
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${CLASS_BADGE[d.deal_class]}`}>
          {CLASS_ICON[d.deal_class]} {d.total_score}
        </span>
        <div className="flex items-center gap-2">
          <TitleBadge status={d.title_status} />
          <span className="text-xs text-slate-400">{d.source}</span>
          <StarButton listingId={d.listing_id} isSaved={isSaved} onToggle={onToggle} />
        </div>
      </div>

      <div className="font-semibold text-slate-900 leading-snug">{d.title}</div>
      <div className="text-xs text-slate-400">{d.year} · {d.make} {d.model} · {fmtMi(d.mileage)}</div>

      <div className="flex items-center gap-3 pt-1">
        <div>
          <div className="text-xs text-slate-400">Asking</div>
          <div className="font-bold text-slate-900">{fmt(d.asking_price)}</div>
        </div>
        {d.carvana_value && (
          <div>
            <div className="text-xs text-slate-400">Carvana</div>
            <div className="font-bold text-[#00aed9]">{fmt(d.carvana_value)}</div>
          </div>
        )}
        {d.profit_estimate != null && (
          <div className="ml-auto text-right">
            <div className="text-xs text-slate-400">Est. Profit</div>
            <div className={`font-bold ${d.profit_estimate > 0 ? "text-emerald-600" : "text-red-500"}`}>
              {fmt(d.profit_estimate)}
              {d.profit_margin_pct != null && (
                <span className="text-xs font-normal ml-1">{(d.profit_margin_pct * 100).toFixed(0)}%</span>
              )}
            </div>
          </div>
        )}
      </div>

      {d.posted_date && (
        <div className="text-xs text-slate-400">
          Posted {[d.posted_date, daysAgo(d.posted_date)].filter(Boolean).join(" · ")}
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

type SortKey = "profit_estimate" | "title" | "asking_price" | "total_score" | "mileage";
type SortDir = "asc" | "desc";

function sortDeals(deals: Deal[], key: SortKey, dir: SortDir): Deal[] {
  return [...deals].sort((a, b) => {
    let av: number | string | null = null;
    let bv: number | string | null = null;
    if (key === "title") { av = a.title ?? ""; bv = b.title ?? ""; }
    else { av = (a as any)[key] ?? null; bv = (b as any)[key] ?? null; }

    if (av === null && bv === null) return 0;
    if (av === null) return 1;
    if (bv === null) return -1;
    if (typeof av === "string") return dir === "asc" ? av.localeCompare(bv as string) : (bv as string).localeCompare(av);
    return dir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
  });
}

function SortHeader({ label, sortKey, current, dir, onClick }: {
  label: string;
  sortKey: SortKey;
  current: SortKey;
  dir: SortDir;
  onClick: (k: SortKey) => void;
}) {
  const active = current === sortKey;
  return (
    <th
      className="px-4 py-3 font-medium cursor-pointer select-none hover:text-slate-800 whitespace-nowrap"
      onClick={() => onClick(sortKey)}
    >
      {label}{" "}
      <span className={active ? "text-slate-700" : "text-slate-300"}>
        {active ? (dir === "asc" ? "▲" : "▼") : "⇅"}
      </span>
    </th>
  );
}

export default function DealsPage() {
  const [deals, setDeals] = useState<Deal[]>([]);
  const [filter, setFilter] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Deal | null>(null);
  const [loading, setLoading] = useState(true);
  const [favoriteIds, setFavoriteIds] = useState<Set<string>>(new Set());
  const [sortKey, setSortKey] = useState<SortKey>("total_score");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  function handleSort(key: SortKey) {
    if (key === sortKey) setSortDir((d) => d === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("desc"); }
  }

  // Load favorite IDs on mount so stars reflect state across all filter tabs
  useEffect(() => {
    getFavorites()
      .then((favs) => setFavoriteIds(new Set(favs.map((f) => f.listing_id))))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const data = filter === "saved" ? await getFavorites() : await getDeals(filter || undefined);
        setDeals(data);
      } catch {}
      setLoading(false);
    };
    load();
  }, [filter]);

  async function toggleFavorite(e: React.MouseEvent, listingId: string) {
    e.stopPropagation();
    const isSaved = favoriteIds.has(listingId);
    // Optimistic update
    setFavoriteIds((prev) => {
      const next = new Set(prev);
      isSaved ? next.delete(listingId) : next.add(listingId);
      return next;
    });
    try {
      if (isSaved) await removeFavorite(listingId);
      else await saveFavorite(listingId);
    } catch {
      // Rollback on error
      setFavoriteIds((prev) => {
        const next = new Set(prev);
        isSaved ? next.add(listingId) : next.delete(listingId);
        return next;
      });
    }
  }

  const visible = sortDeals(
    deals.filter((d) =>
      !search ||
      d.title.toLowerCase().includes(search.toLowerCase()) ||
      d.make?.toLowerCase().includes(search.toLowerCase()) ||
      d.model?.toLowerCase().includes(search.toLowerCase())
    ),
    sortKey,
    sortDir,
  );

  return (
    <div className="p-4 md:p-8 space-y-4 md:space-y-6 max-w-[1400px] mx-auto">
      <div>
        <h1 className="text-xl md:text-2xl font-bold text-slate-900">Deals</h1>
        <p className="text-sm text-slate-500 mt-1">{deals.length} listings found</p>
      </div>

      {/* Controls */}
      <div className="flex flex-col sm:flex-row gap-2 sm:gap-3 items-stretch sm:items-center">
        <div className="flex rounded-lg border border-gray-200 overflow-hidden bg-white">
          {FILTERS.map(({ label, value }) => (
            <button
              key={value}
              onClick={() => setFilter(value)}
              className={`flex-1 sm:flex-none px-3 md:px-4 py-2 text-sm font-medium transition-colors ${
                filter === value ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-gray-50"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <input
          className="text-sm border border-gray-200 rounded-lg px-3 py-2 w-full sm:w-64 focus:outline-none focus:ring-2 focus:ring-slate-300 bg-white"
          placeholder="Search make, model, title…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {loading ? (
        <div className="p-12 text-center text-slate-400 text-sm">Loading…</div>
      ) : visible.length === 0 ? (
        <div className="p-12 text-center text-slate-400 text-sm">
          {filter === "saved"
            ? "No saved listings yet. Tap ☆ on any deal to save it here."
            : "No deals found. Run the pipeline from the Dashboard."}
        </div>
      ) : (
        <>
          {/* Mobile cards */}
          <div className="md:hidden space-y-3">
            {visible.map((d) => (
              <DealCard
                key={d.listing_id}
                d={d}
                onClick={() => setSelected(d)}
                isSaved={favoriteIds.has(d.listing_id)}
                onToggle={toggleFavorite}
              />
            ))}
          </div>

          {/* Desktop table */}
          <div className="hidden md:block bg-white rounded-xl shadow-sm border border-gray-100 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-left text-xs text-slate-500 uppercase tracking-wide">
                  <SortHeader label="Score"      sortKey="total_score"     current={sortKey} dir={sortDir} onClick={handleSort} />
                  <SortHeader label="Vehicle"    sortKey="title"           current={sortKey} dir={sortDir} onClick={handleSort} />
                  <SortHeader label="Asking"     sortKey="asking_price"    current={sortKey} dir={sortDir} onClick={handleSort} />
                  <SortHeader label="Est. Profit" sortKey="profit_estimate" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <th className="px-4 py-3 font-medium">Carvana</th>
                  <th className="px-4 py-3 font-medium">CarMax</th>
                  <th className="px-4 py-3 font-medium">Local Mkt</th>
                  <SortHeader label="Mileage"    sortKey="mileage"         current={sortKey} dir={sortDir} onClick={handleSort} />
                  <th className="px-4 py-3 font-medium">Title</th>
                  <th className="px-4 py-3 font-medium">Posted</th>
                  <th className="px-4 py-3 font-medium">Source</th>
                  <th className="px-4 py-3 w-10"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {visible.map((d) => {
                  const reference = d.blended_market_value ?? d.kbb_value;
                  const savings = d.savings ?? (reference ? reference - d.asking_price : null);
                  return (
                    <tr key={d.listing_id} className="hover:bg-gray-50 cursor-pointer transition-colors" onClick={() => setSelected(d)}>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${CLASS_BADGE[d.deal_class]}`}>
                          {CLASS_ICON[d.deal_class]} {d.total_score}
                        </span>
                      </td>
                      <td className="px-4 py-3 max-w-[220px]">
                        <div className="font-medium text-slate-900 truncate">{d.title}</div>
                        <div className="text-xs text-slate-400">{d.year} · {d.make} {d.model}</div>
                      </td>
                      <td className="px-4 py-3 font-medium text-slate-900">{fmt(d.asking_price)}</td>
                      <td className="px-4 py-3">
                        {d.profit_estimate == null ? (
                          <span className="text-slate-300">—</span>
                        ) : d.profit_estimate > 0 ? (
                          <div>
                            <span className="text-emerald-600 font-bold">{fmt(d.profit_estimate)}</span>
                            {d.profit_margin_pct != null && (
                              <span className="text-emerald-500 text-xs ml-1">{(d.profit_margin_pct * 100).toFixed(0)}%</span>
                            )}
                          </div>
                        ) : (
                          <span className="text-red-500 font-medium">{fmt(d.profit_estimate)}</span>
                        )}
                      </td>
                      <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                        {d.make && d.model ? (
                          <a href={carvanaUrl(d)} target="_blank" rel="noopener noreferrer"
                            className="group inline-flex items-center gap-1.5 text-[#00aed9] font-medium hover:underline">
                            {fmt(d.carvana_value)}
                            <span className="text-xs opacity-60 group-hover:opacity-100">↗</span>
                          </a>
                        ) : <span className="text-slate-400">—</span>}
                      </td>
                      <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                        {d.make && d.model ? (
                          <a href={carmaxUrl(d)} target="_blank" rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-[#e31837]/10 text-[#e31837] text-xs font-semibold hover:bg-[#e31837]/20">
                            Search ↗
                          </a>
                        ) : <span className="text-slate-400">—</span>}
                      </td>
                      <td className="px-4 py-3 text-slate-500">{fmt(d.local_market_value)}</td>
                      <td className="px-4 py-3 text-slate-500">{fmtMi(d.mileage)}</td>
                      <td className="px-4 py-3"><TitleBadge status={d.title_status} /></td>
                      <td className="px-4 py-3 text-slate-500 text-xs whitespace-nowrap">{timeAgo(d.posted_date)}</td>
                      <td className="px-4 py-3">
                        <span className="inline-block px-2 py-0.5 bg-slate-100 text-slate-600 text-xs rounded">{d.source}</span>
                      </td>
                      <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                        <StarButton
                          listingId={d.listing_id}
                          isSaved={favoriteIds.has(d.listing_id)}
                          onToggle={toggleFavorite}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {selected && <DealDrawer deal={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

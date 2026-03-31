"use client";

import { useEffect, useRef, useState } from "react";
import { getUser } from "@/lib/auth";
import {
  type Deal,
  type DealClass,
  type CarvanaOfferStatus,
  type CarscomIntelStatus,
  type CarscomIntel,
  type SavedSearch,
  type SearchCriteria,
  type CarmaxOfferStatus,
  getDeals,
  getSavedSearches,
  getFavorites,
  saveFavorite,
  removeFavorite,
  startCarvanaOffer,
  getCarvanaOfferStatus,
  startCarscomIntel,
  getCarscomIntelStatus,
  startCarmaxOffer,
  getCarmaxOfferStatus,
} from "@/lib/api";

// ── Constants ─────────────────────────────────────────────────────────────────

const FILTERS: { label: string; value: string }[] = [
  { label: "All", value: "" },
  { label: "Great", value: "great" },
  { label: "Fair", value: "fair" },
  { label: "Poor", value: "poor" },
  { label: "Saved", value: "saved" },
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

const CLASS_BORDER: Record<DealClass, string> = {
  great: "border-l-emerald-500",
  fair: "border-l-amber-400",
  poor: "border-l-red-400",
};

const CLASS_RING: Record<DealClass, string> = {
  great: "ring-2 ring-emerald-400",
  fair: "ring-2 ring-amber-400",
  poor: "ring-2 ring-red-400",
};

const DEAL_RATING_STYLE: Record<string, string> = {
  "Great Deal": "bg-emerald-100 text-emerald-800",
  "Good Deal": "bg-green-100 text-green-800",
  "Fair Deal": "bg-amber-100 text-amber-700",
  "High Price": "bg-red-100 text-red-700",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n?: number | null) {
  if (n == null) return "—";
  return `$${n.toLocaleString()}`;
}

function fmtMi(n?: number | null) {
  if (n == null) return "—";
  return `${n.toLocaleString()} mi`;
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
    if (diff === 1) return "1d ago";
    return `${diff}d ago`;
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

// ── Small Components ──────────────────────────────────────────────────────────

const TITLE_BADGE: Record<string, string> = {
  clean: "bg-emerald-100 text-emerald-800",
  rebuilt: "bg-amber-100 text-amber-800",
  salvage: "bg-red-100 text-red-800",
  lien: "bg-orange-100 text-orange-800",
  missing: "bg-red-100 text-red-800",
  unknown: "bg-gray-100 text-gray-500",
};

function TitleBadge({ status }: { status?: string | null }) {
  if (!status || status === "unknown") return null;
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-semibold capitalize ${TITLE_BADGE[status] ?? "bg-gray-100 text-gray-500"}`}>
      {status}
    </span>
  );
}

function StarButton({ listingId, isSaved, onToggle }: {
  listingId: string;
  isSaved: boolean;
  onToggle: (e: React.MouseEvent, id: string) => void;
}) {
  return (
    <button
      onClick={(e) => onToggle(e, listingId)}
      className="text-lg leading-none transition-transform hover:scale-125 active:scale-95"
      title={isSaved ? "Remove from saved" : "Save this listing"}
    >
      {isSaved ? "⭐" : "☆"}
    </button>
  );
}

function StatCell({ label, value, sub, accent, color }: {
  label: string;
  value: string;
  sub?: string;
  accent?: boolean;
  color?: string;
}) {
  return (
    <div className="bg-slate-50 rounded-xl p-2.5">
      <div className="text-xs text-slate-400 mb-0.5">{label}</div>
      <div className={`text-sm font-bold leading-tight ${color ?? (accent ? "text-slate-900" : "text-slate-700")}`}>
        {value}
      </div>
      {sub && <div className="text-xs text-slate-400 mt-0.5">{sub}</div>}
    </div>
  );
}

function BelowMarketBar({ asking, market }: { asking: number; market: number }) {
  const pct = Math.round(((market - asking) / market) * 100);
  const absPct = Math.min(Math.abs(pct), 50);
  const below = pct > 0;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-500">vs Market</span>
        <span className={`text-xs font-bold ${below ? "text-emerald-600" : "text-red-500"}`}>
          {below ? `▼ ${pct}% below` : `▲ ${Math.abs(pct)}% above`}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${below ? "bg-emerald-500" : "bg-red-400"}`}
          style={{ width: `${(absPct / 50) * 100}%` }}
        />
      </div>
    </div>
  );
}

// ── Cars.com Intel Components ─────────────────────────────────────────────────

function FlipScoreBar({ score }: { score: number }) {
  const pct = Math.min(Math.max(score, 0), 100);
  const color = pct >= 80 ? "bg-emerald-500" : pct >= 60 ? "bg-amber-400" : pct >= 40 ? "bg-orange-400" : "bg-red-400";
  const label = pct >= 80 ? "Hot flip" : pct >= 60 ? "Good potential" : pct >= 40 ? "Average" : "Low margin";
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-600">Flip Score</span>
        <span className="text-sm font-bold text-slate-900">
          {score}/100 <span className="text-xs font-normal text-slate-400">{label}</span>
        </span>
      </div>
      <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function CarfaxBadges({ carfax }: { carfax: CarscomIntel["carfax"] }) {
  const badges = [
    { key: "clean_title" as const, label: "Clean Title" },
    { key: "no_accidents" as const, label: "No Accidents" },
    { key: "one_owner" as const, label: "1 Owner" },
    { key: "service_records" as const, label: "Service Records" },
  ];
  return (
    <div className="grid grid-cols-2 gap-1.5">
      {badges.map(({ key, label }) => {
        const ok = carfax[key];
        return (
          <div key={key} className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium ${ok ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-400 line-through"}`}>
            <div className={`w-2 h-2 rounded-full flex-shrink-0 ${ok ? "bg-emerald-500" : "bg-slate-300"}`} />
            {label}
          </div>
        );
      })}
    </div>
  );
}

function CarscomIntelPanel({ intel }: { intel: CarscomIntel }) {
  const { flip_score, flip_breakdown, deal_rating, deal_savings, price_drop, carfax, exterior_color, transmission, drivetrain, mpg_city, mpg_highway, comparables, avg_comp_price, comp_count } = intel;

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-bold text-slate-900">Cars.com Market Intel</span>
        <span className="text-xs text-slate-400">via Cars.com</span>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {deal_rating && (
          <span className={`px-2.5 py-1 rounded-full text-xs font-bold ${DEAL_RATING_STYLE[deal_rating] ?? "bg-gray-100 text-gray-600"}`}>
            {deal_rating}
          </span>
        )}
        {deal_savings != null && (
          <span className={`text-sm font-bold ${deal_savings >= 0 ? "text-emerald-600" : "text-red-500"}`}>
            {deal_savings >= 0 ? `▼ $${deal_savings.toLocaleString()} under market` : `▲ $${Math.abs(deal_savings).toLocaleString()} over market`}
          </span>
        )}
        {price_drop != null && price_drop > 0 && (
          <span className="text-xs px-2 py-0.5 bg-amber-50 text-amber-700 rounded font-medium">
            ⬇ Price dropped ${price_drop.toLocaleString()}
          </span>
        )}
      </div>

      {flip_score != null && <FlipScoreBar score={flip_score} />}

      {flip_breakdown && Object.values(flip_breakdown).some((v) => v != null) && (
        <div className="grid grid-cols-4 gap-1 text-center">
          {[
            { label: "Deal", val: flip_breakdown.deal_rating_score, max: 35 },
            { label: "Price", val: flip_breakdown.price_score, max: 25 },
            { label: "CARFAX", val: flip_breakdown.carfax_score, max: 20 },
            { label: "Resale", val: flip_breakdown.resale_score, max: 20 },
          ].map(({ label, val, max }) => (
            <div key={label} className="bg-slate-50 rounded-lg p-2">
              <div className="text-xs text-slate-400">{label}</div>
              <div className="text-sm font-bold text-slate-800">
                {val ?? "—"}<span className="text-xs font-normal text-slate-400">/{max}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div>
        <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">CARFAX Signals</div>
        <CarfaxBadges carfax={carfax} />
      </div>

      {(exterior_color || transmission || drivetrain || mpg_city) && (
        <div className="flex flex-wrap gap-2 text-xs">
          {exterior_color && <span className="px-2 py-1 bg-slate-100 rounded text-slate-600">{exterior_color}</span>}
          {drivetrain && <span className="px-2 py-1 bg-slate-100 rounded text-slate-600">{drivetrain}</span>}
          {transmission && <span className="px-2 py-1 bg-slate-100 rounded text-slate-600">{transmission}</span>}
          {mpg_city && mpg_highway && <span className="px-2 py-1 bg-slate-100 rounded text-slate-600">{mpg_city}/{mpg_highway} mpg</span>}
        </div>
      )}

      {comparables.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
            {comp_count} Comparable Listings
            {avg_comp_price != null && <span className="font-normal"> (avg ${avg_comp_price.toLocaleString()})</span>}
          </div>
          <div className="space-y-1.5 max-h-[160px] overflow-y-auto pr-1">
            {comparables.map((c, i) => (
              <a key={i} href={c.url ?? "#"} target="_blank" rel="noopener noreferrer"
                className="flex items-center justify-between px-3 py-2 rounded-lg bg-slate-50 hover:bg-slate-100 transition-colors">
                <div className="min-w-0">
                  <div className="text-xs font-medium text-slate-800 truncate">{c.title ?? `${c.year} listing`}</div>
                  <div className="text-xs text-slate-400">{c.mileage != null ? `${c.mileage.toLocaleString()} mi` : ""} {c.trim ?? ""}</div>
                </div>
                <div className="flex-shrink-0 text-right ml-3">
                  <div className="text-sm font-bold text-slate-900">{c.price != null ? `$${c.price.toLocaleString()}` : "—"}</div>
                  {c.deal_rating && (
                    <div className={`text-xs px-1.5 py-0.5 rounded ${DEAL_RATING_STYLE[c.deal_rating] ?? "bg-gray-100 text-gray-500"}`}>
                      {c.deal_rating}
                    </div>
                  )}
                </div>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Spinner ───────────────────────────────────────────────────────────────────

function Spinner({ className = "h-3.5 w-3.5" }: { className?: string }) {
  return (
    <svg className={`animate-spin flex-shrink-0 ${className}`} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
    </svg>
  );
}

// ── Error classification ──────────────────────────────────────────────────────

function classifyError(err: string | null | undefined): { icon: string; label: string; detail: string; hint: string } {
  const e = (err ?? "").toLowerCase();
  if (e.includes("cloudflare") || e.includes("security verification") || e.includes("blocked"))
    return { icon: "🛡️", label: "Cloudflare Blocked", detail: err ?? "", hint: "Carvana's bot protection blocked this request from our server. Try manually below." };
  if (e.includes("timeout") || e.includes("timed out"))
    return { icon: "⏱️", label: "Timed Out", detail: err ?? "", hint: "The page took too long to respond. Carvana may be slow or the flow changed." };
  if (e.includes("changed their flow") || e.includes("no offer"))
    return { icon: "🔄", label: "Flow Changed", detail: err ?? "", hint: "Carvana may have updated their sell page. Try manually below." };
  if (e.includes("no vin") || e.includes("vin"))
    return { icon: "🔑", label: "VIN Issue", detail: err ?? "", hint: "Check the VIN is 17 characters and correct." };
  return { icon: "⚠️", label: "Automation Failed", detail: err ?? "", hint: "An unexpected error occurred. Try manually below or use Cars.com intel below." };
}

// ── CarMax Offer Section ──────────────────────────────────────────────────────

function CarmaxOfferSection({ deal, vin }: { deal: Deal; vin: string }) {
  const [job, setJob] = useState<CarmaxOfferStatus>({ status: "not_started", offer: null, offer_low: null, offer_high: null, error: null, steps: [] });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    getCarmaxOfferStatus(deal.listing_id).then(setJob);
  }, [deal.listing_id]);

  useEffect(() => {
    if (job.status === "running") {
      pollRef.current = setInterval(async () => {
        const s = await getCarmaxOfferStatus(deal.listing_id);
        setJob(s);
        if (s.status !== "running") clearInterval(pollRef.current!);
      }, 3000);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [job.status, deal.listing_id]);

  const start = async () => {
    setJob({ status: "running", offer: null, offer_low: null, offer_high: null, error: null, steps: [] });
    await startCarmaxOffer(deal.listing_id, vin);
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 bg-slate-50">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-[#e31837]" />
          <span className="text-xs font-bold text-slate-800">CarMax Cash Offer</span>
        </div>
        {job.status === "completed" && job.offer && (
          <button onClick={start} className="text-xs text-slate-400 hover:text-slate-600">Refresh</button>
        )}
      </div>

      <div className="p-4 space-y-3">
        {/* Not started */}
        {job.status === "not_started" && (
          <p className="text-xs text-slate-500">Automated sell flow — fills CarMax&apos;s form using your VIN and NHTSA data.</p>
        )}

        {/* Running */}
        {job.status === "running" && (
          <div className="rounded-lg bg-orange-50 border border-orange-100 p-3">
            <div className="flex items-center gap-2 text-orange-700 text-xs font-medium">
              <Spinner className="h-3.5 w-3.5 text-orange-500" />
              Running CarMax automation…
            </div>
            {job.steps.length > 0 && (
              <div className="text-xs text-orange-400 font-mono truncate mt-1">{job.steps[job.steps.length - 1]}</div>
            )}
          </div>
        )}

        {/* Success */}
        {job.status === "completed" && job.offer && (
          <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-3">
            <div className="text-xs text-emerald-600 font-medium mb-1">CarMax Offer Range</div>
            <div className="text-2xl font-bold text-emerald-700">{job.offer}</div>
            {job.offer_low != null && job.offer_high != null && (
              <div className="text-xs text-emerald-500 mt-0.5">
                Low: ${job.offer_low.toLocaleString()} · High: ${job.offer_high.toLocaleString()}
              </div>
            )}
          </div>
        )}

        {/* Error */}
        {job.status === "error" && (
          <div className="rounded-lg bg-red-50 border border-red-200 p-3 space-y-2">
            <div className="flex items-center gap-2 text-xs font-semibold text-red-700">
              <span>⚠️</span> CarMax automation failed
            </div>
            <div className="text-xs text-red-500 leading-snug">{job.error}</div>
            <a href={`https://www.carmax.com/sell-my-car`} target="_blank" rel="noopener noreferrer"
              className="inline-block text-xs font-medium text-[#e31837] underline">
              Try manually on CarMax ↗
            </a>
          </div>
        )}

        {/* Action */}
        {job.status !== "running" && (
          <button
            onClick={start}
            className="w-full py-2 bg-[#e31837] text-white text-xs font-semibold rounded-xl hover:opacity-90 transition-opacity"
          >
            {job.status === "not_started" ? "Get CarMax Offer (Auto-fill)" : "Retry CarMax Offer"}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Carvana Offer Section ─────────────────────────────────────────────────────

function CarvanaOfferSection({ deal }: { deal: Deal }) {
  const [manualVin, setManualVin] = useState(deal.vin ?? "");
  const [job, setJob] = useState<CarvanaOfferStatus>({ status: "not_started", offer: null, error: null, steps: [] });
  const [intel, setIntel] = useState<CarscomIntelStatus | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const intelPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    getCarvanaOfferStatus(deal.listing_id).then(setJob);
    getCarscomIntelStatus(deal.listing_id).then(setIntel);
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

  useEffect(() => {
    if (intel?.status === "running") {
      intelPollRef.current = setInterval(async () => {
        const s = await getCarscomIntelStatus(deal.listing_id);
        setIntel(s);
        if (s.status !== "running") clearInterval(intelPollRef.current!);
      }, 4000);
    }
    return () => { if (intelPollRef.current) clearInterval(intelPollRef.current); };
  }, [intel?.status, deal.listing_id]);

  // Auto-kick Cars.com intel when Carvana fails and VIN is available
  useEffect(() => {
    if (job.status === "error" && manualVin.length === 17 && intel?.status !== "running" && intel?.status !== "completed") {
      setIntel({ status: "running", data: null });
      startCarscomIntel(deal.listing_id);
    }
  }, [job.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = async () => {
    if (!manualVin.trim()) return;
    setJob({ status: "running", offer: null, error: null, steps: [] });
    await startCarvanaOffer(deal.listing_id, manualVin.trim());
    if (manualVin.trim().length === 17) {
      setIntel({ status: "running", data: null });
      await startCarscomIntel(deal.listing_id);
    }
  };

  const vinIsValid = manualVin.trim().length === 17;
  const errInfo = job.status === "error" ? classifyError(job.error) : null;

  return (
    <div className="space-y-3">
      {/* VIN + Carvana block */}
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 bg-slate-50">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-[#00aed9]" />
            <span className="text-xs font-bold text-slate-800">Carvana Cash Offer</span>
          </div>
          {job.status === "completed" && job.offer && (
            <button onClick={start} className="text-xs text-slate-400 hover:text-slate-600">Refresh</button>
          )}
        </div>

        <div className="p-4 space-y-3">
          {/* VIN field */}
          <div>
            <div className="text-xs text-slate-500 font-medium uppercase tracking-wide mb-1.5">VIN</div>
            {deal.vin ? (
              <div className="font-mono text-slate-900 font-bold tracking-widest text-xs break-all bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
                {deal.vin}
              </div>
            ) : (
              <input
                className="w-full font-mono text-xs border border-slate-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#00aed9] placeholder-slate-300 bg-white"
                placeholder="Paste 17-digit VIN"
                value={manualVin}
                onChange={(e) => setManualVin(e.target.value.toUpperCase())}
                maxLength={17}
                disabled={job.status === "running"}
              />
            )}
          </div>

          {/* Running */}
          {job.status === "running" && (
            <div className="rounded-lg bg-blue-50 border border-blue-100 p-3">
              <div className="flex items-center gap-2 text-blue-700 text-xs font-medium">
                <Spinner className="h-3.5 w-3.5 text-blue-500" />
                Running Carvana automation…
              </div>
              {job.steps.length > 0 && (
                <div className="text-xs text-blue-400 font-mono truncate mt-1">{job.steps[job.steps.length - 1]}</div>
              )}
            </div>
          )}

          {/* Success */}
          {job.status === "completed" && job.offer && (
            <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-3">
              <div className="text-xs text-emerald-600 font-medium mb-1">Carvana Cash Offer</div>
              <div className="text-2xl font-bold text-emerald-700">{job.offer}</div>
            </div>
          )}

          {/* Error — rich failure card */}
          {job.status === "error" && errInfo && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-base">{errInfo.icon}</span>
                <span className="text-xs font-bold text-red-700">{errInfo.label}</span>
              </div>
              <p className="text-xs text-red-600 leading-snug">{errInfo.hint}</p>
              <details className="group">
                <summary className="text-xs text-red-400 cursor-pointer hover:text-red-600 list-none flex items-center gap-1">
                  <span className="group-open:hidden">▶ Show error detail</span>
                  <span className="hidden group-open:inline">▼ Hide</span>
                </summary>
                <div className="mt-1 text-xs font-mono text-red-400 break-all leading-snug">{errInfo.detail}</div>
              </details>
              <div className="flex gap-2 pt-1">
                <a
                  href={`https://www.carvana.com/sell-my-car${manualVin ? `?vin=${manualVin}` : ""}`}
                  target="_blank" rel="noopener noreferrer"
                  className="flex-1 text-center py-1.5 text-xs font-semibold bg-[#00aed9] text-white rounded-lg hover:opacity-90"
                >
                  Try manually on Carvana ↗
                </a>
                <button onClick={start} disabled={!vinIsValid}
                  className="flex-1 py-1.5 text-xs font-semibold bg-slate-200 text-slate-700 rounded-lg hover:bg-slate-300 disabled:opacity-40">
                  Retry
                </button>
              </div>
              {intel?.status !== "running" && intel?.status !== "completed" && (
                <p className="text-xs text-slate-500 pt-0.5">Cars.com market intel is loading below as a fallback…</p>
              )}
            </div>
          )}

          {/* Primary CTA */}
          {job.status !== "running" && job.status !== "error" && (
            <button
              onClick={start}
              disabled={!vinIsValid}
              className="w-full py-2.5 bg-[#00aed9] text-white text-xs font-semibold rounded-xl hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {job.status === "not_started" ? "Get Carvana Cash Offer (Auto-fill)" : "Refresh Offer"}
            </button>
          )}

          {/* KBB link */}
          {vinIsValid && (
            <a href={`https://www.kbb.com/instant-cash-offer/?vin=${manualVin}`} target="_blank" rel="noopener noreferrer"
              className="block w-full text-center py-2 text-xs font-semibold bg-slate-100 text-slate-600 rounded-xl hover:bg-slate-200 transition-colors">
              KBB Instant Cash Offer ↗
            </a>
          )}
        </div>
      </div>

      {/* CarMax automated offer */}
      {vinIsValid && <CarmaxOfferSection deal={deal} vin={manualVin} />}

      {/* Cars.com Intel */}
      {intel?.status === "running" && (
        <div className="rounded-xl border border-slate-200 bg-white p-4 flex items-center gap-3 text-sm text-slate-500">
          <Spinner className="h-4 w-4 text-blue-500" />
          Fetching Cars.com market intel…
          {job.status === "error" && <span className="text-xs text-slate-400">(fallback from Carvana failure)</span>}
        </div>
      )}
      {intel?.status === "completed" && intel.data && <CarscomIntelPanel intel={intel.data} />}
      {intel?.status === "error" && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-600">
          Cars.com lookup failed — {intel.error ?? "unknown error"}
        </div>
      )}
    </div>
  );
}

// ── Detail Panel Tabs ─────────────────────────────────────────────────────────

type DetailTab = "overview" | "valuation" | "offer";

function OverviewTab({ deal }: { deal: Deal }) {
  const reference = deal.blended_market_value ?? deal.kbb_value;
  const savings = deal.savings ?? (reference ? reference - deal.asking_price : null);
  const [lightbox, setLightbox] = useState<number | null>(null);
  const [failedImgs, setFailedImgs] = useState<Set<number>>(new Set());

  const validImgs = (deal.image_urls ?? []).filter((_, i) => !failedImgs.has(i));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (lightbox === null) return;
      if (e.key === "ArrowLeft" && lightbox > 0) setLightbox(lightbox - 1);
      if (e.key === "ArrowRight" && lightbox < validImgs.length - 1) setLightbox(lightbox + 1);
      if (e.key === "Escape") setLightbox(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lightbox, validImgs.length]);

  return (
    <div className="flex flex-col h-full p-4 gap-3">
      {/* Top: image + stat grid */}
      <div className="flex gap-3" style={{ height: 176 }}>
        {/* Hero image */}
        {validImgs[0] ? (
          <div
            className="w-44 flex-shrink-0 rounded-xl overflow-hidden cursor-pointer relative group"
            onClick={() => setLightbox(0)}
          >
            <img
              src={validImgs[0]}
              alt=""
              referrerPolicy="no-referrer"
              onError={() => setFailedImgs((s) => { const n = new Set(s); n.add(0); return n; })}
              className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
            />
            {validImgs.length > 1 && (
              <div className="absolute bottom-2 right-2 bg-black/60 text-white text-xs px-1.5 py-0.5 rounded-md font-medium">
                +{validImgs.length - 1}
              </div>
            )}
          </div>
        ) : (
          <div className="w-44 flex-shrink-0 rounded-xl bg-slate-100 flex items-center justify-center">
            <span className="text-slate-300 text-3xl">🚗</span>
          </div>
        )}

        {/* Stats grid */}
        <div className="flex-1 grid grid-cols-2 gap-2 content-start">
          <StatCell label="Asking Price" value={fmt(deal.asking_price)} accent />
          <StatCell label="Market Value" value={fmt(reference)} />
          <StatCell label="Carvana Retail" value={fmt(deal.carvana_value)} color="text-[#00aed9]" />
          <StatCell
            label="Est. Profit"
            value={deal.profit_estimate != null ? fmt(deal.profit_estimate) : "—"}
            sub={deal.profit_margin_pct != null ? `${(deal.profit_margin_pct * 100).toFixed(0)}% margin` : undefined}
            color={deal.profit_estimate != null && deal.profit_estimate > 0 ? "text-emerald-700" : undefined}
          />
          <StatCell label="Mileage" value={fmtMi(deal.mileage)} />
          <StatCell label="Year · Make" value={`${deal.year ?? "—"} ${deal.make ?? ""}`} />
        </div>
      </div>

      {/* Below-market bar */}
      {reference != null && (
        <BelowMarketBar asking={deal.asking_price} market={reference} />
      )}

      {/* Savings pill */}
      {savings != null && (
        <div className={`rounded-xl px-4 py-2.5 flex items-center justify-between ${savings > 0 ? "bg-emerald-50 border border-emerald-100" : "bg-red-50 border border-red-100"}`}>
          <span className="text-xs text-slate-500">vs Blended Market</span>
          <span className={`text-sm font-bold ${savings > 0 ? "text-emerald-700" : "text-red-600"}`}>
            {savings > 0 ? `▼ ${fmt(savings)} below` : `▲ ${fmt(Math.abs(savings))} above`}
          </span>
        </div>
      )}

      {/* Photo filmstrip */}
      {validImgs.length > 1 && (
        <div className="flex gap-2 overflow-x-auto pb-0.5">
          {validImgs.slice(1, 7).map((url, i) => (
            <img
              key={i + 1}
              src={url}
              alt=""
              referrerPolicy="no-referrer"
              onClick={() => setLightbox(i + 1)}
              onError={() => setFailedImgs((s) => { const n = new Set(s); n.add(i + 1); return n; })}
              className="h-12 w-16 object-cover rounded-lg flex-shrink-0 cursor-pointer border border-slate-100 hover:opacity-80 transition-opacity"
            />
          ))}
          {validImgs.length > 7 && (
            <div className="h-12 w-16 flex-shrink-0 rounded-lg bg-slate-100 flex items-center justify-center text-xs text-slate-400 font-medium">
              +{validImgs.length - 7}
            </div>
          )}
        </div>
      )}

      {/* Seller phone */}
      {deal.seller_phone && (
        <a
          href={`tel:${deal.seller_phone}`}
          className="flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs font-semibold hover:bg-emerald-100 transition-colors"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
          </svg>
          {`(${deal.seller_phone.slice(0, 3)}) ${deal.seller_phone.slice(3, 6)}-${deal.seller_phone.slice(6)}`}
        </a>
      )}

      {/* Action buttons */}
      <div className="flex gap-2 mt-auto pt-1">
        <a href={deal.url} target="_blank" rel="noopener noreferrer"
          className="flex-1 text-center py-2.5 text-xs font-semibold bg-slate-900 text-white rounded-xl hover:bg-slate-700 transition-colors">
          View Listing ↗
        </a>
        <a href={carvanaUrl(deal)} target="_blank" rel="noopener noreferrer"
          className="flex-1 text-center py-2.5 text-xs font-semibold bg-[#00aed9] text-white rounded-xl hover:opacity-90 transition-opacity">
          Carvana ↗
        </a>
        <a href={carmaxUrl(deal)} target="_blank" rel="noopener noreferrer"
          className="flex-1 text-center py-2.5 text-xs font-semibold bg-[#e31837] text-white rounded-xl hover:opacity-90 transition-opacity">
          CarMax ↗
        </a>
      </div>

      {/* Lightbox */}
      {lightbox !== null && (
        <div
          className="fixed inset-0 z-[200] bg-black/95 flex items-center justify-center"
          onClick={() => setLightbox(null)}
        >
          <button className="absolute top-4 right-4 text-white text-2xl hover:opacity-70 z-10" onClick={() => setLightbox(null)}>✕</button>
          <div className="absolute top-4 left-1/2 -translate-x-1/2 text-white text-sm bg-black/40 px-3 py-1 rounded-full">
            {lightbox + 1} / {validImgs.length}
          </div>
          {lightbox > 0 && (
            <button className="absolute left-3 md:left-6 text-white text-4xl hover:opacity-70 px-3 py-6 z-10"
              onClick={(e) => { e.stopPropagation(); setLightbox(lightbox - 1); }}>‹</button>
          )}
          <img src={validImgs[lightbox]} alt="" referrerPolicy="no-referrer"
            className="max-h-[85vh] max-w-[90vw] object-contain rounded"
            onClick={(e) => e.stopPropagation()} />
          {lightbox < validImgs.length - 1 && (
            <button className="absolute right-3 md:right-6 text-white text-4xl hover:opacity-70 px-3 py-6 z-10"
              onClick={(e) => { e.stopPropagation(); setLightbox(lightbox + 1); }}>›</button>
          )}
        </div>
      )}
    </div>
  );
}

function ValuationTab({ deal }: { deal: Deal }) {
  const reference = deal.blended_market_value ?? deal.kbb_value;
  const savings = deal.savings ?? (reference ? reference - deal.asking_price : null);

  const valuations = [
    { label: "Asking Price", value: deal.asking_price, color: "bg-slate-500" },
    { label: "KBB Value", value: deal.kbb_value, color: "bg-blue-500" },
    { label: "Carvana Retail", value: deal.carvana_value, color: "bg-[#00aed9]" },
    { label: "CarMax", value: deal.carmax_value, color: "bg-[#e31837]" },
    { label: "Blended Market", value: deal.blended_market_value, color: "bg-indigo-500" },
    { label: "Local Market", value: deal.local_market_value, color: "bg-purple-500" },
  ].filter((v) => v.value != null) as { label: string; value: number; color: string }[];

  const maxVal = Math.max(...valuations.map((v) => v.value)) * 1.08;

  return (
    <div className="p-4 space-y-4">
      {/* Comparison bars */}
      <div>
        <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Price Comparison</div>
        <div className="space-y-3">
          {valuations.map(({ label, value, color }) => (
            <div key={label}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-slate-600">{label}</span>
                <span className="text-xs font-bold text-slate-900">{fmt(value)}</span>
              </div>
              <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
                <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${(value / maxVal) * 100}%` }} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Savings summary */}
      {savings != null && (
        <div className={`rounded-xl p-4 ${savings > 0 ? "bg-emerald-50 border border-emerald-100" : "bg-red-50 border border-red-100"}`}>
          <div className="text-xs font-medium text-slate-500 mb-1">vs Blended Market</div>
          <div className={`text-xl font-bold ${savings > 0 ? "text-emerald-700" : "text-red-600"}`}>
            {savings > 0 ? `▼ ${fmt(savings)} below market` : `▲ ${fmt(Math.abs(savings))} above market`}
          </div>
          {deal.profit_estimate != null && (
            <div className="text-sm text-slate-500 mt-1">
              Est. profit: <span className="font-semibold text-slate-700">{fmt(deal.profit_estimate)}</span>
              {deal.profit_margin_pct != null && <span> ({(deal.profit_margin_pct * 100).toFixed(0)}% margin)</span>}
            </div>
          )}
        </div>
      )}

      {/* Local market comp sources */}
      {deal.local_market_comp_urls && deal.local_market_comp_urls.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
            Local Market Comps ({deal.local_market_comp_urls.length})
          </div>
          <div className="space-y-1">
            {deal.local_market_comp_urls.map((url, i) => (
              <a
                key={i}
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-800 hover:underline truncate"
              >
                <svg className="w-3 h-3 flex-shrink-0 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
                <span className="truncate">{url.replace(/^https?:\/\//, "")}</span>
              </a>
            ))}
          </div>
        </div>
      )}

      {/* Meta grid */}
      <div className="grid grid-cols-3 gap-2 text-xs">
        {[
          { label: "Title Status", value: deal.title_status ?? "—" },
          { label: "Demand Score", value: deal.demand_score != null ? `${deal.demand_score}/100` : "—" },
          { label: "Deal Score", value: `${deal.total_score}/100` },
        ].map(({ label, value }) => (
          <div key={label} className="bg-slate-50 rounded-lg p-2.5">
            <div className="text-slate-400 mb-0.5">{label}</div>
            <div className="font-semibold text-slate-700 capitalize">{value}</div>
          </div>
        ))}
      </div>

      {/* Timestamps */}
      <div className="text-xs text-slate-400 space-y-0.5 pt-1">
        <div>Posted: {deal.posted_date ? [deal.posted_date, daysAgo(deal.posted_date)].filter(Boolean).join(" · ") : "—"}</div>
        <div>First seen: {deal.first_seen ? new Date(deal.first_seen).toLocaleString() : "—"}</div>
        <div>ID: <span className="font-mono">{deal.listing_id}</span></div>
      </div>
    </div>
  );
}

// ── Deal Panel (replaces DealDrawer) ─────────────────────────────────────────

function DealPanel({ deal, onClose, embedded }: { deal: Deal; onClose: () => void; embedded?: boolean }) {
  const [tab, setTab] = useState<DetailTab>("overview");

  const TABS: { key: DetailTab; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "valuation", label: "Valuation" },
    { key: "offer", label: "Get Offer" },
  ];

  const inner = (
    <div className="flex flex-col h-full bg-white">
      {/* Mobile back button */}
      {!embedded && (
        <div className="lg:hidden flex items-center gap-2 px-4 py-2.5 border-b border-slate-100 bg-slate-50 flex-shrink-0">
          <button
            onClick={onClose}
            className="flex items-center gap-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
            Back to Deals
          </button>
        </div>
      )}

      {/* Header */}
      <div className="px-4 pt-3.5 pb-3 border-b border-slate-100 flex-shrink-0 space-y-2.5">
        <div className="flex items-start gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold ${CLASS_BADGE[deal.deal_class]}`}>
                {CLASS_ICON[deal.deal_class]} {deal.total_score}/100
              </span>
              <TitleBadge status={deal.title_status} />
              <span className="text-xs px-1.5 py-0.5 bg-slate-100 text-slate-500 rounded">{deal.source}</span>
            </div>
            <h2 className="font-bold text-slate-900 text-sm leading-snug line-clamp-2">{deal.title}</h2>
            <p className="text-xs text-slate-400 mt-0.5">
              {[deal.location, daysAgo(deal.posted_date)].filter(Boolean).join(" · ")}
            </p>
          </div>
          <button
            onClick={onClose}
            className="flex-shrink-0 p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Tab bar */}
        <div className="flex gap-1 bg-slate-100 p-1 rounded-xl">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`flex-1 py-1.5 text-xs font-semibold rounded-lg transition-all duration-150 ${
                tab === key
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content — fills remaining height */}
      <div className="flex-1 min-h-0 relative overflow-hidden">
        {/* Overview: fixed layout, no scroll */}
        <div className={`absolute inset-0 flex flex-col ${tab === "overview" ? "" : "hidden"}`}>
          <OverviewTab deal={deal} />
        </div>
        {/* Valuation: allows scroll for content */}
        <div className={`absolute inset-0 overflow-y-auto ${tab === "valuation" ? "" : "hidden"}`}>
          <ValuationTab deal={deal} />
        </div>
        {/* Get Offer: allows scroll for offer + intel */}
        <div className={`absolute inset-0 overflow-y-auto ${tab === "offer" ? "" : "hidden"}`}>
          <div className="p-4">
            <CarvanaOfferSection deal={deal} />
          </div>
        </div>
      </div>
    </div>
  );

  if (embedded) return inner;

  // Mobile overlay (bottom sheet)
  return (
    <div className="fixed inset-0 z-50 flex flex-col lg:hidden">
      <div className="flex-shrink-0 bg-black/40" onClick={onClose} style={{ height: "5vh" }} />
      <div className="flex-1 bg-white rounded-t-2xl shadow-2xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
        {inner}
      </div>
    </div>
  );
}

// ── Signal Card ───────────────────────────────────────────────────────────────

function SignalCard({ d, onClick, isSaved, onToggle, isSelected, sortKey }: {
  d: Deal;
  onClick: () => void;
  isSaved: boolean;
  onToggle: (e: React.MouseEvent, id: string) => void;
  isSelected: boolean;
  sortKey: SortKey;
}) {
  const reference = d.blended_market_value ?? d.kbb_value;
  const savings = d.savings ?? (reference ? reference - d.asking_price : null);
  const posted = daysAgo(d.posted_date);
  // When sorted by newest, show scraped time prominently; otherwise show posted age
  const scrapedLabel = d.first_seen
    ? `scraped ${daysAgo(d.first_seen) ?? new Date(d.first_seen).toLocaleDateString()}`
    : null;
  const timeLabel = sortKey === "first_seen" ? scrapedLabel : posted;
  const thumb = d.image_urls?.[0];

  return (
    <div
      onClick={onClick}
      className={`bg-white rounded-xl border border-l-4 ${CLASS_BORDER[d.deal_class]} cursor-pointer transition-all duration-150
        ${isSelected
          ? `border-slate-200 ${CLASS_RING[d.deal_class]} shadow-md`
          : "border-gray-100 hover:shadow-md hover:border-slate-200"
        }`}
    >
      <div className="flex gap-0">
        {thumb && (
          <div className="flex-shrink-0 w-24">
            <img
              src={thumb}
              alt=""
              referrerPolicy="no-referrer"
              className="w-full h-full object-cover rounded-l-[10px] min-h-[80px] max-h-[110px]"
            />
          </div>
        )}
        <div className="flex-1 min-w-0 p-3 space-y-2">
          {/* Row 1 */}
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-xs font-bold ${CLASS_BADGE[d.deal_class]}`}>
              {CLASS_ICON[d.deal_class]} {d.total_score}
            </span>
            {d.title_status && d.title_status !== "clean" && d.title_status !== "unknown" && (
              <TitleBadge status={d.title_status} />
            )}
            <span className="text-xs px-1.5 py-0.5 bg-slate-100 text-slate-400 rounded ml-auto">{d.source}</span>
            <div onClick={(e) => e.stopPropagation()}>
              <StarButton listingId={d.listing_id} isSaved={isSaved} onToggle={onToggle} />
            </div>
          </div>

          {/* Row 2: title */}
          <div className="font-semibold text-slate-900 text-xs leading-snug line-clamp-1">{d.title}</div>

          {/* Row 3: meta */}
          <div className="flex items-center gap-2 text-xs text-slate-400 flex-wrap">
            <span>{fmtMi(d.mileage)}</span>
            {d.location && <span className="truncate max-w-[100px]">{d.location}</span>}
            {timeLabel && (
              <span className={`ml-auto ${sortKey === "first_seen" ? "text-blue-500 font-medium" : ""}`}>
                {timeLabel}
              </span>
            )}
          </div>

          {/* Row 4: prices */}
          <div className="flex items-center gap-3">
            <div>
              <div className="text-xs text-slate-400">Ask</div>
              <div className="text-sm font-bold text-slate-900">{fmt(d.asking_price)}</div>
            </div>
            {savings != null && (
              <div className={`text-xs font-bold ml-auto ${savings > 0 ? "text-emerald-600" : "text-red-500"}`}>
                {savings > 0 ? `▼ ${fmt(savings)}` : `▲ ${fmt(Math.abs(savings))}`}
              </div>
            )}
          </div>

          {/* Row 5: bar */}
          {reference != null && (
            <BelowMarketBar asking={d.asking_price} market={reference} />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

type SortKey = "profit_estimate" | "title" | "asking_price" | "total_score" | "mileage" | "first_seen";
type SortDir = "asc" | "desc";

function sortDeals(deals: Deal[], key: SortKey, dir: SortDir): Deal[] {
  return [...deals].sort((a, b) => {
    // Date sort: compare ISO strings (lexicographic works for ISO 8601)
    if (key === "first_seen") {
      const av = a.first_seen ?? "";
      const bv = b.first_seen ?? "";
      return dir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
    }
    let av: number | string | null = null;
    let bv: number | string | null = null;
    if (key === "title") { av = a.title ?? ""; bv = b.title ?? ""; }
    else { av = (a as unknown as Record<string, number>)[key] ?? null; bv = (b as unknown as Record<string, number>)[key] ?? null; }
    if (av === null && bv === null) return 0;
    if (av === null) return 1;
    if (bv === null) return -1;
    if (typeof av === "string") return dir === "asc" ? av.localeCompare(bv as string) : (bv as string).localeCompare(av);
    return dir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
  });
}

const SORT_OPTIONS: { label: string; key: SortKey }[] = [
  { label: "Score",    key: "total_score" },
  { label: "Profit",   key: "profit_estimate" },
  { label: "Price",    key: "asking_price" },
  { label: "Miles",    key: "mileage" },
  { label: "Newest",   key: "first_seen" },
];

// ── Search filter helpers ─────────────────────────────────────────────────────

const DEFAULT_SEARCHES: { name: string; criteria: SearchCriteria }[] = [
  { name: "Z71",               criteria: { query: "z71" } },
  { name: "Denali",            criteria: { query: "denali" } },
  { name: "GX470",             criteria: { query: "gx470" } },
  { name: "Toyota Camry",      criteria: { query: "camry",      make: "Toyota",  model: "Camry" } },
  { name: "Mercedes C300",     criteria: { query: "c300" } },
  { name: "Volkswagen Tiguan", criteria: { query: "tiguan" } },
  { name: "Ford Fusion",       criteria: { query: "fusion",     make: "Ford",    model: "Fusion" } },
  { name: "Honda Civic",       criteria: { query: "civic",      make: "Honda",   model: "Civic" } },
  { name: "Chevy Silverado",   criteria: { query: "silverado" } },
  { name: "Mercedes CLA250",   criteria: { query: "cla250" } },
  { name: "BMW 428i",          criteria: { query: "428i" } },
  { name: "BMW 435i",          criteria: { query: "435i" } },
  { name: "Toyota Highlander", criteria: { query: "highlander", make: "Toyota",  model: "Highlander" } },
  { name: "Chevy Malibu",      criteria: { query: "malibu" } },
  { name: "Honda Accord",      criteria: { query: "accord",     make: "Honda",   model: "Accord" } },
  { name: "BMW 328 Wagon",     criteria: { query: "328" } },
  { name: "Toyota Tacoma",     criteria: { query: "tacoma",     make: "Toyota",  model: "Tacoma" } },
];

function matchesCriteria(deal: Deal, criteria: SearchCriteria): boolean {
  if (criteria.make && !deal.make?.toLowerCase().includes(criteria.make.toLowerCase())) return false;
  if (criteria.model && !deal.model?.toLowerCase().includes(criteria.model.toLowerCase())) return false;
  if (criteria.min_year && (deal.year ?? 0) < criteria.min_year) return false;
  if (criteria.max_year && (deal.year ?? 9999) > criteria.max_year) return false;
  if (criteria.min_price && deal.asking_price < criteria.min_price) return false;
  if (criteria.max_price && deal.asking_price > criteria.max_price) return false;
  if (criteria.max_mileage && (deal.mileage ?? 0) > criteria.max_mileage) return false;
  if (criteria.query) {
    const q = criteria.query.toLowerCase();
    const haystack = [deal.title, deal.make, deal.model].filter(Boolean).join(" ").toLowerCase();
    if (!haystack.includes(q)) return false;
  }
  return true;
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
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);
  const [activeSearchIds, setActiveSearchIds] = useState<Set<string>>(new Set());

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      // Newest first is the natural default for a date sort
      setSortDir(key === "first_seen" ? "desc" : "desc");
    }
  }

  useEffect(() => {
    getFavorites()
      .then((favs) => setFavoriteIds(new Set(favs.map((f) => f.listing_id))))
      .catch(() => {});
    const user = getUser();
    if (user?.id) {
      getSavedSearches(user.id).then(setSavedSearches).catch(() => {});
    }
  }, []);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const data = filter === "saved" ? await getFavorites() : await getDeals(filter || undefined);
        setDeals(data);
      } catch { /* ignore */ }
      setLoading(false);
    };
    load();
  }, [filter]);

  async function toggleFavorite(e: React.MouseEvent, listingId: string) {
    e.stopPropagation();
    const isSaved = favoriteIds.has(listingId);
    setFavoriteIds((prev) => {
      const next = new Set(prev);
      isSaved ? next.delete(listingId) : next.add(listingId);
      return next;
    });
    try {
      if (isSaved) await removeFavorite(listingId);
      else await saveFavorite(listingId);
    } catch {
      setFavoriteIds((prev) => {
        const next = new Set(prev);
        isSaved ? next.add(listingId) : next.delete(listingId);
        return next;
      });
    }
  }

  // Build the combined list of named search filters (default + user's saved)
  const allSearchFilters: { id: string; name: string; criteria: SearchCriteria }[] = [
    ...DEFAULT_SEARCHES.map((s, i) => ({ id: `default-${i}`, name: s.name, criteria: s.criteria })),
    ...savedSearches.map((s) => ({ id: `saved-${s.id}`, name: s.name, criteria: s.criteria })),
  ];

  const visible = sortDeals(
    deals.filter((d) => {
      // Text search
      if (search) {
        const q = search.toLowerCase();
        const hay = [d.title, d.make, d.model].filter(Boolean).join(" ").toLowerCase();
        if (!hay.includes(q)) return false;
      }
      // Search filter: deal must match ANY of the active searches (union)
      if (activeSearchIds.size > 0) {
        const matchesAny = allSearchFilters
          .filter((f) => activeSearchIds.has(f.id))
          .some((f) => matchesCriteria(d, f.criteria));
        if (!matchesAny) return false;
      }
      return true;
    }),
    sortKey,
    sortDir,
  );

  const greatCount = deals.filter((d) => d.deal_class === "great").length;
  const fairCount = deals.filter((d) => d.deal_class === "fair").length;

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* ── Top bar: header + controls ── */}
      <div className="flex-shrink-0 bg-white border-b border-slate-100 px-4 py-3 space-y-3">
        {/* Header row */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-slate-900">Signal Deals</h1>
            <p className="text-xs text-slate-400 mt-0.5">
              {greatCount > 0 && <span className="text-emerald-600 font-medium">{greatCount} great</span>}
              {greatCount > 0 && fairCount > 0 && <span className="text-slate-300"> · </span>}
              {fairCount > 0 && <span className="text-amber-600 font-medium">{fairCount} fair</span>}
              {(greatCount > 0 || fairCount > 0) && <span className="text-slate-300"> · </span>}
              <span>{deals.length} total</span>
            </p>
          </div>
        </div>

        {/* Search filter pills */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-slate-400 font-medium flex-shrink-0">Filter by search:</span>
          <div className="flex gap-1.5 flex-wrap">
            {allSearchFilters.map(({ id, name }) => {
              const active = activeSearchIds.has(id);
              return (
                <button
                  key={id}
                  onClick={() => {
                    setActiveSearchIds((prev) => {
                      const next = new Set(prev);
                      active ? next.delete(id) : next.add(id);
                      return next;
                    });
                  }}
                  className={`px-2.5 py-1 text-xs font-medium rounded-full border transition-colors ${
                    active
                      ? "bg-slate-900 text-white border-slate-900"
                      : "bg-white text-slate-500 border-slate-200 hover:border-slate-400 hover:text-slate-700"
                  }`}
                >
                  {name}
                </button>
              );
            })}
            {activeSearchIds.size > 0 && (
              <button
                onClick={() => setActiveSearchIds(new Set())}
                className="px-2.5 py-1 text-xs font-medium rounded-full text-slate-400 hover:text-slate-600 transition-colors"
              >
                Clear ✕
              </button>
            )}
          </div>
        </div>

        {/* Controls row */}
        <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
          {/* Filter pills */}
          <div className="flex gap-1">
            {FILTERS.map(({ label, value }) => (
              <button
                key={value}
                onClick={() => setFilter(value)}
                className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors ${
                  filter === value
                    ? "bg-slate-900 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Search */}
          <input
            className="text-xs border border-gray-200 rounded-lg px-3 py-1.5 w-full sm:w-48 focus:outline-none focus:ring-2 focus:ring-slate-300 bg-white"
            placeholder="Search make, model…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />

          {/* Sort */}
          <div className="flex gap-1 items-center sm:ml-auto">
            <span className="text-xs text-slate-400 mr-0.5">Sort:</span>
            {SORT_OPTIONS.map(({ label, key }) => (
              <button
                key={key}
                onClick={() => handleSort(key)}
                className={`px-2 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                  sortKey === key
                    ? "bg-slate-900 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {label}
                {sortKey === key ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Body: master-detail two-column layout ── */}
      <div className="flex-1 flex overflow-hidden min-h-0">
        {/* Left column: scrollable deal list */}
        <div
          className={`
            flex-shrink-0 border-r border-slate-100 bg-slate-50 overflow-y-auto
            w-full lg:w-[380px] xl:w-[420px]
            ${selected ? "hidden lg:flex lg:flex-col" : "flex flex-col"}
          `}
        >
          {loading ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-slate-400 text-sm">Loading…</div>
            </div>
          ) : visible.length === 0 ? (
            <div className="flex-1 flex items-center justify-center p-8 text-center">
              <div className="space-y-2">
                <div className="text-3xl text-slate-300">🔍</div>
                <div className="text-sm text-slate-400">
                  {filter === "saved"
                    ? "No saved listings yet. Tap ☆ on any deal."
                    : "No deals found. Run the pipeline from the Dashboard."}
                </div>
              </div>
            </div>
          ) : (
            <div className="p-3 space-y-2">
              {visible.map((d) => (
                <SignalCard
                  key={d.listing_id}
                  d={d}
                  onClick={() => setSelected(d)}
                  isSaved={favoriteIds.has(d.listing_id)}
                  onToggle={toggleFavorite}
                  isSelected={selected?.listing_id === d.listing_id}
                  sortKey={sortKey}
                />
              ))}
            </div>
          )}
        </div>

        {/* Right column: detail panel */}
        <div
          className={`
            flex-1 overflow-hidden
            ${selected ? "flex flex-col" : "hidden lg:flex lg:items-center lg:justify-center"}
          `}
        >
          {selected ? (
            // Desktop: embedded panel (no overlay)
            // Mobile: uses overlay DealPanel below
            <>
              {/* Desktop embedded panel */}
              <div className="hidden lg:flex lg:flex-col h-full">
                <DealPanel deal={selected} onClose={() => setSelected(null)} embedded />
              </div>
              {/* Mobile: full-screen (not overlay) */}
              <div className="flex flex-col h-full lg:hidden">
                <DealPanel deal={selected} onClose={() => setSelected(null)} />
              </div>
            </>
          ) : (
            <div className="text-center space-y-3 text-slate-300">
              <svg className="w-12 h-12 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7" />
              </svg>
              <div className="text-sm font-medium">Select a deal to inspect</div>
              <div className="text-xs">{visible.length} deals in queue</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

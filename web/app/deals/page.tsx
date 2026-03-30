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

const CLASS_BORDER: Record<DealClass, string> = {
  great: "border-l-emerald-500",
  fair: "border-l-amber-400",
  poor: "border-l-red-400",
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
  if (!status || status === "unknown") return null;
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold capitalize ${TITLE_BADGE[status] ?? "bg-gray-100 text-gray-500"}`}>
      {status}
    </span>
  );
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

function CarvanaOfferSection({ deal }: { deal: Deal }) {
  const [manualVin, setManualVin] = useState(deal.vin ?? "");
  const [job, setJob] = useState<CarvanaOfferStatus>({ status: "not_started", offer: null, error: null, steps: [] });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
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
    if (!manualVin.trim()) return;
    setJob({ status: "running", offer: null, error: null, steps: [] });
    await startCarvanaOffer(deal.listing_id, manualVin.trim());
  };

  const vinIsValid = manualVin.trim().length === 17;

  return (
    <div className="rounded-lg bg-slate-50 border border-slate-200 p-4 space-y-3">
      {/* VIN row */}
      <div>
        <div className="text-xs text-slate-500 font-medium uppercase tracking-wide mb-1">VIN</div>
        {deal.vin ? (
          <div className="font-mono text-slate-900 font-bold tracking-widest text-sm break-all">{deal.vin}</div>
        ) : (
          <input
            className="w-full font-mono text-sm border border-slate-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#00aed9] placeholder-slate-300"
            placeholder="Paste 17-digit VIN to get offer"
            value={manualVin}
            onChange={(e) => setManualVin(e.target.value.toUpperCase())}
            maxLength={17}
            disabled={job.status === "running"}
          />
        )}
      </div>

      {/* Offer status */}
      {job.status === "completed" && job.offer && (
        <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-3 space-y-1">
          <div className="text-xs text-emerald-600 font-medium">✅ Carvana Cash Offer</div>
          <div className="text-2xl font-bold text-emerald-700">{job.offer}</div>
          <button onClick={start} className="text-xs text-emerald-500 underline">Refresh</button>
        </div>
      )}

      {job.status === "error" && (
        <div className="rounded-lg bg-red-50 border border-red-200 p-3 space-y-1">
          <div className="text-xs text-red-700 font-medium">Automation failed</div>
          <div className="text-xs text-red-500 leading-snug">{job.error}</div>
        </div>
      )}

      {job.status === "running" && (
        <div className="rounded-lg bg-blue-50 border border-blue-200 p-3 space-y-1">
          <div className="flex items-center gap-2 text-blue-700 text-xs font-medium">
            <svg className="animate-spin h-3.5 w-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
            </svg>
            Running Carvana automation…
          </div>
          {job.steps.length > 0 && (
            <div className="text-xs text-blue-400 font-mono truncate">{job.steps[job.steps.length - 1]}</div>
          )}
        </div>
      )}

      {/* Action button */}
      {job.status !== "running" && (
        <button
          onClick={start}
          disabled={!vinIsValid}
          className="w-full flex items-center justify-center gap-2 py-2.5 bg-[#00aed9] text-white text-sm font-semibold rounded-lg hover:opacity-90 active:opacity-80 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
        >
          🤖 Get Carvana Cash Offer (Auto-fill)
        </button>
      )}

      {/* Manual links — only show if VIN known */}
      {(deal.vin || vinIsValid) && job.status !== "running" && (
        <div className="flex flex-wrap gap-2">
          <a href={`https://www.carmax.com/car-value/vin/${manualVin || deal.vin}`} target="_blank" rel="noopener noreferrer"
            className="px-3 py-1.5 bg-[#e31837] text-white text-xs font-semibold rounded hover:opacity-90">
            CarMax Offer ↗
          </a>
          <a href={`https://www.kbb.com/instant-cash-offer/?vin=${manualVin || deal.vin}`} target="_blank" rel="noopener noreferrer"
            className="px-3 py-1.5 bg-slate-700 text-white text-xs font-semibold rounded hover:opacity-90">
            KBB Value ↗
          </a>
        </div>
      )}
    </div>
  );
}

// ── Image Gallery ─────────────────────────────────────────────────────────────

function ImageGallery({ urls }: { urls: string[] }) {
  const [lightbox, setLightbox] = useState<number | null>(null);
  const [failed, setFailed] = useState<number[]>([]);

  const visible = urls.filter((_, i) => !failed.includes(i));

  const openAt = (originalIndex: number) => {
    const visibleIndex = visible.indexOf(urls[originalIndex]);
    if (visibleIndex >= 0) setLightbox(visibleIndex);
  };

  const prev = (e: React.MouseEvent) => { e.stopPropagation(); setLightbox((n) => (n != null && n > 0 ? n - 1 : n)); };
  const next = (e: React.MouseEvent) => { e.stopPropagation(); setLightbox((n) => (n != null && n < visible.length - 1 ? n + 1 : n)); };

  const handleKey = (e: KeyboardEvent) => {
    if (lightbox === null) return;
    if (e.key === "ArrowLeft" && lightbox > 0) setLightbox(lightbox - 1);
    if (e.key === "ArrowRight" && lightbox < visible.length - 1) setLightbox(lightbox + 1);
    if (e.key === "Escape") setLightbox(null);
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [lightbox, visible.length]);

  if (visible.length === 0 && failed.length < urls.length) return null;

  return (
    <>
      <div className="relative">
        <div className="flex gap-2 overflow-x-auto pb-2 snap-x snap-mandatory scrollbar-thin">
          {urls.map((url, i) => (
            <img
              key={i}
              src={url}
              alt={`Photo ${i + 1}`}
              referrerPolicy="no-referrer"
              onClick={() => openAt(i)}
              onError={() => setFailed((s) => s.includes(i) ? s : [...s, i])}
              className={`h-28 w-40 object-cover rounded-lg flex-shrink-0 snap-start cursor-pointer hover:opacity-90 transition-opacity border border-gray-100 ${failed.includes(i) ? "hidden" : ""}`}
            />
          ))}
        </div>
        {visible.length > 1 && (
          <div className="absolute bottom-3 right-2 bg-black/50 text-white text-xs px-1.5 py-0.5 rounded pointer-events-none">
            {visible.length} photos
          </div>
        )}
      </div>

      {lightbox !== null && (
        <div
          className="fixed inset-0 z-[100] bg-black/95 flex items-center justify-center"
          onClick={() => setLightbox(null)}
        >
          <button className="absolute top-4 right-4 text-white text-2xl hover:opacity-70 z-10" onClick={() => setLightbox(null)}>✕</button>
          <div className="absolute top-4 left-1/2 -translate-x-1/2 text-white text-sm bg-black/40 px-3 py-1 rounded-full">
            {lightbox + 1} / {visible.length}
          </div>
          {lightbox > 0 && (
            <button className="absolute left-3 md:left-6 text-white text-4xl hover:opacity-70 px-3 py-6 z-10" onClick={prev}>‹</button>
          )}
          <img
            src={visible[lightbox]}
            alt={`Photo ${lightbox + 1}`}
            referrerPolicy="no-referrer"
            className="max-h-[85vh] max-w-[90vw] object-contain rounded"
            onClick={(e) => e.stopPropagation()}
          />
          {lightbox < visible.length - 1 && (
            <button className="absolute right-3 md:right-6 text-white text-4xl hover:opacity-70 px-3 py-6 z-10" onClick={next}>›</button>
          )}
          {visible.length > 1 && (
            <div className="absolute bottom-4 left-0 right-0 flex justify-center gap-1.5 px-4 overflow-x-auto">
              {visible.map((url, i) => (
                <img
                  key={i}
                  src={url}
                  alt=""
                  referrerPolicy="no-referrer"
                  onClick={(e) => { e.stopPropagation(); setLightbox(i); }}
                  className={`h-12 w-16 object-cover rounded flex-shrink-0 cursor-pointer transition-all ${i === lightbox ? "ring-2 ring-white opacity-100" : "opacity-50 hover:opacity-80"}`}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </>
  );
}

function DealDrawer({ deal, onClose }: { deal: Deal; onClose: () => void }) {
  const savings = deal.savings ?? (deal.kbb_value ? deal.kbb_value - deal.asking_price : null);

  return (
    <div className="fixed inset-0 z-50 flex flex-col md:flex-row" onClick={onClose}>
      <div className="flex-1 bg-black/40" />
      <div
        className="w-full md:w-[520px] bg-white max-h-[92vh] md:max-h-none md:h-full overflow-y-auto shadow-2xl rounded-t-2xl md:rounded-none p-6 md:p-8 space-y-5"
        onClick={(e) => e.stopPropagation()}
      >
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

        {deal.image_urls && deal.image_urls.length > 0 ? (
          <ImageGallery urls={deal.image_urls} />
        ) : (
          <div className="text-xs text-slate-400 italic">No images found</div>
        )}

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

        {savings != null && (
          <div className={`rounded-lg p-4 ${savings > 0 ? "bg-emerald-50" : "bg-red-50"}`}>
            <div className="text-xs font-medium mb-1 text-slate-500">vs Market Value</div>
            <div className={`text-xl md:text-2xl font-bold ${savings > 0 ? "text-emerald-700" : "text-red-600"}`}>
              {savings > 0 ? `▼ ${fmt(savings)} below market` : `▲ ${fmt(Math.abs(savings))} above market`}
            </div>
          </div>
        )}

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

        <a href={deal.url} target="_blank" rel="noopener noreferrer"
          className="block w-full text-center py-3 bg-slate-900 text-white font-medium rounded-lg hover:bg-slate-700 transition-colors">
          View Listing ↗
        </a>

        <CarvanaOfferSection deal={deal} />

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

// ── Signal Card (unified mobile + desktop) ────────────────────────────────────

function BelowMarketBar({ asking, market }: { asking: number; market: number }) {
  const pct = Math.round(((market - asking) / market) * 100);
  const absPct = Math.min(Math.abs(pct), 50); // cap bar at 50%
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

function SignalCard({ d, onClick, isSaved, onToggle }: {
  d: Deal;
  onClick: () => void;
  isSaved: boolean;
  onToggle: (e: React.MouseEvent, id: string) => void;
}) {
  const reference = d.blended_market_value ?? d.kbb_value;
  const savings = d.savings ?? (reference ? reference - d.asking_price : null);
  const posted = daysAgo(d.posted_date);
  const thumb = d.image_urls?.[0];

  return (
    <div
      onClick={onClick}
      className={`bg-white rounded-xl border border-gray-100 border-l-4 ${CLASS_BORDER[d.deal_class]} shadow-sm cursor-pointer hover:shadow-md transition-shadow`}
    >
      <div className="flex gap-0">
        {/* Thumbnail */}
        {thumb && (
          <div className="flex-shrink-0 w-28 sm:w-36">
            <img
              src={thumb}
              alt=""
              referrerPolicy="no-referrer"
              className="w-full h-full object-cover rounded-r-none rounded-l-[10px] min-h-[100px]"
            />
          </div>
        )}

        {/* Content */}
        <div className="flex-1 min-w-0 p-4 space-y-2.5">
          {/* Row 1: badge + meta + star */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold ${CLASS_BADGE[d.deal_class]}`}>
              {CLASS_ICON[d.deal_class]} {d.total_score}/100
            </span>
            {d.title_status && d.title_status !== "clean" && d.title_status !== "unknown" && (
              <TitleBadge status={d.title_status} />
            )}
            <span className="text-xs px-1.5 py-0.5 bg-slate-100 text-slate-500 rounded">{d.source}</span>
            <div className="ml-auto" onClick={(e) => e.stopPropagation()}>
              <StarButton listingId={d.listing_id} isSaved={isSaved} onToggle={onToggle} />
            </div>
          </div>

          {/* Row 2: title */}
          <div className="font-semibold text-slate-900 leading-snug line-clamp-1">{d.title}</div>

          {/* Row 3: meta */}
          <div className="flex items-center gap-3 text-xs text-slate-500 flex-wrap">
            <span>{d.year} · {d.make} {d.model}</span>
            <span>{fmtMi(d.mileage)}</span>
            {d.location && <span className="truncate">{d.location}</span>}
            {posted && (
              <span className={`font-medium ${parseInt(posted) >= 14 ? "text-amber-600" : "text-slate-500"}`}>
                🕐 {posted}
              </span>
            )}
          </div>

          {/* Row 4: price + bar */}
          <div className="flex items-end gap-4 flex-wrap">
            <div>
              <div className="text-xs text-slate-400">Asking</div>
              <div className="text-lg font-bold text-slate-900">{fmt(d.asking_price)}</div>
            </div>
            {reference != null && (
              <div>
                <div className="text-xs text-slate-400">Market</div>
                <div className="text-sm font-semibold text-slate-600">{fmt(reference)}</div>
              </div>
            )}
            {d.carvana_value != null && (
              <div>
                <div className="text-xs text-slate-400">Carvana</div>
                <div className="text-sm font-semibold text-[#00aed9]">{fmt(d.carvana_value)}</div>
              </div>
            )}
          </div>

          {/* Row 5: % below market bar */}
          {reference != null && savings != null && (
            <BelowMarketBar asking={d.asking_price} market={reference} />
          )}

          {/* Row 6: actions */}
          <div className="flex items-center gap-2 pt-1" onClick={(e) => e.stopPropagation()}>
            <a
              href={d.url}
              target="_blank"
              rel="noopener noreferrer"
              className="px-3 py-1.5 text-xs font-medium bg-slate-100 text-slate-700 rounded-lg hover:bg-slate-200 transition-colors"
            >
              View Listing ↗
            </a>
            <button
              onClick={(e) => { e.stopPropagation(); onClick(); }}
              className="px-3 py-1.5 text-xs font-medium bg-[#00aed9]/10 text-[#00aed9] rounded-lg hover:bg-[#00aed9]/20 transition-colors"
            >
              🤖 Get Offer
            </button>
          </div>
        </div>
      </div>
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

const SORT_OPTIONS: { label: string; key: SortKey }[] = [
  { label: "Score", key: "total_score" },
  { label: "Profit", key: "profit_estimate" },
  { label: "Price", key: "asking_price" },
  { label: "Mileage", key: "mileage" },
];

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

  const greatCount = deals.filter((d) => d.deal_class === "great").length;
  const fairCount = deals.filter((d) => d.deal_class === "fair").length;

  return (
    <div className="p-4 md:p-8 space-y-4 md:space-y-6 max-w-[1000px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl md:text-2xl font-bold text-slate-900">Deals</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            {greatCount > 0 && <span className="text-emerald-600 font-medium">{greatCount} great</span>}
            {greatCount > 0 && fairCount > 0 && <span className="text-slate-400"> · </span>}
            {fairCount > 0 && <span className="text-amber-600 font-medium">{fairCount} fair</span>}
            {(greatCount > 0 || fairCount > 0) && <span className="text-slate-400"> · </span>}
            <span>{deals.length} total</span>
          </p>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-col sm:flex-row gap-2 sm:gap-3 items-stretch sm:items-center">
        {/* Filter tabs */}
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

        {/* Search */}
        <input
          className="text-sm border border-gray-200 rounded-lg px-3 py-2 w-full sm:w-64 focus:outline-none focus:ring-2 focus:ring-slate-300 bg-white"
          placeholder="Search make, model, title…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        {/* Sort */}
        <div className="flex gap-1 items-center ml-auto">
          <span className="text-xs text-slate-400 mr-1 hidden sm:inline">Sort:</span>
          {SORT_OPTIONS.map(({ label, key }) => (
            <button
              key={key}
              onClick={() => handleSort(key)}
              className={`px-2.5 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                sortKey === key
                  ? "bg-slate-900 text-white"
                  : "bg-white border border-gray-200 text-slate-600 hover:bg-gray-50"
              }`}
            >
              {label}{sortKey === key ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
            </button>
          ))}
        </div>
      </div>

      {/* Cards */}
      {loading ? (
        <div className="p-12 text-center text-slate-400 text-sm">Loading…</div>
      ) : visible.length === 0 ? (
        <div className="p-12 text-center text-slate-400 text-sm">
          {filter === "saved"
            ? "No saved listings yet. Tap ☆ on any deal to save it here."
            : "No deals found. Run the pipeline from the Dashboard."}
        </div>
      ) : (
        <div className="space-y-3">
          {visible.map((d) => (
            <SignalCard
              key={d.listing_id}
              d={d}
              onClick={() => setSelected(d)}
              isSaved={favoriteIds.has(d.listing_id)}
              onToggle={toggleFavorite}
            />
          ))}
        </div>
      )}

      {selected && <DealDrawer deal={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

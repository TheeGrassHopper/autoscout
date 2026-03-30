"use client";

import { useEffect, useState } from "react";
import { getUser } from "@/lib/auth";
import {
  type Deal,
  type SavedSearch,
  type SearchCriteria,
  createSavedSearch,
  updateSavedSearch,
  deleteSavedSearch,
  deleteAllSavedSearches,
  getSavedSearches,
  previewSearch,
  runPipeline,
  getPipelineStatus,
} from "@/lib/api";

// ── Default searches (always shown, cannot be deleted) ────────────────────────

const DEFAULT_SEARCHES: { name: string; criteria: SearchCriteria }[] = [
  { name: "Z71",               criteria: { query: "z71" } },
  { name: "Denali",            criteria: { query: "denali" } },
  { name: "GX470",             criteria: { query: "gx470" } },
  { name: "Toyota Camry",      criteria: { query: "camry",      make: "Toyota",    model: "Camry" } },
  { name: "Mercedes C300",     criteria: { query: "c300" } },
  { name: "Volkswagen Tiguan", criteria: { query: "tiguan" } },
  { name: "Ford Fusion",       criteria: { query: "fusion",     make: "Ford",      model: "Fusion" } },
  { name: "Honda Civic",       criteria: { query: "civic",      make: "Honda",     model: "Civic" } },
  { name: "Chevy Silverado",   criteria: { query: "silverado" } },
  { name: "Mercedes CLA250",   criteria: { query: "cla250" } },
  { name: "BMW 428i",          criteria: { query: "428i" } },
  { name: "BMW 435i",          criteria: { query: "435i" } },
  { name: "Toyota Highlander", criteria: { query: "highlander", make: "Toyota",    model: "Highlander" } },
  { name: "Chevy Malibu",      criteria: { query: "malibu" } },
  { name: "Honda Accord",      criteria: { query: "accord",     make: "Honda",     model: "Accord" } },
  { name: "BMW 328 Wagon",     criteria: { query: "328" } },
  { name: "Toyota Tacoma",     criteria: { query: "tacoma",     make: "Toyota",    model: "Tacoma" } },
];

function fmt(n?: number | null) {
  if (n == null) return "—";
  return `$${n.toLocaleString()}`;
}
function fmtMi(n?: number | null) {
  if (n == null) return "—";
  return `${n.toLocaleString()} mi`;
}

// ── Deal class badge ─────────────────────────────────────────────────────────

function DealBadge({ cls }: { cls?: string }) {
  const map: Record<string, string> = {
    great: "bg-green-100 text-green-700",
    fair:  "bg-yellow-100 text-yellow-700",
    poor:  "bg-red-100 text-red-600",
  };
  const label = cls === "great" ? "Great" : cls === "fair" ? "Fair" : cls === "poor" ? "Poor" : null;
  if (!label) return null;
  return (
    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${map[cls!] ?? ""}`}>
      {label}
    </span>
  );
}

// ── Inline results list ───────────────────────────────────────────────────────

function InlineResults({ deals, onClose }: { deals: Deal[]; onClose: () => void }) {
  return (
    <div className="mt-3 border-t border-gray-100">
      <div className="flex items-center justify-between py-2">
        <span className="text-xs font-semibold text-slate-500">
          {deals.length === 0 ? "No matches in current listings" : `${deals.length} matching listings`}
        </span>
        <button onClick={onClose} className="text-[11px] text-slate-400 hover:text-slate-600">
          Clear ✕
        </button>
      </div>

      {deals.length > 0 && (
        <div className="divide-y divide-gray-50 max-h-72 overflow-y-auto rounded-lg border border-gray-100">
          {deals.map((d) => (
            <a
              key={d.listing_id}
              href={d.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-between gap-3 px-4 py-2.5 hover:bg-slate-50 transition-colors"
            >
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-slate-800 truncate">{d.title}</div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-xs text-slate-400">{d.location}</span>
                  {d.mileage ? <span className="text-xs text-slate-400">{fmtMi(d.mileage)}</span> : null}
                  {d.year ? <span className="text-xs text-slate-400">{d.year}</span> : null}
                </div>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <DealBadge cls={d.deal_class} />
                <div className="text-right">
                  <div className="text-sm font-semibold text-slate-900">{fmt(d.asking_price)}</div>
                  {d.savings > 0 && (
                    <div className="text-[11px] text-green-600 font-medium">-{fmt(d.savings)}</div>
                  )}
                </div>
              </div>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Criteria edit form ────────────────────────────────────────────────────────

function CriteriaForm({
  name,
  criteria,
  isDefault,
  onRun,
  onSaveNew,
  onUpdate,
  onCancel,
  running,
  saving,
}: {
  name: string;
  criteria: SearchCriteria;
  isDefault?: boolean;
  onRun: (c: SearchCriteria) => void;
  onSaveNew: (name: string, c: SearchCriteria) => void;
  onUpdate?: (name: string, c: SearchCriteria) => void;
  onCancel: () => void;
  running: boolean;
  saving: boolean;
}) {
  const [editName, setEditName] = useState(name);
  const [c, setC] = useState<SearchCriteria>({ ...criteria });

  const inp = (
    placeholder: string,
    value: string | number | null | undefined,
    onChange: (v: string) => void,
    type = "text"
  ) => (
    <input
      type={type}
      className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-slate-300"
      placeholder={placeholder}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
    />
  );

  return (
    <div className="mt-3 pt-3 border-t border-gray-100 space-y-3">
      <div className="space-y-1">
        <label className="text-[11px] font-medium text-slate-400 uppercase tracking-wide">Search name</label>
        <input
          className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-slate-300"
          value={editName}
          onChange={(e) => setEditName(e.target.value)}
        />
      </div>

      <div className="space-y-1">
        <label className="text-[11px] font-medium text-slate-400 uppercase tracking-wide">Keyword</label>
        {inp("e.g. tacoma", c.query, (v) => setC((x) => ({ ...x, query: v })))}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className="text-[11px] font-medium text-slate-400 uppercase tracking-wide">Make</label>
          {inp("Toyota", c.make, (v) => setC((x) => ({ ...x, make: v || null })))}
        </div>
        <div className="space-y-1">
          <label className="text-[11px] font-medium text-slate-400 uppercase tracking-wide">Model</label>
          {inp("Tacoma", c.model, (v) => setC((x) => ({ ...x, model: v || null })))}
        </div>
        <div className="space-y-1">
          <label className="text-[11px] font-medium text-slate-400 uppercase tracking-wide">Min year</label>
          {inp("2015", c.min_year, (v) => setC((x) => ({ ...x, min_year: v ? +v : null })), "number")}
        </div>
        <div className="space-y-1">
          <label className="text-[11px] font-medium text-slate-400 uppercase tracking-wide">Max year</label>
          {inp("2024", c.max_year, (v) => setC((x) => ({ ...x, max_year: v ? +v : null })), "number")}
        </div>
        <div className="space-y-1">
          <label className="text-[11px] font-medium text-slate-400 uppercase tracking-wide">Max price</label>
          {inp("30000", c.max_price, (v) => setC((x) => ({ ...x, max_price: v ? +v : null })), "number")}
        </div>
        <div className="space-y-1">
          <label className="text-[11px] font-medium text-slate-400 uppercase tracking-wide">Max mileage</label>
          {inp("120000", c.max_mileage, (v) => setC((x) => ({ ...x, max_mileage: v ? +v : null })), "number")}
        </div>
      </div>

      <div className="flex flex-wrap gap-2 pt-1">
        <button
          onClick={() => onRun(c)}
          disabled={running}
          className="px-3 py-1.5 bg-slate-900 text-white text-xs font-medium rounded-lg hover:bg-slate-700 disabled:opacity-40 transition-colors"
        >
          {running ? "Running…" : "▶ Run with these filters"}
        </button>

        {onUpdate && (
          <button
            onClick={() => onUpdate(editName, c)}
            disabled={saving || !editName.trim()}
            className="px-3 py-1.5 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 transition-colors"
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
        )}

        <button
          onClick={() => onSaveNew(editName, c)}
          disabled={saving || !editName.trim()}
          className="px-3 py-1.5 border border-slate-300 text-slate-700 text-xs font-medium rounded-lg hover:bg-slate-50 disabled:opacity-40 transition-colors"
        >
          {saving ? "Saving…" : isDefault ? "Save as new" : "Duplicate"}
        </button>

        {isDefault && (
          <button
            onClick={() => { setC({ ...criteria }); setEditName(name); }}
            className="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-600 transition-colors"
          >
            Reset
          </button>
        )}

        <button onClick={onCancel} className="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-600 transition-colors">
          Cancel
        </button>
      </div>
    </div>
  );
}

// ── Search card (self-contained: runs, scrapes, shows inline results, edits) ──

type ScrapePhase = "idle" | "scraping" | "done" | "error";

function SearchCard({
  name,
  criteria,
  isDefault,
  saving,
  onSaveNew,
  onUpdate,
  onDelete,
}: {
  name: string;
  criteria: SearchCriteria;
  isDefault?: boolean;
  saving: boolean;
  onSaveNew: (name: string, c: SearchCriteria) => void;
  onUpdate?: (name: string, c: SearchCriteria) => void;
  onDelete?: () => void;
}) {
  const [editing,     setEditing]     = useState(false);
  const [searching,   setSearching]   = useState(false);
  const [scrapePhase, setScrapePhase] = useState<ScrapePhase>("idle");
  const [scrapeMsg,   setScrapeMsg]   = useState("");
  const [results,     setResults]     = useState<Deal[] | null>(null);
  const [error,       setError]       = useState<string | null>(null);
  const user = getUser();

  /** Filter existing DB listings for these criteria */
  const search = async (c: SearchCriteria) => {
    if (!user) return;
    setSearching(true);
    setError(null);
    setResults(null);
    try {
      const { results: deals } = await previewSearch(user.id, c);
      setResults(deals);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setSearching(false);
    }
  };

  /** Trigger pipeline scrape for this query, poll until done, then show results */
  const scrape = async (c: SearchCriteria) => {
    if (!user || scrapePhase === "scraping") return;
    setScrapePhase("scraping");
    setScrapeMsg("Starting scrape…");
    setResults(null);
    setError(null);
    try {
      await runPipeline(
        c.query ?? "",
        false,                             // dryRun = false → actually save listings
        c.zip_code ?? "",
        c.radius_miles ?? 0,
        false,                             // skip FB (slow) for per-search scrapes
        {
          minYear:    c.min_year  ?? undefined,
          maxYear:    c.max_year  ?? undefined,
          maxPrice:   c.max_price ?? undefined,
          maxMileage: c.max_mileage ?? undefined,
        }
      );
    } catch (err: unknown) {
      setScrapePhase("error");
      setError(err instanceof Error ? err.message : "Pipeline failed to start");
      return;
    }

    // Poll pipeline status until it finishes
    setScrapeMsg("Scraping listings…");
    const start = Date.now();
    const MAX_WAIT_MS = 5 * 60 * 1000; // 5 min timeout
    let finished = false;
    while (Date.now() - start < MAX_WAIT_MS) {
      await new Promise((r) => setTimeout(r, 4000));
      try {
        const status = await getPipelineStatus();
        if (!status.running) { finished = true; break; }
        const elapsed = Math.round((Date.now() - start) / 1000);
        setScrapeMsg(`Scraping… ${elapsed}s`);
      } catch { /* ignore poll errors */ }
    }

    if (!finished) {
      setScrapePhase("error");
      setError("Scrape timed out — try Run to see partial results");
      return;
    }

    setScrapeMsg("Scrape complete — loading results…");
    setScrapePhase("done");
    await search(c);
  };

  const busy = searching || scrapePhase === "scraping";

  return (
    <div className={`bg-white rounded-xl shadow-sm border transition-colors ${
      editing ? "border-slate-300" : results !== null ? "border-slate-200" : "border-gray-100 hover:border-slate-200"
    }`}>
      <div className="p-4">
        {/* Header */}
        <div className="flex flex-wrap items-start gap-3">
          <button className="flex-1 min-w-0 text-left" onClick={() => setEditing((v) => !v)}>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold text-slate-900 text-sm">{name}</span>
              {isDefault && (
                <span className="text-[10px] font-medium px-1.5 py-0.5 bg-slate-100 text-slate-400 rounded">
                  default
                </span>
              )}
              {results !== null && !editing && (
                <span className="text-[10px] font-medium px-1.5 py-0.5 bg-blue-50 text-blue-500 rounded">
                  {results.length} results
                </span>
              )}
              {scrapePhase === "scraping" && (
                <span className="text-[10px] font-medium px-1.5 py-0.5 bg-amber-50 text-amber-600 rounded animate-pulse">
                  {scrapeMsg}
                </span>
              )}
              <span className="text-[11px] text-slate-300">{editing ? "▲" : "▼"}</span>
            </div>
            <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1">
              {criteria.make && (
                <span className="text-xs text-slate-500">
                  {criteria.make}{criteria.model ? ` ${criteria.model}` : ""}
                </span>
              )}
              {criteria.query && (
                <span className="text-xs text-slate-400">"{criteria.query}"</span>
              )}
              {criteria.min_year && (
                <span className="text-xs text-slate-500">{criteria.min_year}–{criteria.max_year ?? "now"}</span>
              )}
              {criteria.max_price && (
                <span className="text-xs text-slate-500">≤ {fmt(criteria.max_price)}</span>
              )}
              {criteria.max_mileage && (
                <span className="text-xs text-slate-500">≤ {fmtMi(criteria.max_mileage)}</span>
              )}
            </div>
          </button>

          {/* Action buttons */}
          <div className="flex gap-2 flex-shrink-0 items-center">
            {/* Run: filter existing DB */}
            <button
              onClick={(e) => { e.stopPropagation(); search(criteria); }}
              disabled={busy}
              title="Filter your current scraped listings"
              className="px-3 py-1.5 bg-slate-900 text-white text-xs font-medium rounded-lg hover:bg-slate-700 disabled:opacity-40 transition-colors"
            >
              {searching ? "Searching…" : "▶ Run"}
            </button>

            {/* Scrape: trigger pipeline for this query */}
            <button
              onClick={(e) => { e.stopPropagation(); scrape(criteria); }}
              disabled={busy}
              title="Scrape fresh listings from Craigslist for this search"
              className="px-3 py-1.5 bg-emerald-600 text-white text-xs font-medium rounded-lg hover:bg-emerald-700 disabled:opacity-40 transition-colors"
            >
              {scrapePhase === "scraping" ? "Scraping…" : "⬇ Scrape"}
            </button>

            {onDelete && !editing && (
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(); }}
                className="px-3 py-1.5 text-xs text-red-500 hover:text-red-700 border border-red-200 rounded-lg hover:bg-red-50 transition-colors"
              >
                Delete
              </button>
            )}
          </div>
        </div>

        {/* Error */}
        {error && <div className="mt-2 text-xs text-red-500">{error}</div>}

        {/* Inline results */}
        {results !== null && !editing && (
          <InlineResults deals={results} onClose={() => setResults(null)} />
        )}

        {/* Edit form */}
        {editing && (
          <CriteriaForm
            name={name}
            criteria={criteria}
            isDefault={isDefault}
            running={busy}
            saving={saving}
            onRun={(c) => { search(c); setEditing(false); }}
            onSaveNew={(n, c) => { onSaveNew(n, c); setEditing(false); }}
            onUpdate={onUpdate ? (n, c) => { onUpdate(n, c); setEditing(false); } : undefined}
            onCancel={() => setEditing(false)}
          />
        )}
      </div>
    </div>
  );
}

// ── New Search modal ──────────────────────────────────────────────────────────

function NewSearchButton({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen]     = useState(false);
  const [name, setName]     = useState("");
  const [criteria, setCriteria] = useState<SearchCriteria>({ query: "" });
  const [saving, setSaving] = useState(false);
  const user = getUser();

  const save = async () => {
    if (!name.trim() || !user) return;
    setSaving(true);
    try {
      await createSavedSearch(user.id, name.trim(), criteria);
      setName("");
      setCriteria({ query: "" });
      setOpen(false);
      onCreated();
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="px-4 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-700 transition-colors"
      >
        + New Search
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 space-y-4">
            <h3 className="text-sm font-semibold text-slate-900">New Saved Search</h3>

            <div className="space-y-1">
              <label className="text-xs text-slate-500">Name</label>
              <input
                autoFocus
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300"
                placeholder='e.g. "Tacoma under $30k"'
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && save()}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              {(
                [
                  ["Keyword", "query", "tacoma", "text"],
                  ["Make", "make", "Toyota", "text"],
                  ["Model", "model", "Tacoma", "text"],
                  ["Min year", "min_year", "2015", "number"],
                  ["Max year", "max_year", "2024", "number"],
                  ["Max price", "max_price", "30000", "number"],
                  ["Max mileage", "max_mileage", "120000", "number"],
                ] as [string, keyof SearchCriteria, string, string][]
              ).map(([label, key, placeholder, type]) => (
                <div key={key} className="space-y-1">
                  <label className="text-xs text-slate-500">{label}</label>
                  <input
                    type={type}
                    className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300"
                    placeholder={placeholder}
                    value={(criteria[key] as string | number | null | undefined) ?? ""}
                    onChange={(e) =>
                      setCriteria((c) => ({
                        ...c,
                        [key]: e.target.value ? (type === "number" ? +e.target.value : e.target.value) : null,
                      }))
                    }
                  />
                </div>
              ))}
            </div>

            <div className="flex gap-2 justify-end pt-1">
              <button onClick={() => setOpen(false)} className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700">
                Cancel
              </button>
              <button
                onClick={save}
                disabled={saving || !name.trim()}
                className="px-4 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-700 disabled:opacity-40 transition-colors"
              >
                {saving ? "Saving…" : "Save search"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SearchesPage() {
  const [searches, setSearches] = useState<SavedSearch[]>([]);
  const [saving,   setSaving]   = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const user = getUser();

  const load = async () => {
    if (!user) return;
    try { setSearches(await getSavedSearches(user.id)); } catch {}
  };

  useEffect(() => { load(); }, []);

  const saveNew = async (key: string, name: string, criteria: SearchCriteria) => {
    if (!user) return;
    setSaving(key);
    try {
      await createSavedSearch(user.id, name.trim() || "Untitled", criteria);
      await load();
    } finally {
      setSaving(null);
    }
  };

  const doUpdate = async (key: string, search: SavedSearch, name: string, criteria: SearchCriteria) => {
    if (!user) return;
    setSaving(key);
    try {
      const updated = await updateSavedSearch(user.id, search.id, name.trim() || search.name, criteria);
      setSearches((prev) => prev.map((s) => (s.id === search.id ? updated : s)));
    } finally {
      setSaving(null);
    }
  };

  const del = async (searchId: number) => {
    if (!user) return;
    await deleteSavedSearch(user.id, searchId);
    setSearches((s) => s.filter((x) => x.id !== searchId));
  };

  const delAll = async () => {
    if (!user || !confirm("Delete all saved searches?")) return;
    setDeleting(true);
    try {
      await deleteAllSavedSearches(user.id);
      setSearches([]);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="p-4 md:p-8 space-y-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl md:text-2xl font-bold text-slate-900">Searches</h1>
          <p className="text-sm text-slate-500 mt-1">
            Click <strong>▶ Run</strong> to search current listings · click the name to edit filters
          </p>
        </div>
        <div className="flex gap-2">
          {searches.length > 0 && (
            <button
              onClick={delAll}
              disabled={deleting}
              className="px-3 py-2 text-sm text-red-500 hover:text-red-700 border border-red-200 rounded-lg hover:bg-red-50 disabled:opacity-40 transition-colors"
            >
              {deleting ? "Deleting…" : "Clear saved"}
            </button>
          )}
          <NewSearchButton onCreated={load} />
        </div>
      </div>

      {/* Default searches */}
      <div className="space-y-2">
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Default Searches</h2>
        {DEFAULT_SEARCHES.map((s, i) => {
          const key = `default-${i}`;
          return (
            <SearchCard
              key={key}
              
              name={s.name}
              criteria={s.criteria}
              isDefault
              saving={saving === key}
              onSaveNew={(name, c) => saveNew(key, name, c)}
            />
          );
        })}
      </div>

      {/* My saved searches */}
      <div className="space-y-2">
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">My Searches</h2>
        {searches.length === 0 ? (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-8 text-center text-slate-400 text-sm">
            No saved searches yet — edit a default above and click "Save as new".
          </div>
        ) : (
          searches.map((s) => {
            const key = `saved-${s.id}`;
            return (
              <SearchCard
                key={key}
                
                name={s.name}
                criteria={s.criteria}
                saving={saving === key}
                onSaveNew={(name, c) => saveNew(key, name, c)}
                onUpdate={(name, c) => doUpdate(key, s, name, c)}
                onDelete={() => del(s.id)}
              />
            );
          })
        )}
      </div>
    </div>
  );
}

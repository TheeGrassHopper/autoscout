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
  executeSavedSearch,
  getSavedSearches,
  previewSearch,
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

// ── Criteria edit form (inline, shared by all card types) ─────────────────────

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

  const field = (label: string, node: React.ReactNode) => (
    <div className="space-y-1">
      <label className="text-[11px] font-medium text-slate-400 uppercase tracking-wide">{label}</label>
      {node}
    </div>
  );

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
      {/* Name */}
      <div className="space-y-1">
        <label className="text-[11px] font-medium text-slate-400 uppercase tracking-wide">Search name</label>
        <input
          className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-slate-300"
          value={editName}
          onChange={(e) => setEditName(e.target.value)}
        />
      </div>

      {/* Query */}
      {field("Keyword / query", inp("e.g. tacoma", c.query, (v) => setC((x) => ({ ...x, query: v }))))}

      {/* Make + Model */}
      <div className="grid grid-cols-2 gap-3">
        {field("Make", inp("Toyota", c.make, (v) => setC((x) => ({ ...x, make: v || null }))))}
        {field("Model", inp("Tacoma", c.model, (v) => setC((x) => ({ ...x, model: v || null }))))}
      </div>

      {/* Year */}
      <div className="grid grid-cols-2 gap-3">
        {field("Min year", inp("2015", c.min_year, (v) => setC((x) => ({ ...x, min_year: v ? +v : null })), "number"))}
        {field("Max year", inp("2024", c.max_year, (v) => setC((x) => ({ ...x, max_year: v ? +v : null })), "number"))}
      </div>

      {/* Price + Mileage */}
      <div className="grid grid-cols-2 gap-3">
        {field("Max price", inp("30000", c.max_price, (v) => setC((x) => ({ ...x, max_price: v ? +v : null })), "number"))}
        {field("Max mileage", inp("120000", c.max_mileage, (v) => setC((x) => ({ ...x, max_mileage: v ? +v : null })), "number"))}
      </div>

      {/* Actions */}
      <div className="flex flex-wrap gap-2 pt-1">
        <button
          onClick={() => onRun(c)}
          disabled={running}
          className="px-3 py-1.5 bg-slate-900 text-white text-xs font-medium rounded-lg hover:bg-slate-700 disabled:opacity-40 transition-colors"
        >
          {running ? "Running…" : "▶ Run"}
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
            onClick={() => setC({ ...criteria })}
            className="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-600 transition-colors"
          >
            Reset
          </button>
        )}

        <button
          onClick={onCancel}
          className="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-600 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// ── Search card ───────────────────────────────────────────────────────────────

function SearchCard({
  name,
  criteria,
  isDefault,
  running,
  saving,
  onRun,
  onSaveNew,
  onUpdate,
  onDelete,
}: {
  name: string;
  criteria: SearchCriteria;
  isDefault?: boolean;
  running: boolean;
  saving: boolean;
  onRun: (c: SearchCriteria) => void;
  onSaveNew: (name: string, c: SearchCriteria) => void;
  onUpdate?: (name: string, c: SearchCriteria) => void;
  onDelete?: () => void;
}) {
  const [editing, setEditing] = useState(false);

  return (
    <div
      className={`bg-white rounded-xl shadow-sm border p-4 transition-colors ${
        editing ? "border-slate-300" : "border-gray-100 hover:border-slate-200"
      }`}
    >
      {/* Header row — click anywhere on the left side to toggle edit */}
      <div className="flex flex-wrap items-start gap-3">
        <button
          className="flex-1 min-w-0 text-left"
          onClick={() => setEditing((v) => !v)}
        >
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-900 text-sm">{name}</span>
            {isDefault && (
              <span className="text-[10px] font-medium px-1.5 py-0.5 bg-slate-100 text-slate-400 rounded">
                default
              </span>
            )}
            <span className="text-[11px] text-slate-400 ml-auto">
              {editing ? "▲" : "▼"}
            </span>
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
              <span className="text-xs text-slate-500">
                {criteria.min_year}–{criteria.max_year ?? "now"}
              </span>
            )}
            {criteria.max_price && (
              <span className="text-xs text-slate-500">≤ {fmt(criteria.max_price)}</span>
            )}
            {criteria.max_mileage && (
              <span className="text-xs text-slate-500">≤ {fmtMi(criteria.max_mileage)}</span>
            )}
          </div>
        </button>

        {/* Quick-run button (always visible) */}
        <div className="flex gap-2 flex-shrink-0">
          <button
            onClick={(e) => { e.stopPropagation(); onRun(criteria); }}
            disabled={running}
            className="px-3 py-1.5 bg-slate-900 text-white text-xs font-medium rounded-lg hover:bg-slate-700 disabled:opacity-40 transition-colors"
          >
            {running ? "Running…" : "▶ Run"}
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

      {/* Inline edit form */}
      {editing && (
        <CriteriaForm
          name={name}
          criteria={criteria}
          isDefault={isDefault}
          running={running}
          saving={saving}
          onRun={(c) => { onRun(c); setEditing(false); }}
          onSaveNew={(n, c) => { onSaveNew(n, c); setEditing(false); }}
          onUpdate={onUpdate ? (n, c) => { onUpdate(n, c); setEditing(false); } : undefined}
          onCancel={() => setEditing(false)}
        />
      )}
    </div>
  );
}

// ── Search Results ────────────────────────────────────────────────────────────

function SearchResultsPanel({ results, onClose }: { results: Deal[]; onClose: () => void }) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-900">{results.length} matching listings</h3>
        <button onClick={onClose} className="text-xs text-slate-400 hover:text-slate-700">
          Close ✕
        </button>
      </div>

      {results.length === 0 ? (
        <div className="p-8 text-center text-slate-400 text-sm">No listings matched this search.</div>
      ) : (
        <div className="divide-y divide-gray-50">
          {results.map((d) => (
            <div key={d.listing_id} className="px-5 py-3 flex items-start justify-between gap-4">
              <div className="min-w-0">
                <a
                  href={d.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm font-medium text-slate-900 hover:text-blue-600 line-clamp-1"
                >
                  {d.title}
                </a>
                <div className="text-xs text-slate-400 mt-0.5">{d.location}</div>
              </div>
              <div className="text-right flex-shrink-0">
                <div className="text-sm font-semibold text-slate-900">{fmt(d.asking_price)}</div>
                <div className="text-xs text-slate-400">{fmtMi(d.mileage)}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SearchesPage() {
  const [searches, setSearches] = useState<SavedSearch[]>([]);
  const [results, setResults] = useState<{ key: string; deals: Deal[] } | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const user = getUser();

  const load = async () => {
    if (!user) return;
    try { setSearches(await getSavedSearches(user.id)); } catch {}
  };

  useEffect(() => { load(); }, []);

  // ── Run ──────────────────────────────────────────────────────────────────

  const runWith = async (key: string, criteria: SearchCriteria) => {
    if (!user) return;
    setRunning(key);
    setRunError(null);
    try {
      const { results: deals } = await previewSearch(user.id, criteria);
      setResults({ key, deals });
    } catch (err: unknown) {
      setRunError(err instanceof Error ? err.message : "Failed to run search");
    } finally {
      setRunning(null);
    }
  };

  const runSaved = async (key: string, search: SavedSearch, criteria: SearchCriteria) => {
    if (!user) return;
    setRunning(key);
    setRunError(null);
    try {
      // If criteria matches the saved search exactly, use the persisted execute; otherwise preview
      const { results: deals } = await previewSearch(user.id, criteria);
      setResults({ key, deals });
    } catch (err: unknown) {
      setRunError(err instanceof Error ? err.message : "Failed to run search");
    } finally {
      setRunning(null);
    }
  };

  // ── Save ─────────────────────────────────────────────────────────────────

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

  const updateSearch = async (key: string, search: SavedSearch, name: string, criteria: SearchCriteria) => {
    if (!user) return;
    setSaving(key);
    try {
      const updated = await updateSavedSearch(user.id, search.id, name.trim() || search.name, criteria);
      setSearches((prev) => prev.map((s) => (s.id === search.id ? updated : s)));
    } finally {
      setSaving(null);
    }
  };

  // ── Delete ───────────────────────────────────────────────────────────────

  const del = async (searchId: number) => {
    if (!user) return;
    await deleteSavedSearch(user.id, searchId);
    setSearches((s) => s.filter((x) => x.id !== searchId));
    if (results?.key === `saved-${searchId}`) setResults(null);
  };

  const delAll = async () => {
    if (!user || !confirm("Delete all saved searches? Your favorites will not be affected.")) return;
    setDeleting(true);
    try {
      await deleteAllSavedSearches(user.id);
      setSearches([]);
      setResults(null);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="p-4 md:p-8 space-y-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl md:text-2xl font-bold text-slate-900">Searches</h1>
          <p className="text-sm text-slate-500 mt-1">Click a search to edit filters, then run or save</p>
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
          <button
            onClick={() => {
              // open the New Search form by triggering the first default card in edit mode —
              // actually just use CreateSearchForm inline
              const el = document.getElementById("new-search-btn");
              el?.click();
            }}
            id="new-search-btn-proxy"
            style={{ display: "none" }}
          />
          <NewSearchButton onCreated={load} />
        </div>
      </div>

      {runError && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3">
          {runError}
        </div>
      )}

      {results && (
        <SearchResultsPanel
          results={results.deals}
          onClose={() => { setResults(null); setRunError(null); }}
        />
      )}

      {/* Default searches */}
      <div className="space-y-3">
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Default Searches</h2>
        <div className="space-y-2">
          {DEFAULT_SEARCHES.map((s, i) => {
            const key = `default-${i}`;
            return (
              <SearchCard
                key={key}
                name={s.name}
                criteria={s.criteria}
                isDefault
                running={running === key}
                saving={saving === key}
                onRun={(c) => runWith(key, c)}
                onSaveNew={(name, c) => saveNew(key, name, c)}
              />
            );
          })}
        </div>
      </div>

      {/* Saved searches */}
      <div className="space-y-3">
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">My Searches</h2>
        {searches.length === 0 ? (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-8 text-center text-slate-400 text-sm">
            No saved searches yet — edit a default above and click "Save as new".
          </div>
        ) : (
          <div className="space-y-2">
            {searches.map((s) => {
              const key = `saved-${s.id}`;
              return (
                <SearchCard
                  key={key}
                  name={s.name}
                  criteria={s.criteria}
                  running={running === key}
                  saving={saving === key}
                  onRun={(c) => runSaved(key, s, c)}
                  onSaveNew={(name, c) => saveNew(key, name, c)}
                  onUpdate={(name, c) => updateSearch(key, s, name, c)}
                  onDelete={() => del(s.id)}
                />
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ── New search button / form ──────────────────────────────────────────────────

function NewSearchButton({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [criteria, setCriteria] = useState<SearchCriteria>({ query: "", zip_code: "85001", radius_miles: 500 });
  const [saving, setSaving] = useState(false);
  const user = getUser();

  const save = async () => {
    if (!name.trim() || !user) return;
    setSaving(true);
    try {
      await createSavedSearch(user.id, name.trim(), criteria);
      setName("");
      setCriteria({ query: "", zip_code: "85001", radius_miles: 500 });
      setOpen(false);
      onCreated();
    } finally {
      setSaving(false);
    }
  };

  if (!open) {
    return (
      <button
        id="new-search-btn"
        onClick={() => setOpen(true)}
        className="px-4 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-700 transition-colors"
      >
        + New Search
      </button>
    );
  }

  return (
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
          {[
            ["Make", "make", "Toyota", "text"],
            ["Model", "model", "Tacoma", "text"],
            ["Min year", "min_year", "2015", "number"],
            ["Max year", "max_year", "2024", "number"],
            ["Max price", "max_price", "30000", "number"],
            ["Max mileage", "max_mileage", "120000", "number"],
          ].map(([label, key, placeholder, type]) => (
            <div key={key} className="space-y-1">
              <label className="text-xs text-slate-500">{label}</label>
              <input
                type={type as string}
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300"
                placeholder={placeholder as string}
                value={(criteria as Record<string, unknown>)[key as string] as string ?? ""}
                onChange={(e) =>
                  setCriteria((c) => ({
                    ...c,
                    [key as string]: e.target.value
                      ? type === "number" ? +e.target.value : e.target.value
                      : null,
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
  );
}

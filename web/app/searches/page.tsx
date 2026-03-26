"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getUser } from "@/lib/auth";
import {
  type Deal,
  type SavedSearch,
  type SearchCriteria,
  createSavedSearch,
  deleteSavedSearch,
  deleteAllSavedSearches,
  executeSavedSearch,
  getSavedSearches,
} from "@/lib/api";

function fmt(n?: number | null) {
  if (n == null) return "—";
  return `$${n.toLocaleString()}`;
}

function fmtMi(n?: number | null) {
  if (n == null) return "—";
  return `${n.toLocaleString()} mi`;
}

// ── Create Search Form ────────────────────────────────────────────────────────

function CreateSearchForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [criteria, setCriteria] = useState<SearchCriteria>({
    query: "",
    zip_code: "85001",
    radius_miles: 500,
  });
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
        onClick={() => setOpen(true)}
        className="px-4 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-700 transition-colors"
      >
        + New Search
      </button>
    );
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 space-y-4">
      <h3 className="text-sm font-semibold text-slate-900">New Saved Search</h3>

      <div className="space-y-1">
        <label className="text-xs text-slate-500">Search name</label>
        <input
          autoFocus
          className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300"
          placeholder='e.g. "Tacoma under $30k"'
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className="text-xs text-slate-500">Make</label>
          <input
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300"
            placeholder="Toyota"
            value={criteria.make ?? ""}
            onChange={(e) => setCriteria((c) => ({ ...c, make: e.target.value || null }))}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-slate-500">Model</label>
          <input
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300"
            placeholder="Tacoma"
            value={criteria.model ?? ""}
            onChange={(e) => setCriteria((c) => ({ ...c, model: e.target.value || null }))}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-slate-500">Min year</label>
          <input
            type="number"
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300"
            placeholder="2015"
            value={criteria.min_year ?? ""}
            onChange={(e) => setCriteria((c) => ({ ...c, min_year: e.target.value ? +e.target.value : null }))}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-slate-500">Max year</label>
          <input
            type="number"
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300"
            placeholder="2024"
            value={criteria.max_year ?? ""}
            onChange={(e) => setCriteria((c) => ({ ...c, max_year: e.target.value ? +e.target.value : null }))}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-slate-500">Max price</label>
          <input
            type="number"
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300"
            placeholder="30000"
            value={criteria.max_price ?? ""}
            onChange={(e) => setCriteria((c) => ({ ...c, max_price: e.target.value ? +e.target.value : null }))}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-slate-500">Max mileage</label>
          <input
            type="number"
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300"
            placeholder="100000"
            value={criteria.max_mileage ?? ""}
            onChange={(e) => setCriteria((c) => ({ ...c, max_mileage: e.target.value ? +e.target.value : null }))}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className="text-xs text-slate-500">ZIP code</label>
          <input
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300 font-mono"
            placeholder="85001"
            value={criteria.zip_code}
            onChange={(e) => setCriteria((c) => ({ ...c, zip_code: e.target.value }))}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-slate-500">Radius (mi)</label>
          <input
            type="number"
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300 font-mono"
            value={criteria.radius_miles}
            onChange={(e) => setCriteria((c) => ({ ...c, radius_miles: +e.target.value }))}
          />
        </div>
      </div>

      <div className="flex gap-2 justify-end">
        <button
          onClick={() => setOpen(false)}
          className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700 transition-colors"
        >
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
  const [results, setResults] = useState<{ searchId: number; deals: Deal[] } | null>(null);
  const [running, setRunning] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const user = getUser();

  const load = async () => {
    if (!user) return;
    try {
      setSearches(await getSavedSearches(user.id));
    } catch {}
  };

  useEffect(() => { load(); }, []);

  const run = async (search: SavedSearch) => {
    if (!user) return;
    setRunning(search.id);
    setRunError(null);
    try {
      const { results: deals } = await executeSavedSearch(user.id, search.id);
      setResults({ searchId: search.id, deals });
    } catch (err: unknown) {
      setRunError(err instanceof Error ? err.message : "Failed to run search");
    } finally {
      setRunning(null);
    }
  };

  const del = async (searchId: number) => {
    if (!user) return;
    await deleteSavedSearch(user.id, searchId);
    setSearches((s) => s.filter((x) => x.id !== searchId));
    if (results?.searchId === searchId) setResults(null);
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
    <div className="p-4 md:p-8 space-y-4 md:space-y-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl md:text-2xl font-bold text-slate-900">Saved Searches</h1>
          <p className="text-sm text-slate-500 mt-1">Run any search again with one click</p>
        </div>
        <div className="flex gap-2">
          {searches.length > 0 && (
            <button
              onClick={delAll}
              disabled={deleting}
              className="px-3 py-2 text-sm text-red-500 hover:text-red-700 border border-red-200 rounded-lg hover:bg-red-50 disabled:opacity-40 transition-colors"
            >
              {deleting ? "Deleting…" : "Clear all"}
            </button>
          )}
          <CreateSearchForm onCreated={load} />
        </div>
      </div>

      {runError && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3">
          {runError}
        </div>
      )}

      {results && (
        <SearchResultsPanel results={results.deals} onClose={() => { setResults(null); setRunError(null); }} />
      )}

      {searches.length === 0 ? (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-10 text-center text-slate-400 text-sm">
          No saved searches yet. Create one above to start filtering deals.
        </div>
      ) : (
        <div className="space-y-3">
          {searches.map((s) => (
            <div
              key={s.id}
              className="bg-white rounded-xl shadow-sm border border-gray-100 p-4 flex flex-wrap items-start gap-3"
            >
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-slate-900 text-sm">{s.name}</div>
                <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1">
                  {s.criteria.make && (
                    <span className="text-xs text-slate-500">{s.criteria.make} {s.criteria.model}</span>
                  )}
                  {s.criteria.min_year && (
                    <span className="text-xs text-slate-500">{s.criteria.min_year}–{s.criteria.max_year ?? "now"}</span>
                  )}
                  {s.criteria.max_price && (
                    <span className="text-xs text-slate-500">≤ {fmt(s.criteria.max_price)}</span>
                  )}
                  {s.criteria.max_mileage && (
                    <span className="text-xs text-slate-500">≤ {fmtMi(s.criteria.max_mileage)}</span>
                  )}
                  {s.criteria.zip_code && (
                    <span className="text-xs text-slate-400">ZIP {s.criteria.zip_code} · {s.criteria.radius_miles} mi</span>
                  )}
                </div>
                <div className="text-xs text-slate-300 mt-1">
                  Created {new Date(s.created_at).toLocaleDateString()}
                </div>
              </div>

              <div className="flex gap-2 flex-shrink-0">
                <button
                  onClick={() => run(s)}
                  disabled={running === s.id}
                  className="px-3 py-1.5 bg-slate-900 text-white text-xs font-medium rounded-lg hover:bg-slate-700 disabled:opacity-40 transition-colors"
                >
                  {running === s.id ? "Running…" : "▶ Run"}
                </button>
                <button
                  onClick={() => del(s.id)}
                  className="px-3 py-1.5 text-xs text-red-500 hover:text-red-700 border border-red-200 rounded-lg hover:bg-red-50 transition-colors"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { type PipelineRun, type PipelineRunLogs, getRuns, getRunLogs } from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString("en-US", {
    timeZone: "America/Phoenix",
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function fmtDuration(secs: number | null) {
  if (secs == null) return "—";
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

const STATUS_STYLE: Record<string, string> = {
  completed: "bg-emerald-100 text-emerald-700",
  stopped:   "bg-amber-100 text-amber-700",
  error:     "bg-red-100 text-red-700",
  running:   "bg-blue-100 text-blue-700",
};

const STATUS_LABEL: Record<string, string> = {
  completed: "✅ Completed",
  stopped:   "⛔ Stopped",
  error:     "❌ Error",
  running:   "⏳ Running",
};

function countWarnings(log: string) {
  return (log.match(/\bWARNING\b/g) ?? []).length;
}

function countErrors(log: string) {
  return (log.match(/\bERROR\b|\b❌\b/g) ?? []).length;
}

// ── Log Line Coloriser ────────────────────────────────────────────────────────

function LogLine({ line }: { line: string }) {
  let color = "text-slate-300";
  if (/ERROR|❌/.test(line))   color = "text-red-400";
  else if (/WARNING/.test(line)) color = "text-amber-400";
  else if (/✅|complete/i.test(line)) color = "text-emerald-400";
  else if (/⛔|stopped/i.test(line))  color = "text-amber-400";
  else if (/INFO/.test(line))   color = "text-slate-300";
  return <div className={`${color} leading-relaxed whitespace-pre-wrap break-all`}>{line}</div>;
}

// ── Log Viewer Modal ──────────────────────────────────────────────────────────

function LogViewer({ run, onClose }: { run: PipelineRun; onClose: () => void }) {
  const [data, setData] = useState<PipelineRunLogs | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | "warnings" | "errors">("all");

  useEffect(() => {
    getRunLogs(run.id)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [run.id]);

  const lines = data?.log_text ? data.log_text.split("\n").filter(Boolean) : [];
  const filtered = filter === "all"
    ? lines
    : filter === "warnings"
    ? lines.filter(l => /WARNING/.test(l))
    : lines.filter(l => /ERROR|❌/.test(l));

  const warnings = lines.filter(l => /WARNING/.test(l)).length;
  const errors   = lines.filter(l => /ERROR|❌/.test(l)).length;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 overflow-y-auto">
      <div className="w-full max-w-4xl bg-slate-900 rounded-2xl border border-slate-700 shadow-2xl my-8">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <div>
            <h2 className="text-base font-semibold text-slate-100">
              Run #{run.id} — {fmtDate(run.started_at)}
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              {run.listing_count} listings · {fmtDuration(run.duration_seconds)}
              {run.query ? ` · "${run.query}"` : ""}
              {run.zip_code ? ` · ZIP ${run.zip_code}` : ""}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Filter bar */}
        <div className="flex items-center gap-2 px-6 py-3 border-b border-slate-700">
          {(["all", "warnings", "errors"] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                filter === f
                  ? "bg-slate-700 text-slate-100"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {f === "all"      ? `All (${lines.length})`      : null}
              {f === "warnings" ? `⚠️ Warnings (${warnings})`  : null}
              {f === "errors"   ? `❌ Errors (${errors})`      : null}
            </button>
          ))}
          <span className="ml-auto text-xs text-slate-500">{filtered.length} lines shown</span>
        </div>

        {/* Log body */}
        <div className="bg-slate-950 rounded-b-2xl p-5 h-[60vh] overflow-y-auto font-mono text-xs space-y-0.5">
          {loading ? (
            <div className="text-slate-500 text-center pt-10">Loading logs…</div>
          ) : filtered.length === 0 ? (
            <div className="text-slate-500 text-center pt-10">No {filter === "all" ? "log output" : filter} found</div>
          ) : (
            filtered.map((line, i) => <LogLine key={i} line={line} />)
          )}
        </div>
      </div>
    </div>
  );
}

// ── Run Row ───────────────────────────────────────────────────────────────────

function RunRow({ run, onView }: { run: PipelineRun; onView: (r: PipelineRun) => void }) {
  return (
    <tr className="hover:bg-slate-50 transition-colors cursor-pointer" onClick={() => onView(run)}>
      <td className="px-4 py-3 text-xs text-slate-400 font-mono">#{run.id}</td>
      <td className="px-4 py-3">
        <div className="text-sm font-medium text-slate-900">{fmtDate(run.started_at)}</div>
        {run.finished_at && (
          <div className="text-xs text-slate-400">{fmtDuration(run.duration_seconds)}</div>
        )}
      </td>
      <td className="px-4 py-3">
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLE[run.status] ?? "bg-slate-100 text-slate-600"}`}>
          {STATUS_LABEL[run.status] ?? run.status}
        </span>
      </td>
      <td className="px-4 py-3 text-sm text-slate-700 font-medium">{run.listing_count}</td>
      <td className="px-4 py-3">
        <div className="flex gap-2">
          <span className="text-xs font-semibold text-emerald-600">{run.great_count} great</span>
          <span className="text-xs text-amber-500">{run.fair_count} fair</span>
        </div>
      </td>
      <td className="px-4 py-3 text-xs text-slate-500">
        {run.query || <span className="italic text-slate-300">all</span>}
        {run.zip_code ? ` · ${run.zip_code}` : ""}
        {run.radius_miles ? ` +${run.radius_miles}mi` : ""}
      </td>
      <td className="px-4 py-3 text-xs">
        {run.dry_run ? (
          <span className="text-amber-500 font-medium">Dry run</span>
        ) : (
          <span className="text-slate-400">Live</span>
        )}
      </td>
      <td className="px-4 py-3">
        <button
          onClick={e => { e.stopPropagation(); onView(run); }}
          className="px-3 py-1 text-xs font-medium text-slate-600 bg-slate-100 rounded-lg hover:bg-slate-200 transition-colors"
        >
          View logs
        </button>
      </td>
    </tr>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function RunsPage() {
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<PipelineRun | null>(null);

  useEffect(() => {
    getRuns(100)
      .then(setRuns)
      .finally(() => setLoading(false));
  }, []);

  const totalListings = runs.reduce((s, r) => s + r.listing_count, 0);
  const totalGreat    = runs.reduce((s, r) => s + r.great_count, 0);
  const errorRuns     = runs.filter(r => r.status === "error").length;

  return (
    <div className="p-4 md:p-8 space-y-6 max-w-7xl mx-auto">

      {/* Header */}
      <div>
        <h1 className="text-xl md:text-2xl font-bold text-slate-900">Run History</h1>
        <p className="text-sm text-slate-500 mt-1">Pipeline execution logs — click any row to inspect output</p>
      </div>

      {/* Summary cards */}
      {!loading && runs.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: "Total Runs",      value: runs.length,    color: "border-slate-400" },
            { label: "Listings Found",  value: totalListings,  color: "border-blue-400" },
            { label: "Great Deals",     value: totalGreat,     color: "border-emerald-500" },
            { label: "Failed Runs",     value: errorRuns,      color: "border-red-400" },
          ].map(c => (
            <div key={c.label} className={`bg-white rounded-xl border-l-4 ${c.color} shadow-sm p-4`}>
              <div className="text-2xl font-bold text-slate-900">{c.value}</div>
              <div className="text-xs text-slate-500 mt-1">{c.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Table */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-slate-400">Loading run history…</div>
        ) : runs.length === 0 ? (
          <div className="p-12 text-center">
            <div className="text-4xl mb-3">📋</div>
            <div className="text-slate-600 font-medium">No runs yet</div>
            <div className="text-slate-400 text-sm mt-1">
              Run the pipeline from the Dashboard — each run will be recorded here.
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-left text-xs text-slate-500 uppercase tracking-wide border-b border-gray-100">
                  <th className="px-4 py-3 font-medium">ID</th>
                  <th className="px-4 py-3 font-medium">Started</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Listings</th>
                  <th className="px-4 py-3 font-medium">Deals</th>
                  <th className="px-4 py-3 font-medium">Query</th>
                  <th className="px-4 py-3 font-medium">Mode</th>
                  <th className="px-4 py-3 font-medium"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {runs.map(r => (
                  <RunRow key={r.id} run={r} onView={setSelected} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Log viewer modal */}
      {selected && (
        <LogViewer run={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

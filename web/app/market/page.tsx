"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { type Deal, type SearchCriteria, previewSearch } from "@/lib/api";
import { useSession } from "next-auth/react";

const DEFAULT_SEARCHES: { name: string; query: string }[] = [
  { name: "Z71",               query: "z71" },
  { name: "Denali",            query: "denali" },
  { name: "GX470",             query: "gx470" },
  { name: "Toyota Camry",      query: "camry" },
  { name: "Mercedes C300",     query: "c300" },
  { name: "Volkswagen Tiguan", query: "tiguan" },
  { name: "Ford Fusion",       query: "fusion" },
  { name: "Honda Civic",       query: "civic" },
  { name: "Chevy Silverado",   query: "silverado" },
  { name: "Mercedes CLA250",   query: "cla250" },
  { name: "BMW 428i",          query: "428i" },
  { name: "BMW 435i",          query: "435i" },
  { name: "Toyota Highlander", query: "highlander" },
  { name: "Chevy Malibu",      query: "malibu" },
  { name: "Honda Accord",      query: "accord" },
  { name: "BMW 328 Wagon",     query: "328" },
  { name: "Toyota Tacoma",     query: "tacoma" },
];

interface SearchRow {
  name: string;
  query: string;
  total: number;
  great: number;
  fair: number;
  avgDiscount: number | null;
  bestDeal: Deal | null;
}

function fmt$(n: number): string {
  return "$" + n.toLocaleString("en-US");
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + "…" : s;
}

export default function MarketPage() {
  const { data: session } = useSession();
  const [rows, setRows] = useState<SearchRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const user = session?.user ?? null;
        if (!user) {
          setError("Not logged in.");
          setLoading(false);
          return;
        }

        const results = await Promise.all(
          DEFAULT_SEARCHES.map(({ query }) =>
            previewSearch(parseInt(user.id), { query } as SearchCriteria).catch(() => ({
              count: 0,
              results: [] as Deal[],
            }))
          )
        );

        const built: SearchRow[] = DEFAULT_SEARCHES.map(({ name, query }, i) => {
          const { results: deals } = results[i];
          const total = deals.length;
          const great = deals.filter((d) => d.deal_class === "great").length;
          const fair = deals.filter((d) => d.deal_class === "fair").length;

          const withSavings = deals.filter((d) => d.savings > 0);
          const avgDiscount =
            withSavings.length > 0
              ? Math.round(
                  withSavings.reduce((sum, d) => sum + d.savings, 0) / withSavings.length
                )
              : null;

          const bestDeal =
            deals.length > 0
              ? deals.reduce((best, d) =>
                  d.total_score > best.total_score ? d : best
                )
              : null;

          return { name, query, total, great, fair, avgDiscount, bestDeal };
        });

        // Sort: most great deals first, then by total
        built.sort((a, b) => {
          if (b.great !== a.great) return b.great - a.great;
          return b.total - a.total;
        });

        setRows(built);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Failed to load market data.");
      } finally {
        setLoading(false);
      }
    }

    load();
  }, []);

  const totalListings = rows.reduce((s, r) => s + r.total, 0);

  return (
    <div className="min-h-screen bg-slate-50 p-4 md:p-8">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Market Overview</h1>
        {!loading && !error && (
          <p className="text-sm text-slate-500 mt-1">
            Showing results from your last pipeline run &middot;{" "}
            <span className="font-medium text-slate-700">
              {totalListings.toLocaleString()} total listings scanned
            </span>
          </p>
        )}
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex flex-col items-center justify-center py-24 gap-4">
          <div className="w-10 h-10 border-4 border-slate-200 border-t-blue-500 rounded-full animate-spin" />
          <p className="text-slate-500 text-sm font-medium">Scanning all searches…</p>
        </div>
      )}

      {/* Error */}
      {!loading && error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-red-700 text-sm">
          {error}
        </div>
      )}

      {/* Desktop table */}
      {!loading && !error && (
        <>
          <div className="hidden md:block bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="text-left px-5 py-3 font-semibold text-slate-600">Search</th>
                  <th className="text-right px-4 py-3 font-semibold text-slate-600">Listings</th>
                  <th className="text-right px-4 py-3 font-semibold text-slate-600">🔥 Great</th>
                  <th className="text-right px-4 py-3 font-semibold text-slate-600">⚡ Fair</th>
                  <th className="text-right px-4 py-3 font-semibold text-slate-600">Avg Discount</th>
                  <th className="px-4 py-3 font-semibold text-slate-600">Best Deal</th>
                  <th className="px-4 py-3 font-semibold text-slate-600">Action</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const isEmpty = row.total === 0;
                  const hasGreat = row.great > 0;

                  return (
                    <tr
                      key={row.name}
                      className={`border-b border-slate-100 last:border-0 transition-colors ${
                        isEmpty
                          ? "opacity-50"
                          : hasGreat
                          ? "bg-emerald-50/40 hover:bg-emerald-50/60"
                          : "hover:bg-slate-50"
                      }`}
                    >
                      {/* Search name with left border accent */}
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-2">
                          {hasGreat && (
                            <span className="w-1 h-5 rounded-full bg-emerald-500 shrink-0" />
                          )}
                          <span className="font-medium text-slate-800">{row.name}</span>
                        </div>
                      </td>

                      <td className="text-right px-4 py-3 text-slate-700 tabular-nums">
                        {isEmpty ? <span className="text-slate-400">0</span> : row.total}
                      </td>

                      <td className="text-right px-4 py-3 tabular-nums">
                        {row.great > 0 ? (
                          <span className="font-bold text-emerald-600">{row.great}</span>
                        ) : (
                          <span className="text-slate-400">0</span>
                        )}
                      </td>

                      <td className="text-right px-4 py-3 tabular-nums">
                        {row.fair > 0 ? (
                          <span className="font-medium text-amber-600">{row.fair}</span>
                        ) : (
                          <span className="text-slate-400">0</span>
                        )}
                      </td>

                      <td className="text-right px-4 py-3">
                        {row.avgDiscount !== null ? (
                          <span className="text-emerald-600 font-medium">
                            {fmt$(row.avgDiscount)} below market
                          </span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>

                      <td className="px-4 py-3 max-w-[220px]">
                        {isEmpty ? (
                          <span className="text-slate-400 text-xs italic">
                            No data — scrape first
                          </span>
                        ) : row.bestDeal ? (
                          <a
                            href={row.bestDeal.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-600 hover:text-blue-800 hover:underline"
                          >
                            <span className="font-medium">
                              {fmt$(row.bestDeal.asking_price)}
                            </span>{" "}
                            <span className="text-slate-600 text-xs">
                              {truncate(row.bestDeal.title, 30)}
                            </span>
                          </a>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>

                      <td className="px-4 py-3">
                        <Link
                          href="/searches"
                          className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-100 text-slate-700 hover:bg-slate-200 transition-colors"
                        >
                          ▶ Run
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile card list */}
          <div className="md:hidden space-y-3">
            {rows.map((row) => {
              const isEmpty = row.total === 0;
              const hasGreat = row.great > 0;

              return (
                <div
                  key={row.name}
                  className={`bg-white rounded-xl shadow-sm border overflow-hidden ${
                    hasGreat ? "border-emerald-300" : "border-slate-200"
                  } ${isEmpty ? "opacity-60" : ""}`}
                >
                  <div
                    className={`px-4 py-3 flex items-center justify-between ${
                      hasGreat ? "bg-emerald-50" : "bg-slate-50"
                    }`}
                  >
                    <span className="font-semibold text-slate-800">{row.name}</span>
                    <div className="flex items-center gap-2">
                      {hasGreat && (
                        <span className="text-xs font-bold bg-emerald-500 text-white px-2 py-0.5 rounded-full">
                          {row.great} great
                        </span>
                      )}
                      {row.fair > 0 && (
                        <span className="text-xs font-bold bg-amber-400 text-white px-2 py-0.5 rounded-full">
                          {row.fair} fair
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="px-4 py-3 space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Listings</span>
                      <span className="font-medium text-slate-800">{row.total}</span>
                    </div>

                    <div className="flex justify-between">
                      <span className="text-slate-500">Avg Discount</span>
                      <span
                        className={
                          row.avgDiscount !== null
                            ? "font-medium text-emerald-600"
                            : "text-slate-400"
                        }
                      >
                        {row.avgDiscount !== null
                          ? `${fmt$(row.avgDiscount)} below market`
                          : "—"}
                      </span>
                    </div>

                    {isEmpty ? (
                      <div className="text-slate-400 text-xs italic">
                        No data — scrape first
                      </div>
                    ) : row.bestDeal ? (
                      <div className="flex justify-between items-start gap-2">
                        <span className="text-slate-500 shrink-0">Best Deal</span>
                        <a
                          href={row.bestDeal.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:underline text-right"
                        >
                          <span className="font-medium">
                            {fmt$(row.bestDeal.asking_price)}
                          </span>{" "}
                          <span className="text-xs text-slate-600">
                            {truncate(row.bestDeal.title, 28)}
                          </span>
                        </a>
                      </div>
                    ) : null}

                    <div className="pt-1">
                      <Link
                        href="/searches"
                        className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-100 text-slate-700 hover:bg-slate-200 transition-colors"
                      >
                        ▶ Run
                      </Link>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

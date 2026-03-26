"use client";

import { useEffect, useState } from "react";
import { type UserProfile, type SavedSearch, type Deal, adminGetUsers, adminUpdateUser, adminDeleteUser, adminGetUserSearches, adminGetUserFavorites } from "@/lib/api";
import { getUser } from "@/lib/auth";

function fmt(n?: number | null) {
  return n == null ? "—" : `$${n.toLocaleString()}`;
}

export default function AdminPage() {
  const currentUser = getUser();
  const [users, setUsers] = useState<UserProfile[]>([]);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [expandedData, setExpandedData] = useState<{ searches: SavedSearch[]; favorites: Deal[] } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (currentUser?.role !== "admin") return;
    adminGetUsers()
      .then(setUsers)
      .catch(() => setError("Failed to load users"));
  }, []);

  if (currentUser?.role !== "admin") {
    return (
      <div className="p-8 text-center">
        <div className="text-slate-400 text-sm">403 — Admin access required</div>
      </div>
    );
  }

  const expand = async (userId: number) => {
    if (expanded === userId) {
      setExpanded(null);
      setExpandedData(null);
      return;
    }
    setExpanded(userId);
    setExpandedData(null);
    const [searches, favorites] = await Promise.all([
      adminGetUserSearches(userId),
      adminGetUserFavorites(userId),
    ]);
    setExpandedData({ searches, favorites });
  };

  const toggleRole = async (user: UserProfile) => {
    const newRole = user.role === "admin" ? "user" : "admin";
    if (!confirm(`Change ${user.email} to ${newRole}?`)) return;
    const updated = await adminUpdateUser(user.id, { role: newRole });
    setUsers((u) => u.map((x) => (x.id === user.id ? updated : x)));
  };

  const deleteUser = async (user: UserProfile) => {
    if (!confirm(`Delete ${user.email} and all their data? This cannot be undone.`)) return;
    await adminDeleteUser(user.id);
    setUsers((u) => u.filter((x) => x.id !== user.id));
    if (expanded === user.id) { setExpanded(null); setExpandedData(null); }
  };

  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl md:text-2xl font-bold text-slate-900">Admin</h1>
        <p className="text-sm text-slate-500 mt-1">{users.length} registered users</p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3">{error}</div>
      )}

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <div className="hidden md:grid grid-cols-[1fr_100px_120px_80px_80px] gap-4 px-5 py-3 bg-gray-50 text-xs font-medium text-slate-500 uppercase tracking-wide border-b border-gray-100">
          <span>Email</span>
          <span>Role</span>
          <span>Member since</span>
          <span>Notify</span>
          <span></span>
        </div>

        <div className="divide-y divide-gray-50">
          {users.map((u) => (
            <div key={u.id}>
              <div
                className="grid md:grid-cols-[1fr_100px_120px_80px_80px] gap-4 px-5 py-3 items-center cursor-pointer hover:bg-gray-50 transition-colors"
                onClick={() => expand(u.id)}
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium text-slate-800 truncate">{u.email}</div>
                  <div className="text-xs text-slate-400 md:hidden">ID {u.id} · {new Date(u.created_at).toLocaleDateString()}</div>
                </div>
                <div className="hidden md:flex">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${u.role === "admin" ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600"}`}>
                    {u.role}
                  </span>
                </div>
                <div className="hidden md:block text-sm text-slate-500">{new Date(u.created_at).toLocaleDateString()}</div>
                <div className="hidden md:block text-sm text-slate-500">{u.notify_carvana ? "✓" : "—"}</div>
                <div className="flex gap-2 justify-end" onClick={(e) => e.stopPropagation()}>
                  <button
                    onClick={() => toggleRole(u)}
                    className="text-xs px-2 py-1 rounded border border-slate-200 hover:bg-slate-50 text-slate-600 transition-colors"
                    title={u.role === "admin" ? "Demote to user" : "Promote to admin"}
                  >
                    {u.role === "admin" ? "Demote" : "Promote"}
                  </button>
                  {u.id !== currentUser?.id && (
                    <button
                      onClick={() => deleteUser(u)}
                      className="text-xs px-2 py-1 rounded border border-red-200 hover:bg-red-50 text-red-500 transition-colors"
                    >
                      Delete
                    </button>
                  )}
                </div>
              </div>

              {expanded === u.id && (
                <div className="px-5 pb-4 bg-gray-50 border-t border-gray-100 space-y-3">
                  {!expandedData ? (
                    <div className="text-xs text-slate-400 py-2">Loading…</div>
                  ) : (
                    <>
                      <div>
                        <div className="text-xs font-semibold text-slate-500 mb-1">
                          Saved searches ({expandedData.searches.length})
                        </div>
                        {expandedData.searches.length === 0 ? (
                          <div className="text-xs text-slate-400">None</div>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {expandedData.searches.map((s) => (
                              <span key={s.id} className="text-xs bg-white border border-gray-200 rounded px-2 py-0.5 text-slate-600">
                                {s.name}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                      <div>
                        <div className="text-xs font-semibold text-slate-500 mb-1">
                          Favorites ({expandedData.favorites.length})
                        </div>
                        {expandedData.favorites.length === 0 ? (
                          <div className="text-xs text-slate-400">None</div>
                        ) : (
                          <div className="space-y-1">
                            {expandedData.favorites.slice(0, 5).map((f) => (
                              <div key={f.listing_id} className="text-xs text-slate-600 flex justify-between">
                                <span className="truncate max-w-xs">{f.title}</span>
                                <span className="text-slate-400 flex-shrink-0 ml-2">{fmt(f.asking_price)}</span>
                              </div>
                            ))}
                            {expandedData.favorites.length > 5 && (
                              <div className="text-xs text-slate-400">+{expandedData.favorites.length - 5} more</div>
                            )}
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

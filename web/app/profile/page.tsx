"use client";

import { useEffect, useState } from "react";
import { type UserProfile, getUserProfile, updateUserProfile } from "@/lib/api";
import { getUser, saveAuth, getToken } from "@/lib/auth";

export default function ProfilePage() {
  const currentUser = getUser();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [email, setEmail] = useState("");
  const [notifyCarvana, setNotifyCarvana] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!currentUser) return;
    getUserProfile(currentUser.id)
      .then((p) => {
        setProfile(p);
        setEmail(p.email);
        setNotifyCarvana(p.notify_carvana);
      })
      .catch(() => setError("Failed to load profile"));
  }, []);

  const save = async () => {
    if (!currentUser || !profile) return;
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      const updated = await updateUserProfile(currentUser.id, {
        email: email !== profile.email ? email : undefined,
        notify_carvana: notifyCarvana !== profile.notify_carvana ? notifyCarvana : undefined,
      });
      setProfile(updated);
      // Sync localStorage if email changed
      if (updated.email !== currentUser.email) {
        const token = getToken();
        if (token) saveAuth(token, { ...currentUser, email: updated.email });
      }
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-4 md:p-8 max-w-lg mx-auto space-y-6">
      <div>
        <h1 className="text-xl md:text-2xl font-bold text-slate-900">Profile</h1>
        <p className="text-sm text-slate-500 mt-1">Manage your account settings</p>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 space-y-5">
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-3 py-2">{error}</div>
        )}
        {saved && (
          <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 text-sm rounded-lg px-3 py-2">Profile saved</div>
        )}

        <div className="space-y-1">
          <label className="text-xs font-medium text-slate-600">Email address</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-slate-300"
          />
        </div>

        <div className="flex items-center justify-between py-2 border-t border-gray-50">
          <div>
            <div className="text-sm font-medium text-slate-700">Carvana offer notifications</div>
            <div className="text-xs text-slate-400 mt-0.5">Get emailed when a Carvana offer job completes</div>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={notifyCarvana}
              onChange={(e) => setNotifyCarvana(e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-gray-200 peer-focus:ring-2 peer-focus:ring-slate-300 rounded-full peer peer-checked:bg-slate-900 after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:after:translate-x-5" />
          </label>
        </div>

        <button
          onClick={save}
          disabled={saving}
          className="w-full py-2.5 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-700 disabled:opacity-50 transition-colors"
        >
          {saving ? "Saving…" : "Save changes"}
        </button>
      </div>

      {profile && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 space-y-2">
          <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Account info</h3>
          <div className="flex justify-between text-sm">
            <span className="text-slate-500">User ID</span>
            <span className="font-mono text-slate-700">{profile.id}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-slate-500">Role</span>
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${profile.role === "admin" ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600"}`}>
              {profile.role}
            </span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-slate-500">Member since</span>
            <span className="text-slate-700">{new Date(profile.created_at).toLocaleDateString()}</span>
          </div>
        </div>
      )}
    </div>
  );
}

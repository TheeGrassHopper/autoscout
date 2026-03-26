const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "";

function authHeaders(): HeadersInit {
  return API_KEY ? { "X-API-Key": API_KEY } : {};
}

export type DealClass = "great" | "fair" | "poor";

export interface Deal {
  saved_at?: string;
  listing_id: string;
  source: string;
  title: string;
  url: string;
  asking_price: number;
  kbb_value: number;
  carvana_value: number | null;
  carmax_value: number | null;
  local_market_value: number | null;
  blended_market_value: number | null;
  profit_estimate: number | null;
  profit_margin_pct: number | null;
  demand_score: number | null;
  savings: number;
  total_score: number;
  deal_class: DealClass;
  make: string;
  model: string;
  year: number;
  mileage: number;
  location: string;
  vin: string | null;
  title_status: string | null;
  posted_date: string | null;
  first_seen: string;
  last_seen: string;
  image_urls: string[];
}

export interface Stats {
  total_listings: number;
  great_deals: number;
  fair_deals: number;
  poor_deals: number;
  messages_queued: number;
  messages_approved: number;
}

export interface QueuedMessage {
  id: number;
  listing_id: string;
  message_text: string;
  drafted_at: string;
  status: string;
  title: string;
  url: string;
  asking_price: number;
  kbb_value: number;
  savings: number;
  total_score: number;
  deal_class: DealClass;
  make: string;
  model: string;
  year: number;
  mileage: number;
  location: string;
}

export interface PipelineStatus {
  running: boolean;
  last_run: string | null;
  last_count: number;
  start_time: string | null;
  elapsed_seconds: number | null;
  stop_requested: boolean;
}

export async function stopPipeline(): Promise<void> {
  await fetch(`${BASE}/api/pipeline/stop`, { method: "POST", headers: authHeaders() });
}

export async function getStats(): Promise<Stats> {
  const res = await fetch(`${BASE}/api/stats`, { cache: "no-store", headers: authHeaders() });
  return res.json();
}

export async function getDeals(dealClass?: string): Promise<Deal[]> {
  const params = dealClass ? `?deal_class=${dealClass}` : "";
  const res = await fetch(`${BASE}/api/deals${params}`, { cache: "no-store", headers: authHeaders() });
  return res.json();
}

export async function getMessageQueue(): Promise<QueuedMessage[]> {
  const res = await fetch(`${BASE}/api/messages/queue`, { cache: "no-store", headers: authHeaders() });
  return res.json();
}

export async function approveMessage(id: number): Promise<void> {
  await fetch(`${BASE}/api/messages/${id}/approve`, { method: "POST", headers: authHeaders() });
}

export async function skipMessage(id: number): Promise<void> {
  await fetch(`${BASE}/api/messages/${id}/skip`, { method: "POST", headers: authHeaders() });
}

export async function getPipelineStatus(): Promise<PipelineStatus> {
  const res = await fetch(`${BASE}/api/pipeline/status`, { cache: "no-store", headers: authHeaders() });
  return res.json();
}

export async function getFavorites(): Promise<Deal[]> {
  const res = await fetch(`${BASE}/api/favorites`, { cache: "no-store", headers: authHeaders() });
  return res.json();
}

export async function saveFavorite(listingId: string): Promise<void> {
  await fetch(`${BASE}/api/favorites/${listingId}`, { method: "POST", headers: authHeaders() });
}

export async function removeFavorite(listingId: string): Promise<void> {
  await fetch(`${BASE}/api/favorites/${listingId}`, { method: "DELETE", headers: authHeaders() });
}

export async function resetDatabase(): Promise<void> {
  await fetch(`${BASE}/api/database`, { method: "DELETE", headers: authHeaders() });
}

export interface CarvanaOfferStatus {
  status: "not_started" | "running" | "completed" | "error";
  offer: string | null;
  error: string | null;
  steps: string[];
}

export async function startCarvanaOffer(listingId: string, vin?: string): Promise<void> {
  const params = vin ? `?vin=${encodeURIComponent(vin)}` : "";
  await fetch(`${BASE}/api/deals/${listingId}/carvana-offer${params}`, { method: "POST", headers: authHeaders() });
}

export async function getCarvanaOfferStatus(listingId: string): Promise<CarvanaOfferStatus> {
  const res = await fetch(`${BASE}/api/deals/${listingId}/carvana-offer`, { cache: "no-store", headers: authHeaders() });
  return res.json();
}

export async function runPipeline(query = "", dryRun = true, zipCode = "", radiusMiles = 0, includeFacebook = true): Promise<void> {
  const params = new URLSearchParams({ query, dry_run: String(dryRun), include_facebook: String(includeFacebook) });
  if (zipCode) params.set("zip_code", zipCode);
  if (radiusMiles) params.set("radius_miles", String(radiusMiles));
  await fetch(`${BASE}/api/pipeline/run?${params}`, { method: "POST", headers: authHeaders() });
}

// ── User portal ───────────────────────────────────────────────────────────────

import { getToken, type AuthUser } from "@/lib/auth";
export type { AuthUser };

function userHeaders(): HeadersInit {
  const h: Record<string, string> = { ...(authHeaders() as Record<string, string>) };
  const token = getToken();
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

export async function apiRegister(email: string, password: string): Promise<{ token: string; user: AuthUser }> {
  const res = await fetch(`${BASE}/auth/register`, {
    method: "POST",
    headers: { ...authHeaders() as Record<string, string>, "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error((await res.json()).detail ?? "Registration failed");
  return res.json();
}

export async function apiLogin(email: string, password: string): Promise<{ token: string; user: AuthUser }> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    headers: { ...authHeaders() as Record<string, string>, "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error((await res.json()).detail ?? "Login failed");
  return res.json();
}

export interface SearchCriteria {
  query?: string;
  zip_code?: string;
  radius_miles?: number;
  min_year?: number | null;
  max_year?: number | null;
  min_price?: number | null;
  max_price?: number | null;
  max_mileage?: number | null;
  make?: string | null;
  model?: string | null;
}

export interface SavedSearch {
  id: number;
  user_id: number;
  name: string;
  criteria: SearchCriteria;
  created_at: string;
  updated_at: string;
}

export async function getSavedSearches(userId: number): Promise<SavedSearch[]> {
  const res = await fetch(`${BASE}/users/${userId}/searches`, { cache: "no-store", headers: userHeaders() });
  if (!res.ok) throw new Error("Failed to load searches");
  return res.json();
}

export async function createSavedSearch(userId: number, name: string, criteria: SearchCriteria): Promise<SavedSearch> {
  const res = await fetch(`${BASE}/users/${userId}/searches`, {
    method: "POST",
    headers: { ...userHeaders() as Record<string, string>, "Content-Type": "application/json" },
    body: JSON.stringify({ name, criteria }),
  });
  if (!res.ok) throw new Error("Failed to create search");
  return res.json();
}

export async function executeSavedSearch(userId: number, searchId: number): Promise<{ count: number; results: Deal[] }> {
  const res = await fetch(`${BASE}/users/${userId}/searches/${searchId}/execute`, {
    method: "POST",
    headers: userHeaders(),
  });
  if (!res.ok) throw new Error("Failed to execute search");
  return res.json();
}

export async function deleteSavedSearch(userId: number, searchId: number): Promise<void> {
  await fetch(`${BASE}/users/${userId}/searches/${searchId}`, { method: "DELETE", headers: userHeaders() });
}

export async function deleteAllSavedSearches(userId: number): Promise<{ deleted: number }> {
  const res = await fetch(`${BASE}/users/${userId}/searches`, { method: "DELETE", headers: userHeaders() });
  return res.json();
}

export async function getUserFavorites(userId: number): Promise<Deal[]> {
  const res = await fetch(`${BASE}/users/${userId}/favorites`, { cache: "no-store", headers: userHeaders() });
  if (!res.ok) throw new Error("Failed to load favorites");
  return res.json();
}

export async function addUserFavorite(userId: number, deal: Deal): Promise<void> {
  await fetch(`${BASE}/users/${userId}/favorites`, {
    method: "POST",
    headers: { ...userHeaders() as Record<string, string>, "Content-Type": "application/json" },
    body: JSON.stringify({ listing_data: deal }),
  });
}

export async function removeUserFavorite(userId: number, listingId: string): Promise<void> {
  await fetch(`${BASE}/users/${userId}/favorites/${listingId}`, { method: "DELETE", headers: userHeaders() });
}

// ── User profile ──────────────────────────────────────────────────────────────

export interface UserProfile {
  id: number;
  email: string;
  role: string;
  notify_carvana: boolean;
  created_at: string;
}

export async function getUserProfile(userId: number): Promise<UserProfile> {
  const res = await fetch(`${BASE}/users/${userId}`, { cache: "no-store", headers: userHeaders() });
  if (!res.ok) throw new Error("Failed to load profile");
  return res.json();
}

export async function updateUserProfile(userId: number, data: { email?: string; notify_carvana?: boolean }): Promise<UserProfile> {
  const res = await fetch(`${BASE}/users/${userId}`, {
    method: "PATCH",
    headers: { ...userHeaders() as Record<string, string>, "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update profile");
  return res.json();
}

// ── Admin ─────────────────────────────────────────────────────────────────────

export async function adminGetUsers(): Promise<UserProfile[]> {
  const res = await fetch(`${BASE}/admin/users`, { cache: "no-store", headers: userHeaders() });
  if (!res.ok) throw new Error("Admin access required");
  return res.json();
}

export async function adminUpdateUser(id: number, data: { role?: string; notify_carvana?: boolean; email?: string }): Promise<UserProfile> {
  const res = await fetch(`${BASE}/admin/users/${id}`, {
    method: "PATCH",
    headers: { ...userHeaders() as Record<string, string>, "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update user");
  return res.json();
}

export async function adminDeleteUser(id: number): Promise<void> {
  await fetch(`${BASE}/admin/users/${id}`, { method: "DELETE", headers: userHeaders() });
}

export async function adminGetUserSearches(id: number): Promise<SavedSearch[]> {
  const res = await fetch(`${BASE}/admin/users/${id}/searches`, { cache: "no-store", headers: userHeaders() });
  return res.json();
}

export async function adminGetUserFavorites(id: number): Promise<Deal[]> {
  const res = await fetch(`${BASE}/admin/users/${id}/favorites`, { cache: "no-store", headers: userHeaders() });
  return res.json();
}

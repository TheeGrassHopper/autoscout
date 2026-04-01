import { getSession } from "next-auth/react";
import type { AuthUser } from "@/lib/auth";
export type { AuthUser };

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "";

function authHeaders(): Record<string, string> {
  return API_KEY ? { "X-API-Key": API_KEY } : {};
}

/** Fetch with API-key + Bearer token from the active NextAuth session. */
async function authedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const session = await getSession();
  const token = session?.accessToken ?? "";
  const headers: Record<string, string> = {
    ...authHeaders(),
    ...(init.headers as Record<string, string> ?? {}),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return fetch(url, { ...init, headers });
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
  carmax_offer: number | null;
  kbb_ico: number | null;
  carvana_offer: number | null;
  local_market_value: number | null;
  local_market_comp_urls?: string[];
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
  seller_phone: string | null;
  seller_email: string | null;
  suggested_offer: number | null;
  cylinders: string | null;
  fuel: string | null;
  body_type: string | null;
  transmission: string | null;
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
  await authedFetch(`${BASE}/api/pipeline/stop`, { method: "POST" });
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

export interface DraftedMessage {
  id: number;
  message_text: string;
  status: string;
}

export async function draftMessage(listingId: string): Promise<DraftedMessage> {
  const res = await fetch(`${BASE}/api/deals/${listingId}/draft-message`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to generate message");
  return res.json();
}

export async function getPipelineStatus(): Promise<PipelineStatus> {
  const res = await authedFetch(`${BASE}/api/pipeline/status`, { cache: "no-store" });
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

export interface ManualOffers {
  carmax_offer?: number | null;
  kbb_ico?: number | null;
  carvana_offer?: number | null;
}

export async function submitManualOffers(listingId: string, offers: ManualOffers): Promise<Deal> {
  const params = new URLSearchParams();
  if (offers.carmax_offer)  params.set("carmax_offer",  String(offers.carmax_offer));
  if (offers.kbb_ico)       params.set("kbb_ico",       String(offers.kbb_ico));
  if (offers.carvana_offer) params.set("carvana_offer", String(offers.carvana_offer));
  const res = await authedFetch(
    `${BASE}/api/deals/${listingId}/manual-offers?${params}`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error("Failed to save offers");
  return res.json();
}

export async function startCarvanaOffer(listingId: string, vin?: string): Promise<void> {
  const params = vin ? `?vin=${encodeURIComponent(vin)}` : "";
  await fetch(`${BASE}/api/deals/${listingId}/carvana-offer${params}`, { method: "POST", headers: authHeaders() });
}

export async function getCarvanaOfferStatus(listingId: string): Promise<CarvanaOfferStatus> {
  const res = await fetch(`${BASE}/api/deals/${listingId}/carvana-offer`, { cache: "no-store", headers: authHeaders() });
  return res.json();
}

// ── CarMax Offer ──────────────────────────────────────────────────────────────

export interface CarmaxOfferStatus {
  status: "not_started" | "running" | "completed" | "error";
  offer: string | null;
  offer_low: number | null;
  offer_high: number | null;
  error: string | null;
  steps: string[];
}

export async function startCarmaxOffer(listingId: string, vin?: string): Promise<void> {
  const params = vin ? `?vin=${encodeURIComponent(vin)}` : "";
  await fetch(`${BASE}/api/deals/${listingId}/carmax-offer${params}`, { method: "POST", headers: authHeaders() });
}

export async function getCarmaxOfferStatus(listingId: string): Promise<CarmaxOfferStatus> {
  const res = await fetch(`${BASE}/api/deals/${listingId}/carmax-offer`, { cache: "no-store", headers: authHeaders() });
  return res.json();
}

// ── Cars.com Market Intel ─────────────────────────────────────────────────────

export interface CarscomCarfax {
  clean_title: boolean;
  no_accidents: boolean;
  one_owner: boolean;
  service_records: boolean;
}

export interface CarscomComp {
  title: string | null;
  price: number | null;
  mileage: number | null;
  year: number | null;
  trim: string | null;
  deal_rating: string | null;
  flip_score: number | null;
  url: string | null;
}

export interface CarscomIntel {
  vin: string;
  target: { url: string | null; title: string | null; price: number | null; mileage: number | null; trim: string | null; dealer_name: string | null } | null;
  flip_score: number | null;
  flip_breakdown: { deal_rating_score: number | null; price_score: number | null; carfax_score: number | null; resale_score: number | null };
  deal_rating: string | null;
  deal_savings: number | null;
  price_drop: number | null;
  carfax: CarscomCarfax;
  exterior_color: string | null;
  interior_color: string | null;
  transmission: string | null;
  drivetrain: string | null;
  fuel_type: string | null;
  mpg_city: number | null;
  mpg_highway: number | null;
  comparables: CarscomComp[];
  avg_comp_price: number | null;
  comp_count: number;
}

export interface CarscomIntelStatus {
  status: "not_started" | "running" | "completed" | "error" | "no_vin";
  data: CarscomIntel | null;
  error?: string;
}

export async function startCarscomIntel(listingId: string): Promise<void> {
  await fetch(`${BASE}/api/deals/${listingId}/carscom-intel`, { method: "POST", headers: authHeaders() });
}

export async function getCarscomIntelStatus(listingId: string): Promise<CarscomIntelStatus> {
  const res = await fetch(`${BASE}/api/deals/${listingId}/carscom-intel`, { cache: "no-store", headers: authHeaders() });
  return res.json();
}

// ── Run History ───────────────────────────────────────────────────────────────

export interface PipelineRun {
  id: number;
  user_key: string;
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  query: string;
  dry_run: number;
  listing_count: number;
  great_count: number;
  fair_count: number;
  status: "completed" | "stopped" | "error" | "running";
  zip_code: string;
  radius_miles: number;
}

export interface PipelineRunLogs {
  id: number;
  started_at: string;
  status: string;
  log_text: string;
}

export async function getRuns(limit = 50): Promise<PipelineRun[]> {
  const res = await authedFetch(`${BASE}/api/runs?limit=${limit}`, { cache: "no-store" });
  if (!res.ok) return [];
  return res.json();
}

export async function getRunLogs(runId: number): Promise<PipelineRunLogs> {
  const res = await authedFetch(`${BASE}/api/runs/${runId}/logs`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch run logs");
  return res.json();
}

export interface RunFilters {
  minYear?: number;
  maxYear?: number;
  maxPrice?: number;
  maxMileage?: number;
}

export async function runPipeline(query = "", dryRun = true, zipCode = "", radiusMiles = 0, includeFacebook = true, filters: RunFilters = {}): Promise<void> {
  const params = new URLSearchParams({ query, dry_run: String(dryRun), include_facebook: String(includeFacebook) });
  if (zipCode) params.set("zip_code", zipCode);
  if (radiusMiles) params.set("radius_miles", String(radiusMiles));
  if (filters.minYear)   params.set("min_year",    String(filters.minYear));
  if (filters.maxYear)   params.set("max_year",    String(filters.maxYear));
  if (filters.maxPrice)  params.set("max_price",   String(filters.maxPrice));
  if (filters.maxMileage) params.set("max_mileage", String(filters.maxMileage));
  const res = await authedFetch(`${BASE}/api/pipeline/run?${params}`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Failed to start pipeline (${res.status})`);
  }
}

// ── User portal ───────────────────────────────────────────────────────────────

/** POST with a 15-second timeout — aborts and throws if server doesn't respond. */
async function authFetch(path: string, body: object): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 15_000);
  try {
    return await fetch(`${BASE}${path}`, {
      method: "POST",
      signal: ctrl.signal,
      headers: { ...authHeaders() as Record<string, string>, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Request timed out — make sure the server is running");
    }
    if (err instanceof TypeError) {
      throw new Error("Cannot reach the server — make sure the API is running");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/** Extract a readable error message from a failed response. */
async function apiErrorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    const detail = data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg).join("; ");
    return fallback;
  } catch {
    return fallback;
  }
}

export async function apiRegister(email: string, password: string): Promise<{ token: string; user: AuthUser }> {
  const res = await authFetch("/auth/register", { email, password });
  if (!res.ok) throw new Error(await apiErrorMessage(res, "Registration failed"));
  return res.json();
}

export async function apiForgotPassword(email: string): Promise<void> {
  await authFetch("/auth/forgot-password", { email });
}

export async function apiResetPassword(token: string, password: string): Promise<void> {
  const res = await authFetch("/auth/reset-password", { token, password });
  if (!res.ok) throw new Error(await apiErrorMessage(res, "Reset failed"));
}

export async function apiLogin(email: string, password: string): Promise<{ token: string; user: AuthUser }> {
  const res = await authFetch("/auth/login", { email, password });
  if (!res.ok) throw new Error(await apiErrorMessage(res, "Login failed"));
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

export async function previewSearch(userId: number, criteria: SearchCriteria): Promise<{ count: number; results: Deal[] }> {
  const res = await authedFetch(`${BASE}/users/${userId}/searches/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(criteria),
  });
  if (!res.ok) throw new Error("Failed to run search");
  return res.json();
}

export async function getSavedSearches(userId: number): Promise<SavedSearch[]> {
  const res = await authedFetch(`${BASE}/users/${userId}/searches`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load searches");
  return res.json();
}

export async function createSavedSearch(userId: number, name: string, criteria: SearchCriteria): Promise<SavedSearch> {
  const res = await authedFetch(`${BASE}/users/${userId}/searches`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, criteria }),
  });
  if (!res.ok) throw new Error("Failed to create search");
  return res.json();
}

export async function updateSavedSearch(userId: number, searchId: number, name: string, criteria: SearchCriteria): Promise<SavedSearch> {
  const res = await authedFetch(`${BASE}/users/${userId}/searches/${searchId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, criteria }),
  });
  if (!res.ok) throw new Error("Failed to update search");
  return res.json();
}

export async function executeSavedSearch(userId: number, searchId: number): Promise<{ count: number; results: Deal[] }> {
  const res = await authedFetch(`${BASE}/users/${userId}/searches/${searchId}/execute`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to execute search");
  return res.json();
}

export async function deleteSavedSearch(userId: number, searchId: number): Promise<void> {
  await authedFetch(`${BASE}/users/${userId}/searches/${searchId}`, { method: "DELETE" });
}

export async function deleteAllSavedSearches(userId: number): Promise<{ deleted: number }> {
  const res = await authedFetch(`${BASE}/users/${userId}/searches`, { method: "DELETE" });
  return res.json();
}

export async function getUserFavorites(userId: number): Promise<Deal[]> {
  const res = await authedFetch(`${BASE}/users/${userId}/favorites`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load favorites");
  return res.json();
}

export async function addUserFavorite(userId: number, deal: Deal): Promise<void> {
  await authedFetch(`${BASE}/users/${userId}/favorites`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ listing_data: deal }),
  });
}

export async function removeUserFavorite(userId: number, listingId: string): Promise<void> {
  await authedFetch(`${BASE}/users/${userId}/favorites/${listingId}`, { method: "DELETE" });
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
  const res = await authedFetch(`${BASE}/users/${userId}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load profile");
  return res.json();
}

export async function updateUserProfile(userId: number, data: { email?: string; notify_carvana?: boolean }): Promise<UserProfile> {
  const res = await authedFetch(`${BASE}/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update profile");
  return res.json();
}

// ── Admin ─────────────────────────────────────────────────────────────────────

export async function adminGetUsers(): Promise<UserProfile[]> {
  const res = await authedFetch(`${BASE}/admin/users`, { cache: "no-store" });
  if (!res.ok) throw new Error("Admin access required");
  return res.json();
}

export async function adminUpdateUser(id: number, data: { role?: string; notify_carvana?: boolean; email?: string }): Promise<UserProfile> {
  const res = await authedFetch(`${BASE}/admin/users/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update user");
  return res.json();
}

export async function adminDeleteUser(id: number): Promise<void> {
  await authedFetch(`${BASE}/admin/users/${id}`, { method: "DELETE" });
}

export async function adminGetUserSearches(id: number): Promise<SavedSearch[]> {
  const res = await authedFetch(`${BASE}/admin/users/${id}/searches`, { cache: "no-store" });
  return res.json();
}

export type AdminSavedSearch = SavedSearch & { owner_email: string };

export async function adminGetAllSearches(): Promise<AdminSavedSearch[]> {
  const res = await authedFetch(`${BASE}/admin/searches`, { cache: "no-store" });
  if (!res.ok) throw new Error("Admin access required");
  return res.json();
}

export async function adminGetUserFavorites(id: number): Promise<Deal[]> {
  const res = await authedFetch(`${BASE}/admin/users/${id}/favorites`, { cache: "no-store" });
  return res.json();
}

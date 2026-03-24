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

export async function runPipeline(query = "", dryRun = true, zipCode = "", radiusMiles = 0): Promise<void> {
  const params = new URLSearchParams({ query, dry_run: String(dryRun) });
  if (zipCode) params.set("zip_code", zipCode);
  if (radiusMiles) params.set("radius_miles", String(radiusMiles));
  await fetch(`${BASE}/api/pipeline/run?${params}`, { method: "POST", headers: authHeaders() });
}

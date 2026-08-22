/**
 * Typed client for the Python sourcing engine.
 * Shapes mirror the FastAPI OpenAPI schema at /openapi.json.
 */
/**
 * Same-origin by default: the Python API serves this bundle, so relative paths
 * work and there is nothing to configure. Override only when running the
 * Next dev server separately.
 */
export const API = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export type Check = { name: string; status: "PASS" | "WARN" | "FAIL" | "SKIP"; detail: string; fix: string };
export type Verification = { ok: boolean; summary: string; checks: Check[] };

export type Health = {
  status: string;
  keepa_configured: boolean;
  amazon_data: string;
  serverless: boolean;
  scanning_available: boolean;
};

export type Settings = {
  keepa_configured: boolean;
  keepa_key_masked: string | null;
  min_roi: number; max_bsr: number;
  inbound_cost: number; prep_cost: number;
};

export type Retailer = {
  slug: string; name: string; host: string;
  platform: string; tier: number; enabled: number; products: number;
};

export type Stats = {
  retailers: number; products: number; price_snapshots: number;
  amazon_products: number; matches: number; last_scan: string | null;
};

export type Lead = {
  retailer: string; retailer_slug: string; product_id: number;
  title: string; brand: string | null; url: string | null;
  pack_qty: number | null; price: number; list_price: number;
  discount_pct: number; captured_at: string;
  amazon_price: number; net_profit: number; roi_pct: number;
  margin_pct: number; referral_fee: number; fba_fee: number;
  flags: string[]; modelled: boolean;
};

export type LeadPage = {
  total: number; count: number; offset: number;
  items: Lead[]; modelled: boolean; note: string;
};

export type Product = {
  product_id: number; retailer: string; retailer_slug: string;
  title: string; brand: string | null; url: string | null;
  sku: string | null; upc: string | null; pack_qty: number | null;
  price: number; list_price: number | null; in_stock: boolean;
  discount_pct: number | null; captured_at: string;
};

export type ProductPage = {
  total: number; count: number; offset: number; items: Product[];
};

export type Funnel = {
  skus_ingested: number; discounted_in_stock: number; discounted_pct: number;
  within_price_band: number; band_pct: number;
  keepa_lookups_needed: number; lookup_pct: number; reduction_factor: number | null;
};

export type MatchStats = {
  attempted: number; auto: number; pending: number;
  rejected: number; no_candidate: number; errors: number; keepa_mode: string;
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, { cache: "no-store", ...init });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : msg;
    } catch { /* keep status text */ }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

const qs = (p: Record<string, string | number | boolean | undefined>) =>
  Object.entries(p)
    .filter(([, v]) => v !== undefined && v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join("&");

export const api = {
  health:    () => req<Health>("/health"),
  stats:     () => req<Stats>("/stats"),
  settings:  () => req<Settings>("/settings"),
  retailers: () => req<Retailer[]>("/retailers"),
  funnel:    () => req<Funnel>("/candidates"),
  verify:    (offline = false) => req<Verification>(`/verify?offline=${offline}`),

  saveKey: (api_key: string) =>
    req<Settings>("/settings/keepa-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key }),
    }),

  ingest: (slug: string, pages?: number) =>
    req<{ retailer: string; seen: number; new: number; price_changes: number; on_sale: number }>(
      `/retailers/${slug}/ingest?${qs({ pages })}`, { method: "POST" }),

  match: (limit = 25) =>
    req<MatchStats>(`/match?${qs({ limit })}`, { method: "POST" }),

  leads: (p: { min_roi?: number; multiplier?: number; retailer?: string; limit?: number }) =>
    req<LeadPage>(`/leads?${qs(p)}`),

  verified: (p: { min_roi?: number; include_pending?: boolean; retailer?: string; limit?: number }) =>
    req<LeadPage>(`/leads/verified?${qs(p)}`),

  products: (p: { retailer?: string; q?: string; on_sale?: boolean;
                  in_stock?: boolean; limit?: number; offset?: number }) =>
    req<ProductPage>(`/products?${qs(p)}`),

  csvUrl: (min_discount = 15) => `${API}/export.csv?${qs({ min_discount })}`,
};

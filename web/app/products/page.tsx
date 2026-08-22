"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Product, type ProductPage, type Retailer } from "@/lib/api";
import { Pagination } from "@/components/Pagination";

export default function ProductsPage() {
  const [retailer, setRetailer] = useState("");
  const [query, setQuery] = useState("");
  const [onSale, setOnSale] = useState<"" | "yes" | "no">("");
  const [inStock, setInStock] = useState(true);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  // Typing should not fire a request per keystroke.
  const [debounced, setDebounced] = useState("");
  const [page, setPage] = useState<ProductPage | null>(null);
  const [retailers, setRetailers] = useState<Retailer[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Deep link from the dashboard: /products?retailer=vitacost
  useEffect(() => {
    const r = new URLSearchParams(window.location.search).get("retailer");
    if (r) setRetailer(r);
    api.retailers().then(setRetailers).catch(() => {});
  }, []);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(t);
  }, [query]);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      setPage(await api.products({
        retailer: retailer || undefined,
        q: debounced || undefined,
        on_sale: onSale === "" ? undefined : onSale === "yes",
        in_stock: inStock ? true : undefined,
        limit: pageSize, offset,
      }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [retailer, debounced, onSale, inStock, offset, pageSize]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setOffset(0); }, [retailer, debounced, onSale, inStock]);

  const total = page?.total ?? 0;
  const shown = page?.items.length ?? 0;

  return (
    <main style={{ display: "flex", flexDirection: "column", gap: "1.25rem", paddingTop: "2.5rem" }}>
      <header style={{ display: "flex", flexDirection: "column", gap: ".4rem" }}>
        <span className="eyebrow">Catalog</span>
        <h1 style={{ fontSize: "1.9rem", fontWeight: 700 }}>
          {retailers.find((r) => r.slug === retailer)?.name ?? "All products"}
        </h1>
        <p className="muted tiny" style={{ margin: 0 }}>
          Live prices from each retailer&rsquo;s catalog.
        </p>
      </header>

      <section className="card" style={{ display: "flex", gap: "1rem", alignItems: "flex-end", flexWrap: "wrap" }}>
        <label className="field" style={{ flex: "1 1 16rem" }}>
          <span>Search</span>
          <input value={query} onChange={(e) => setQuery(e.target.value)}
                 placeholder="product or brand…" />
        </label>
        <label className="field">
          <span>Retailer</span>
          <select value={retailer} onChange={(e) => setRetailer(e.target.value)}>
            <option value="">All</option>
            {retailers.map((r) => (
              <option key={r.slug} value={r.slug}>{r.name} ({r.products.toLocaleString()})</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Price</span>
          <select value={onSale} onChange={(e) => setOnSale(e.target.value as "" | "yes" | "no")}>
            <option value="">Any</option>
            <option value="yes">Discounted only</option>
            <option value="no">Full price only</option>
          </select>
        </label>
        <label className="field">
          <span>In stock</span>
          <input type="checkbox" checked={inStock}
                 onChange={(e) => setInStock(e.target.checked)}
                 style={{ width: "1.1rem", height: "1.1rem" }} />
        </label>
      </section>

      {error && <div className="card warn tiny mono">{error}</div>}

      <p className="muted tiny" style={{ margin: 0 }}>
        {loading ? "Loading…" : `${total.toLocaleString()} products`}
      </p>

      <Pagination total={total} offset={offset} pageSize={pageSize}
                  onOffset={setOffset} onPageSize={setPageSize} />

      <div className="tablewrap">
        <table>
          <thead>
            <tr>
              <th></th><th>Retailer</th><th>Product</th><th>Pack</th>
              <th>Price</th><th>Was</th><th>Off</th><th>Stock</th><th>Seen</th>
            </tr>
          </thead>
          <tbody>
            {(page?.items ?? []).map((p) => <Row key={p.product_id} p={p} />)}
            {!loading && !shown && (
              <tr><td colSpan={9} className="muted tiny" style={{ padding: "1.5rem" }}>
                No products match these filters.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      <Pagination total={total} offset={offset} pageSize={pageSize}
                  onOffset={setOffset} onPageSize={setPageSize} />
    </main>
  );
}

function Row({ p }: { p: Product }) {
  const d = p.discount_pct ?? 0;
  const band = d >= 50 ? "FAIL" : d >= 30 ? "WARN" : "PASS";
  return (
    <tr>
      <td style={{ width: "5.5rem" }}>
        {p.image_url ? (
          <img src={p.image_url} alt="" loading="lazy" width={76} height={76}
               style={{ width: 76, height: 76, objectFit: "contain",
                        borderRadius: 4, background: "var(--surface-alt)",
                        border: "1px solid var(--line-soft)", padding: 2 }} />
        ) : (
          <div aria-hidden style={{ width: 76, height: 76, borderRadius: 4,
                 background: "var(--surface-alt)", border: "1px solid var(--line-soft)" }} />
        )}
      </td>
      <td className="tiny muted">{p.retailer}</td>
      <td>
        {p.url ? <a href={p.url} target="_blank" rel="noopener">{p.title.slice(0, 70)}</a>
               : p.title.slice(0, 70)}
        <div className="tiny muted">
          {p.brand}{p.sku && ` · SKU ${p.sku}`}{p.upc && ` · UPC ${p.upc}`}
        </div>
      </td>
      <td className="n">{p.pack_qty ?? "—"}</td>
      <td className="n"><strong>${p.price.toFixed(2)}</strong></td>
      <td className="n was">{p.list_price ? `$${p.list_price.toFixed(2)}` : "—"}</td>
      <td className="n">{d > 0 ? <span className={`pill ${band}`}>{d.toFixed(0)}%</span> : <span className="muted">—</span>}</td>
      <td className="n">{p.in_stock ? <span className="pill PASS">yes</span> : <span className="pill SKIP">no</span>}</td>
      <td className="n tiny muted">{p.captured_at.slice(0, 10)}</td>
    </tr>
  );
}

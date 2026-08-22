"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Product, type ProductPage, type Retailer } from "@/lib/api";

const PAGE = 100;

export default function ProductsPage() {
  const [retailer, setRetailer] = useState("");
  const [query, setQuery] = useState("");
  const [onSale, setOnSale] = useState<"" | "yes" | "no">("");
  const [inStock, setInStock] = useState(true);
  const [offset, setOffset] = useState(0);
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

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      setPage(await api.products({
        retailer: retailer || undefined,
        q: query.trim() || undefined,
        on_sale: onSale === "" ? undefined : onSale === "yes",
        in_stock: inStock ? true : undefined,
        limit: PAGE, offset,
      }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [retailer, query, onSale, inStock, offset]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setOffset(0); }, [retailer, query, onSale, inStock]);

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
          Everything being tracked, discounted or not. Prices are read live from
          each retailer&rsquo;s own catalog.
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
        {total > PAGE && ` · showing ${offset + 1}–${offset + shown}`}
      </p>

      <div className="tablewrap">
        <table>
          <thead>
            <tr>
              <th>Retailer</th><th>Product</th><th>Pack</th>
              <th>Price</th><th>Was</th><th>Off</th><th>Stock</th><th>Seen</th>
            </tr>
          </thead>
          <tbody>
            {(page?.items ?? []).map((p) => <Row key={p.product_id} p={p} />)}
            {!loading && !shown && (
              <tr><td colSpan={8} className="muted tiny" style={{ padding: "1.5rem" }}>
                No products match these filters.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {total > PAGE && (
        <div style={{ display: "flex", gap: ".6rem", alignItems: "center" }}>
          <button className="ghost" disabled={offset === 0 || loading}
                  onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
          <button className="ghost" disabled={offset + PAGE >= total || loading}
                  onClick={() => setOffset(offset + PAGE)}>Next</button>
          <span className="muted tiny">page {Math.floor(offset / PAGE) + 1} of {Math.ceil(total / PAGE)}</span>
        </div>
      )}
    </main>
  );
}

function Row({ p }: { p: Product }) {
  const d = p.discount_pct ?? 0;
  const band = d >= 50 ? "FAIL" : d >= 30 ? "WARN" : "PASS";
  return (
    <tr>
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

"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Lead, type LeadPage, type Retailer } from "@/lib/api";

export default function LeadsPage() {
  const [verified, setVerified] = useState(false);
  const [minRoi, setMinRoi] = useState(30);
  const [retailer, setRetailer] = useState("");
  const [includePending, setIncludePending] = useState(false);
  const [page, setPage] = useState<LeadPage | null>(null);
  const [retailers, setRetailers] = useState<Retailer[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.retailers().then(setRetailers).catch(() => {}); }, []);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      setPage(verified
        ? await api.verified({ min_roi: minRoi, include_pending: includePending, retailer: retailer || undefined, limit: 200 })
        : await api.leads({ min_roi: minRoi, retailer: retailer || undefined, limit: 200 }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [verified, minRoi, retailer, includePending]);

  useEffect(() => { load(); }, [load]);

  return (
    <main style={{ display: "flex", flexDirection: "column", gap: "1.25rem", paddingTop: "2.5rem" }}>
      <header style={{ display: "flex", flexDirection: "column", gap: ".4rem" }}>
        <span className="eyebrow">{verified ? "Verified against Amazon" : "Estimated"}</span>
        <h1 style={{ fontSize: "1.9rem", fontWeight: 700 }}>Leads</h1>
      </header>

      {!verified && (
        <div className="card warn tiny">
          <strong>Profit figures are estimated.</strong> Retailer prices and discounts
          are live, but the Amazon sale price is inferred rather than looked up.
          Connect a Keepa key in <a href="/settings">Settings</a> for verified numbers.
        </div>
      )}

      <section className="card" style={{ display: "flex", gap: "1rem", alignItems: "flex-end", flexWrap: "wrap" }}>
        <label className="field">
          <span>Source</span>
          <select value={verified ? "v" : "m"} onChange={(e) => setVerified(e.target.value === "v")}>
            <option value="m">Estimated</option>
            <option value="v">Verified</option>
          </select>
        </label>
        <label className="field">
          <span>Min ROI %</span>
          <input type="number" value={minRoi} min={0} step={5}
                 onChange={(e) => setMinRoi(Number(e.target.value))} style={{ width: "7rem" }} />
        </label>
        <label className="field">
          <span>Retailer</span>
          <select value={retailer} onChange={(e) => setRetailer(e.target.value)}>
            <option value="">All</option>
            {retailers.map((r) => <option key={r.slug} value={r.slug}>{r.name}</option>)}
          </select>
        </label>
        {verified && (
          <label className="field">
            <span>Include review queue</span>
            <input type="checkbox" checked={includePending}
                   onChange={(e) => setIncludePending(e.target.checked)} style={{ width: "1.1rem", height: "1.1rem" }} />
          </label>
        )}
        <a className="btn" href={api.csvUrl(15)} style={{ textDecoration: "none", marginLeft: "auto" }}>
          Export CSV
        </a>
      </section>

      {error && <div className="card warn tiny mono">{error}</div>}

      <p className="muted tiny" style={{ margin: 0 }}>
        {loading ? "Loading…" : `${page?.total ?? 0} leads at ${minRoi}%+ ROI`}
        {page && !page.modelled && " · verified against Amazon"}
      </p>

      <div className="tablewrap sticky">
        <table>
          <thead>
            <tr>
              <th>Retailer</th><th>Product</th><th>Pack</th>
              <th>Cost</th><th>Was</th><th>Off</th>
              <th>Amazon</th><th>Fees</th><th>Net</th><th>ROI</th><th>Flags</th>
            </tr>
          </thead>
          <tbody>
            {(page?.items ?? []).map((l) => <Row key={`${l.product_id}-${l.price}`} l={l} />)}
            {!loading && !page?.items.length && (
              <tr><td colSpan={11} className="muted tiny" style={{ padding: "1.5rem" }}>
                {verified
                  ? "No verified leads yet — connect a Keepa key in Settings."
                  : "No leads at this ROI threshold. Try lowering it."}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </main>
  );
}

function Row({ l }: { l: Lead }) {
  const band = l.discount_pct >= 50 ? "hot" : l.discount_pct >= 25 ? "warm" : "mild";
  return (
    <tr>
      <td className="tiny muted">{l.retailer}</td>
      <td>
        {l.url ? <a href={l.url} target="_blank" rel="noopener">{l.title.slice(0, 62)}</a>
               : l.title.slice(0, 62)}
        {l.brand && <div className="tiny muted">{l.brand}</div>}
      </td>
      <td className="n">{l.pack_qty ?? "—"}</td>
      <td className="n">${l.price.toFixed(2)}</td>
      <td className="n was">${l.list_price.toFixed(2)}</td>
      <td className="n"><span className={`disc ${band}`}>{l.discount_pct.toFixed(0)}%</span></td>
      <td className="n">${l.amazon_price.toFixed(2)}</td>
      <td className="n muted">${(l.referral_fee + l.fba_fee).toFixed(2)}</td>
      <td className="n"><strong>${l.net_profit.toFixed(2)}</strong></td>
      <td className="n" style={{ color: "var(--good)", fontWeight: 700 }}>{l.roi_pct.toFixed(0)}%</td>
      <td className="tiny">
        {l.flags.map((f) => (
          <span key={f} className="pill WARN" style={{ marginRight: ".25rem", display: "inline-block", marginBottom: ".15rem" }}>
            {f.replace(/_/g, " ").toLowerCase()}
          </span>
        ))}
      </td>
    </tr>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { LiveStatus } from "@/components/LiveStatus";
import { api, type Funnel, type Retailer, type Settings, type Stats } from "@/lib/api";

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [retailers, setRetailers] = useState<Retailer[]>([]);
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, cfg, r, f] = await Promise.all([
        api.stats(), api.settings(), api.retailers(), api.funnel(),
      ]);
      setStats(s); setSettings(cfg); setRetailers(r); setFunnel(f); setError(null);
    } catch (e) {
      const msg = (e as Error).message;
      setError(/Failed to fetch|NetworkError|ECONNREFUSED/i.test(msg)
        ? "The engine is not running.\n\nStart it with:  ./start.sh"
        : msg);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  if (error && !stats) {
    return (
      <main style={{ paddingTop: "3rem" }}>
        <div className="card warn">
          <h2 style={{ fontSize: "1.2rem", marginBottom: ".5rem" }}>
            {/not running/i.test(error) ? "Engine not running" : "Cannot read the database"}
          </h2>
          <pre className="mono tiny" style={{ whiteSpace: "pre-wrap", margin: 0 }}>{error}</pre>
        </div>
      </main>
    );
  }

  const totalDiscounts = funnel?.discounted_in_stock ?? 0;

  return (
    <main style={{ display: "flex", flexDirection: "column", gap: "1.75rem", paddingTop: "2.5rem" }}>
      <header style={{ display: "flex", flexDirection: "column", gap: ".4rem" }}>
        <h1 style={{ fontSize: "2rem", fontWeight: 700, letterSpacing: "-.015em" }}>
          Sourcing overview
        </h1>
        <p className="muted" style={{ margin: 0, maxWidth: "42em" }}>
          Discounted products across {stats?.retailers ?? 0} US retailers, matched
          to Amazon and scored on profit.
        </p>
      </header>

      {!settings?.keepa_configured && (
        <div className="card warn">
          <div style={{ display: "flex", alignItems: "center", gap: ".7rem", flexWrap: "wrap" }}>
            <span className="pill WARN">Amazon data not connected</span>
            <span className="tiny muted">
              Profit and ROI figures are estimated until a Keepa key is added.
            </span>
            <a href="/settings" className="btn" style={{ marginLeft: "auto", textDecoration: "none" }}>
              Connect
            </a>
          </div>
        </div>
      )}

      <section className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(9.5rem,1fr))" }}>
        <Stat label="Retailers" value={stats?.retailers} />
        <Stat label="Products tracked" value={stats?.products?.toLocaleString()} />
        <Stat label="On sale now" value={totalDiscounts.toLocaleString()} href="/products?on_sale=true" />
        <Stat label="Amazon matches" value={stats?.matches?.toLocaleString()} />
        <Stat label="Price records" value={stats?.price_snapshots?.toLocaleString()} />
      </section>

      <LiveStatus />

      <section style={{ display: "flex", flexDirection: "column", gap: ".8rem" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: ".75rem" }}>
          <h2 style={{ fontSize: "1.15rem", fontWeight: 600 }}>Retailers</h2>
          <a href="/products" className="tiny" style={{ marginLeft: "auto" }}>
            Browse all products →
          </a>
        </div>
        <div className="tablewrap">
          <table>
            <thead>
              <tr><th>Retailer</th><th>Products</th><th>Removed</th><th>On sale</th><th>Updated</th></tr>
            </thead>
            <tbody>
              {retailers.map((r) => (
                <tr key={r.slug}>
                  <td>
                    <a href={`/products?retailer=${r.slug}`}
                       style={{ color: "var(--ink)", fontWeight: 600, textDecoration: "none" }}>
                      {r.name}
                    </a>
                    <div className="tiny muted mono">{r.host}</div>
                  </td>
                  <td className="n">
                    <a href={`/products?retailer=${r.slug}`} style={{ color: "var(--accent)" }}>
                      {r.products.toLocaleString()}
                    </a>
                  </td>
                  <td className="n">
                    {r.delisted > 0
                      ? <span className="muted" title="No longer listed by the retailer">
                          {r.delisted.toLocaleString()}
                        </span>
                      : <span className="muted">—</span>}
                  </td>
                  <td className="n">
                    <a href={`/products?retailer=${r.slug}&on_sale=true`} style={{ color: "var(--accent)" }}>
                      view
                    </a>
                  </td>
                  <td className="tiny muted">
                    {r.last_full_scan
                      ? `full scan ${r.last_full_scan.slice(0, 10)}`
                      : "no full scan yet"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

function Stat({ label, value, href }: { label: string; value?: string | number; href?: string }) {
  const inner = (
    <>
      <div className="v">{value ?? "—"}</div>
      <div className="k">{label}</div>
    </>
  );
  return href
    ? <a className="stat" href={href} style={{ textDecoration: "none" }}>{inner}</a>
    : <div className="stat">{inner}</div>;
}

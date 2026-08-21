"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Check, type Funnel, type Retailer, type Settings, type Stats, type Verification } from "@/lib/api";

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [retailers, setRetailers] = useState<Retailer[]>([]);
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [keyInput, setKeyInput] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, cfg, r, f] = await Promise.all([
        api.stats(), api.settings(), api.retailers(), api.funnel(),
      ]);
      setStats(s); setSettings(cfg); setRetailers(r); setFunnel(f); setError(null);
    } catch (e) {
      setError(
        `Cannot reach the engine. Start it with:  python3 -m uvicorn arbitrage.web.api:app --port 8000` +
        `\n(${(e as Error).message})`
      );
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  async function run<T>(label: string, fn: () => Promise<T>, after?: (r: T) => string) {
    setBusy(label); setError(null); setNotice(null);
    try {
      const r = await fn();
      if (after) setNotice(after(r));
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (error && !stats) {
    return (
      <main style={{ paddingTop: "3rem" }}>
        <div className="card warn">
          <h2 style={{ fontSize: "1.2rem", marginBottom: ".5rem" }}>Engine not running</h2>
          <pre className="mono tiny" style={{ whiteSpace: "pre-wrap", margin: 0 }}>{error}</pre>
        </div>
      </main>
    );
  }

  const configured = settings?.keepa_configured;

  return (
    <main style={{ display: "flex", flexDirection: "column", gap: "2rem", paddingTop: "2.5rem" }}>
      <header style={{ display: "flex", flexDirection: "column", gap: ".5rem" }}>
        <span className="eyebrow">Control panel</span>
        <h1 style={{ fontSize: "2.1rem", fontWeight: 700, letterSpacing: "-.015em" }}>
          Arbitrage Sourcing Engine
        </h1>
        <p className="muted" style={{ margin: 0, maxWidth: "42em" }}>
          Scan retailers for discounts, match products to Amazon, and calculate real profit.
        </p>
      </header>

      {/* ---- step 1: the key ---- */}
      <section className={`card ${configured ? "accent" : "warn"}`}>
        <div style={{ display: "flex", alignItems: "center", gap: ".75rem", marginBottom: ".6rem" }}>
          <span className="eyebrow">Step 1 — Amazon data</span>
          <span className={`pill ${configured ? "PASS" : "WARN"}`}>
            {configured ? "Connected" : "Not connected"}
          </span>
        </div>
        {configured ? (
          <p className="muted tiny" style={{ margin: 0 }}>
            Keepa key <span className="mono">{settings?.keepa_key_masked}</span> is active.
            Amazon prices, sales rank history and fees are live.
          </p>
        ) : (
          <>
            <p className="muted tiny" style={{ marginTop: 0 }}>
              Without a Keepa key the Amazon figures are <strong>modelled, not real</strong>.
              Paste your key below — it is validated with Keepa before being saved.
            </p>
            <div style={{ display: "flex", gap: ".5rem", flexWrap: "wrap" }}>
              <input
                type="password" placeholder="Keepa API key" value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                style={{ flex: "1 1 22rem" }} aria-label="Keepa API key"
              />
              <button
                disabled={keyInput.trim().length < 8 || busy !== null}
                onClick={() => run("key", () => api.saveKey(keyInput.trim()), () => "Keepa key saved and validated.")}
              >
                {busy === "key" ? "Checking…" : "Save & validate"}
              </button>
            </div>
          </>
        )}
      </section>

      {/* ---- stats ---- */}
      <section className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(9rem,1fr))" }}>
        {[
          ["Retailers", stats?.retailers],
          ["Products", stats?.products?.toLocaleString()],
          ["Price snapshots", stats?.price_snapshots?.toLocaleString()],
          ["Amazon matches", stats?.matches],
          ["Keepa lookups needed", funnel?.keepa_lookups_needed],
        ].map(([k, v]) => (
          <div className="stat" key={k as string}>
            <div className="v">{v ?? "—"}</div>
            <div className="k">{k as string}</div>
          </div>
        ))}
      </section>

      {/* ---- step 2: verify ---- */}
      <section className="card">
        <div style={{ display: "flex", alignItems: "center", gap: ".75rem", flexWrap: "wrap", marginBottom: ".75rem" }}>
          <span className="eyebrow">Step 2 — Check it works</span>
          <button className="ghost" disabled={busy !== null}
                  onClick={() => run("verify", () => api.verify(false), () => "")}>
            {busy === "verify" ? "Running…" : "Run verification"}
          </button>
          {verification && <span className={`pill ${verification.ok ? "PASS" : "FAIL"}`}>{verification.summary}</span>}
        </div>
        <p className="muted tiny" style={{ marginTop: 0 }}>
          Tests every stage — configuration, database, retailer connection, Keepa key,
          Amazon lookup, rank history, fees and ROI — and names the stage that failed.
        </p>
        {verification && <VerifyTable checks={verification.checks} />}
      </section>

      {/* ---- step 3: scan ---- */}
      <section className="card">
        <span className="eyebrow">Step 3 — Scan retailers</span>
        <div className="tablewrap" style={{ marginTop: ".75rem" }}>
          <table>
            <thead>
              <tr><th>Retailer</th><th>Platform</th><th>Tier</th><th>Products</th><th></th></tr>
            </thead>
            <tbody>
              {retailers.map((r) => (
                <tr key={r.slug}>
                  <td><strong>{r.name}</strong><div className="tiny muted mono">{r.host}</div></td>
                  <td className="tiny">{r.platform}</td>
                  <td><span className={`pill ${r.tier === 1 ? "PASS" : r.tier === 4 ? "FAIL" : "WARN"}`}>tier {r.tier}</span></td>
                  <td className="n">{r.products.toLocaleString()}</td>
                  <td>
                    <button className="ghost" disabled={busy !== null}
                      onClick={() => run(`scan-${r.slug}`, () => api.ingest(r.slug, 4),
                        (res) => `${r.name}: ${res.seen} scanned, ${res.new} new, ${res.price_changes} price changes, ${res.on_sale} on sale.`)}>
                      {busy === `scan-${r.slug}` ? "Scanning…" : "Scan"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ---- step 4: match ---- */}
      <section className="card">
        <div style={{ display: "flex", alignItems: "center", gap: ".75rem", flexWrap: "wrap" }}>
          <span className="eyebrow">Step 4 — Match to Amazon</span>
          <button disabled={busy !== null}
            onClick={() => run("match", () => api.match(25),
              (m) => `Attempted ${m.attempted}: ${m.auto} auto-accepted, ${m.pending} need review, ${m.rejected} rejected (${m.keepa_mode} mode).`)}>
            {busy === "match" ? "Matching…" : "Match 25 products"}
          </button>
          {!configured && <span className="pill WARN">simulation only — no key</span>}
        </div>
        {funnel && (
          <p className="muted tiny" style={{ marginBottom: 0 }}>
            Only {funnel.keepa_lookups_needed} of {funnel.skus_ingested.toLocaleString()} products need an
            Amazon lookup — a {funnel.reduction_factor}× reduction, so Keepa tokens go a long way.
          </p>
        )}
      </section>

      {notice && <div className="card accent tiny">{notice}</div>}
      {error && stats && <div className="card warn tiny mono" style={{ whiteSpace: "pre-wrap" }}>{error}</div>}
    </main>
  );
}

function VerifyTable({ checks }: { checks: Check[] }) {
  return (
    <div className="tablewrap">
      <table style={{ minWidth: "40rem" }}>
        <thead><tr><th>Stage</th><th>Result</th><th>Detail</th></tr></thead>
        <tbody>
          {checks.map((c) => (
            <tr key={c.name}>
              <td><strong>{c.name}</strong></td>
              <td><span className={`pill ${c.status}`}>{c.status}</span></td>
              <td className="tiny">
                {c.detail}
                {c.fix && <div className="muted" style={{ marginTop: ".2rem" }}>→ {c.fix}</div>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Check, type Funnel, type Settings, type Verification } from "@/lib/api";

/** Operational controls, kept off the main view. */
export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [keyInput, setKeyInput] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [cfg, f] = await Promise.all([api.settings(), api.funnel()]);
      setSettings(cfg); setFunnel(f);
    } catch (e) { setError((e as Error).message); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  async function run<T>(label: string, fn: () => Promise<T>, after?: (r: T) => string) {
    setBusy(label); setError(null); setNotice(null);
    try {
      const r = await fn();
      if (after) setNotice(after(r));
      await refresh();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(null); }
  }

  const configured = settings?.keepa_configured;

  return (
    <main style={{ display: "flex", flexDirection: "column", gap: "1.5rem", paddingTop: "2.5rem" }}>
      <header style={{ display: "flex", flexDirection: "column", gap: ".4rem" }}>
        <h1 style={{ fontSize: "1.9rem", fontWeight: 700 }}>Settings</h1>
        <p className="muted tiny" style={{ margin: 0 }}>
          Amazon connection, sourcing criteria and diagnostics.
        </p>
      </header>

      <section className={`card ${configured ? "accent" : "warn"}`}>
        <div style={{ display: "flex", alignItems: "center", gap: ".7rem", marginBottom: ".6rem" }}>
          <h2 style={{ fontSize: "1.05rem", fontWeight: 600 }}>Amazon data</h2>
          <span className={`pill ${configured ? "PASS" : "WARN"}`}>
            {configured ? "Connected" : "Not connected"}
          </span>
        </div>
        {configured ? (
          <p className="muted tiny" style={{ margin: 0 }}>
            Keepa key <span className="mono">{settings?.keepa_key_masked}</span> is active.
            Prices, sales rank history and fees are live.
          </p>
        ) : (
          <>
            <p className="muted tiny" style={{ marginTop: 0 }}>
              Without a Keepa key the Amazon figures are <strong>estimated, not real</strong>.
              The key is validated with Keepa before it is saved.
            </p>
            <div style={{ display: "flex", gap: ".5rem", flexWrap: "wrap" }}>
              <input type="password" placeholder="Keepa API key" value={keyInput}
                     onChange={(e) => setKeyInput(e.target.value)}
                     style={{ flex: "1 1 22rem" }} aria-label="Keepa API key" />
              <button disabled={keyInput.trim().length < 8 || busy !== null}
                      onClick={() => run("key", () => api.saveKey(keyInput.trim()),
                                          () => "Key saved and validated.")}>
                {busy === "key" ? "Checking…" : "Save"}
              </button>
            </div>
          </>
        )}
      </section>

      <section className="card">
        <h2 style={{ fontSize: "1.05rem", fontWeight: 600, marginBottom: ".6rem" }}>
          Sourcing criteria
        </h2>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(8rem,1fr))" }}>
          <Small label="Minimum ROI" value={`${settings?.min_roi ?? "—"}%`} />
          <Small label="Maximum BSR" value={settings?.max_bsr?.toLocaleString() ?? "—"} />
          <Small label="Inbound cost" value={`$${settings?.inbound_cost ?? "—"}`} />
          <Small label="Prep cost" value={`$${settings?.prep_cost ?? "—"}`} />
        </div>
        <p className="muted tiny" style={{ marginBottom: 0 }}>
          Change these in the <span className="mono">.env</span> file, or as environment
          variables on the deployment.
        </p>
      </section>

      {funnel && (
        <section className="card">
          <h2 style={{ fontSize: "1.05rem", fontWeight: 600, marginBottom: ".5rem" }}>
            Amazon lookup budget
          </h2>
          <p className="muted tiny" style={{ margin: 0 }}>
            Of {funnel.skus_ingested.toLocaleString()} tracked products, only{" "}
            <strong>{funnel.keepa_lookups_needed.toLocaleString()}</strong> are discounted
            and in a sensible price band — a {funnel.reduction_factor}× reduction, so a
            modest Keepa plan covers the whole catalog.
          </p>
        </section>
      )}

      <section className="card">
        <div style={{ display: "flex", alignItems: "center", gap: ".7rem", flexWrap: "wrap", marginBottom: ".6rem" }}>
          <h2 style={{ fontSize: "1.05rem", fontWeight: 600 }}>Diagnostics</h2>
          <button className="ghost" disabled={busy !== null}
                  onClick={() => run("verify", () => api.verify(false), () => "")}>
            {busy === "verify" ? "Running…" : "Run check"}
          </button>
          {verification && (
            <span className={`pill ${verification.ok ? "PASS" : "FAIL"}`}>{verification.summary}</span>
          )}
        </div>
        <p className="muted tiny" style={{ marginTop: 0 }}>
          Tests every stage — database, retailer connection, Keepa key, Amazon lookup,
          rank history, fees and ROI — and names anything that fails.
        </p>
        {verification && <CheckTable checks={verification.checks} />}
      </section>

      {notice && <div className="card accent tiny">{notice}</div>}
      {error && <div className="card warn tiny mono" style={{ whiteSpace: "pre-wrap" }}>{error}</div>}
    </main>
  );

  function CheckTable({ checks }: { checks: Check[] }) {
    return (
      <div className="tablewrap">
        <table style={{ minWidth: "38rem" }}>
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
}

function Small({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <div className="v" style={{ fontSize: "1.15rem" }}>{value}</div>
      <div className="k">{label}</div>
    </div>
  );
}

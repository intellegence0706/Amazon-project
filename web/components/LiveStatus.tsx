"use client";

import { useEffect, useState } from "react";
import { api, type ActivityItem, type Freshness } from "@/lib/api";

/**
 * Live view of the catalog.
 *
 * Polling rather than a push channel: prices only move when a scan runs, so a
 * socket would sit idle for hours and then deliver one burst. Polling every 30
 * seconds costs one small request and keeps an open dashboard current.
 */
export function LiveStatus({ intervalMs = 30_000 }: { intervalMs?: number }) {
  const [fresh, setFresh] = useState<Freshness | null>(null);
  const [feed, setFeed] = useState<ActivityItem[]>([]);
  const [live, setLive] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const pull = async () => {
      try {
        const [f, a] = await Promise.all([api.freshness(), api.activity(12)]);
        if (!cancelled) { setFresh(f); setFeed(a); }
      } catch { /* transient - the next tick retries */ }
    };
    pull();
    if (!live) return;
    const t = setInterval(pull, intervalMs);
    return () => { cancelled = true; clearInterval(t); };
  }, [live, intervalMs, tick]);

  // Re-render each second so "3 minutes ago" stays true between polls.
  const [, force] = useState(0);
  useEffect(() => {
    const t = setInterval(() => force((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const age = fresh?.last_scan ? ago(fresh.last_scan) : null;
  const stale = age !== null && age.minutes > 60 * 8;

  return (
    <section className="card" style={{ display: "flex", flexDirection: "column", gap: ".9rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: ".75rem", flexWrap: "wrap" }}>
        <span className="eyebrow">Live status</span>
        <span className={`pill ${stale ? "WARN" : "PASS"}`}>
          {live ? "● updating" : "paused"}
        </span>
        <span className="tiny muted">
          {age ? `data ${age.label} old` : "no scan recorded"}
          {fresh?.changes_in_last_scan
            ? ` · ${fresh.changes_in_last_scan.toLocaleString()} changes in last scan` : ""}
        </span>
        <div style={{ marginLeft: "auto", display: "flex", gap: ".4rem" }}>
          <button className="ghost" onClick={() => setTick((n) => n + 1)}>Refresh now</button>
          <button className="ghost" onClick={() => setLive((v) => !v)}>
            {live ? "Pause" : "Resume"}
          </button>
        </div>
      </div>

      {stale && (
        <p className="tiny" style={{ margin: 0, color: "var(--warn)" }}>
          Data is older than expected. The scheduled refresh may not be running —
          check the GitHub Actions workflow has a DATABASE_URL secret.
        </p>
      )}

      {feed.length === 0 ? (
        <p className="tiny muted" style={{ margin: 0 }}>
          No price movements recorded yet. Changes appear here after a scan finds
          a different price from the one already stored.
        </p>
      ) : (
        <ul className="feed">
          {feed.map((f) => (
            <li key={`${f.product_id}-${f.captured_at}`}>
              {f.image_url
                ? <img src={f.image_url} alt="" loading="lazy" width={34} height={34} />
                : <span className="feed-noimg" aria-hidden />}
              <span className="feed-title">
                {f.url ? <a href={f.url} target="_blank" rel="noopener">{f.title.slice(0, 54)}</a>
                       : f.title.slice(0, 54)}
                <span className="tiny muted"> · {f.retailer}</span>
              </span>
              <span className="mono tiny feed-prices">
                ${f.old_price.toFixed(2)} → <strong>${f.new_price.toFixed(2)}</strong>
              </span>
              <span className={`pill ${f.direction === "down" ? "PASS" : "FAIL"}`}>
                {f.direction === "down" ? "▼" : "▲"} {Math.abs(f.change_pct).toFixed(0)}%
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ago(iso: string) {
  const mins = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return { minutes: 0, label: "seconds" };
  if (mins < 60) return { minutes: mins, label: `${mins} minute${mins === 1 ? "" : "s"}` };
  const h = Math.floor(mins / 60);
  if (h < 24) return { minutes: mins, label: `${h} hour${h === 1 ? "" : "s"}` };
  const d = Math.floor(h / 24);
  return { minutes: mins, label: `${d} day${d === 1 ? "" : "s"}` };
}

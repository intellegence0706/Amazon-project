"use client";

/**
 * Numbered pagination.
 *
 * With ~12,500 products a page cannot list 125 page numbers, so it shows the
 * first, the last, and a window around the current page, with ellipses for the
 * gaps. Page size is adjustable because "how many rows fit" is a preference,
 * not something the app should decide.
 */
export function Pagination({
  total, offset, pageSize, onOffset, onPageSize,
}: {
  total: number;
  offset: number;
  pageSize: number;
  onOffset: (n: number) => void;
  onPageSize: (n: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.floor(offset / pageSize) + 1;
  if (total === 0) return null;

  const go = (page: number) => {
    const p = Math.min(Math.max(1, page), pages);
    onOffset((p - 1) * pageSize);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const from = offset + 1;
  const to = Math.min(offset + pageSize, total);

  return (
    <nav className="pager" aria-label="Pagination">
      <span className="pager-count mono">
        {from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()}
      </span>

      <div className="pager-buttons">
        <button className="ghost" onClick={() => go(1)} disabled={current === 1}
                aria-label="First page">«</button>
        <button className="ghost" onClick={() => go(current - 1)} disabled={current === 1}
                aria-label="Previous page">‹</button>

        {pageWindow(current, pages).map((p, i) =>
          p === "…" ? (
            <span key={`gap-${i}`} className="pager-gap" aria-hidden>…</span>
          ) : (
            <button
              key={p}
              className={p === current ? "" : "ghost"}
              onClick={() => go(p)}
              aria-current={p === current ? "page" : undefined}
              aria-label={`Page ${p}`}
            >
              {p}
            </button>
          )
        )}

        <button className="ghost" onClick={() => go(current + 1)} disabled={current === pages}
                aria-label="Next page">›</button>
        <button className="ghost" onClick={() => go(pages)} disabled={current === pages}
                aria-label="Last page">»</button>
      </div>

      <label className="pager-size">
        <span className="tiny muted">Per page</span>
        <select value={pageSize} onChange={(e) => { onPageSize(Number(e.target.value)); onOffset(0); }}>
          {[25, 50, 100, 200].map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </label>
    </nav>
  );
}

/** First, last, and a window around the current page; "…" marks the gaps. */
function pageWindow(current: number, pages: number, span = 2): (number | "…")[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);

  const out: (number | "…")[] = [1];
  const start = Math.max(2, current - span);
  const end = Math.min(pages - 1, current + span);

  if (start > 2) out.push("…");
  for (let p = start; p <= end; p++) out.push(p);
  if (end < pages - 1) out.push("…");
  out.push(pages);
  return out;
}

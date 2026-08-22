"""Generate a shareable static lead report.

Built for one specific constraint: the person who needs to see this is usually
not at a computer. It is a single self-contained HTML file - no server, no
install, opens on a phone.
"""
import html
from datetime import datetime, timezone

from . import db
from .economics import evaluate

QUERY = """
SELECT r.name AS retailer, p.title, p.brand, p.url, p.grams, p.pack_qty,
       s.price, s.list_price,
       ROUND(CAST((s.list_price - s.price) / NULLIF(s.list_price, 0) * 100 AS NUMERIC), 1) AS disc
  FROM products p
  JOIN retailers r ON r.id = p.retailer_id
  JOIN price_snapshots s ON s.id = (
       SELECT id FROM price_snapshots
        WHERE product_id = p.id ORDER BY captured_at DESC LIMIT 1)
 WHERE s.list_price > s.price AND s.price >= 0.50 AND s.in_stock = 1
   AND ((s.list_price - s.price) / NULLIF(s.list_price, 0) * 100) >= ?
 ORDER BY disc DESC
"""


def collect(conn, min_discount=15.0, multiplier=0.85, limit=120):
    rows = conn.execute(QUERY, (min_discount,)).fetchall()
    seen, leads = set(), []
    for x in rows:
        # Colourway/size variants share a URL and price - one lead, not twelve.
        key = (x["url"], round(x["price"], 2))
        if key in seen:
            continue
        seen.add(key)
        amz = round(x["list_price"] * multiplier, 2)
        lead = evaluate(cost=x["price"], sale_price=amz,
                        weight_lb=(x["grams"] or 454) / 453.6)
        leads.append({"row": x, "amz": amz, "lead": lead})
        if len(leads) >= limit:
            break
    return leads


def stats(conn, leads):
    g = lambda q: conn.execute(q).fetchone()[0]
    return {
        "retailers": g("SELECT COUNT(*) FROM retailers"),
        "products": g("SELECT COUNT(*) FROM products"),
        "snapshots": g("SELECT COUNT(*) FROM price_snapshots"),
        "leads": len(leads),
        "top": max((l["row"]["disc"] for l in leads), default=0),
    }


def _rows_html(leads):
    out = []
    for i in leads:
        x, lead = i["row"], i["lead"]
        d = x["disc"]
        band = "hot" if d >= 50 else "warm" if d >= 30 else "mild"
        pack = x["pack_qty"] or "—"
        title = html.escape(x["title"])[:78]
        url = html.escape(x["url"] or "#")
        out.append(f"""      <tr>
        <td class="ret">{html.escape(x['retailer'])}</td>
        <td class="prod"><a href="{url}" target="_blank" rel="noopener">{title}</a>
            <span class="brand">{html.escape(x['brand'] or '')}</span></td>
        <td class="n">{pack}</td>
        <td class="n">${x['price']:.2f}</td>
        <td class="n was">${x['list_price']:.2f}</td>
        <td class="n"><span class="disc {band}">{d:.0f}%</span></td>
        <td class="n model">${i['amz']:.2f}</td>
        <td class="n model">${lead.net_profit:.2f}</td>
        <td class="n model roi">{lead.roi_pct:.0f}%</td>
      </tr>""")
    return "\n".join(out)


def render(conn, **kw):
    leads = collect(conn, **kw)
    s = stats(conn, leads)
    ts = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")
    names = ", ".join(r["name"] for r in
                      conn.execute("SELECT name FROM retailers ORDER BY name"))
    return TEMPLATE.format(ts=ts, names=html.escape(names), rows=_rows_html(leads), **s)


TEMPLATE = """<title>Live Sourcing Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Zilla+Slab:wght@500;600;700&family=Source+Sans+3:wght@400;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
:root {{
  --ground:#F4F6F1; --surface:#FCFDFA; --surface-alt:#EDF0E9;
  --line:#D6DCD1; --line-soft:#E4E9DF;
  --ink:#171F19; --ink-mid:#46524A; --ink-soft:#6B776F;
  --accent:#1E5D45; --accent-soft:#E2EDE7;
  --hot:#A3341F; --hot-bg:#F7E6E1;
  --warm:#8A5B0B; --warm-bg:#F8EEDC;
  --mild:#40634F; --mild-bg:#E6EDE8;
  --caution:#8A5B0B; --caution-bg:#F8EEDC; --caution-line:#E0C48A;
}}
@media (prefers-color-scheme:dark) {{
  :root:not([data-theme="light"]) {{
    --ground:#12160F; --surface:#191E19; --surface-alt:#1F251F;
    --line:#313A31; --line-soft:#262E26;
    --ink:#E7EDE5; --ink-mid:#AFBBB2; --ink-soft:#85918A;
    --accent:#5CBE92; --accent-soft:#1C2C25;
    --hot:#E8917B; --hot-bg:#2E1C17;
    --warm:#D9A85C; --warm-bg:#2B2317;
    --mild:#8FC0A5; --mild-bg:#1B241E;
    --caution:#D9A85C; --caution-bg:#26200F; --caution-line:#5A4A22;
  }}
}}
:root[data-theme="dark"] {{
  --ground:#12160F; --surface:#191E19; --surface-alt:#1F251F;
  --line:#313A31; --line-soft:#262E26;
  --ink:#E7EDE5; --ink-mid:#AFBBB2; --ink-soft:#85918A;
  --accent:#5CBE92; --accent-soft:#1C2C25;
  --hot:#E8917B; --hot-bg:#2E1C17;
  --warm:#D9A85C; --warm-bg:#2B2317;
  --mild:#8FC0A5; --mild-bg:#1B241E;
  --caution:#D9A85C; --caution-bg:#26200F; --caution-line:#5A4A22;
}}
*{{box-sizing:border-box}}
body{{background:var(--ground);color:var(--ink);margin:0;padding:0 1rem 5rem;
  font-family:"Source Sans 3",ui-sans-serif,system-ui,sans-serif;font-size:1rem;line-height:1.6;
  -webkit-font-smoothing:antialiased}}
.wrap{{max-width:72rem;margin:0 auto;display:flex;flex-direction:column;gap:2rem}}
header{{padding-top:3rem;display:flex;flex-direction:column;gap:.9rem}}
.eyebrow{{font-family:"IBM Plex Mono",monospace;font-size:.68rem;font-weight:500;
  letter-spacing:.14em;text-transform:uppercase;color:var(--ink-soft);
  display:flex;gap:.6rem;flex-wrap:wrap;align-items:center}}
.eyebrow i{{font-style:normal;color:var(--line)}}
h1{{font-family:"Zilla Slab",Georgia,serif;font-size:clamp(1.9rem,1.3rem+2.6vw,2.9rem);
  font-weight:700;letter-spacing:-.015em;margin:0;line-height:1.12;text-wrap:balance}}
.sub{{color:var(--ink-mid);max-width:42em;margin:0;font-size:1.05rem}}
.caution{{background:var(--caution-bg);border:1px solid var(--caution-line);
  border-left:3px solid var(--caution);border-radius:3px;padding:1.1rem 1.35rem;
  display:flex;flex-direction:column;gap:.4rem}}
.caution b{{font-family:"IBM Plex Mono",monospace;font-size:.68rem;letter-spacing:.13em;
  text-transform:uppercase;color:var(--caution)}}
.caution p{{margin:0;font-size:.96rem;color:var(--ink-mid);max-width:52em}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:.75rem}}
.stat{{background:var(--surface);border:1px solid var(--line-soft);border-radius:3px;
  padding:1rem 1.15rem;display:flex;flex-direction:column;gap:.15rem}}
.stat .v{{font-family:"IBM Plex Mono",monospace;font-size:1.6rem;font-weight:600;
  font-variant-numeric:tabular-nums;color:var(--accent);line-height:1.1}}
.stat .k{{font-family:"IBM Plex Mono",monospace;font-size:.63rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-soft)}}
.tablewrap{{overflow-x:auto;border:1px solid var(--line);border-radius:3px;background:var(--surface)}}
table{{border-collapse:collapse;width:100%;min-width:56rem;font-size:.92rem}}
th,td{{text-align:left;padding:.62rem .8rem;border-bottom:1px solid var(--line-soft);vertical-align:top}}
thead th{{font-family:"IBM Plex Mono",monospace;font-size:.6rem;font-weight:600;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink-soft);background:var(--surface-alt);
  border-bottom:1px solid var(--line);position:sticky;top:0}}
thead th.m{{color:var(--caution)}}
tbody tr:last-child td{{border-bottom:none}}
tbody tr:hover{{background:var(--accent-soft)}}
td.n{{font-family:"IBM Plex Mono",monospace;font-variant-numeric:tabular-nums;white-space:nowrap}}
td.ret{{color:var(--ink-mid);white-space:nowrap;font-size:.85rem}}
td.was{{color:var(--ink-soft);text-decoration:line-through}}
td.model{{color:var(--ink-mid)}}
td.roi{{font-weight:600;color:var(--accent)}}
td.prod a{{color:var(--ink);text-decoration:none;font-weight:600}}
td.prod a:hover{{color:var(--accent);text-decoration:underline}}
td.prod .brand{{display:block;font-size:.78rem;color:var(--ink-soft)}}
.disc{{font-weight:600;padding:.16rem .42rem;border-radius:2px;font-size:.84rem}}
.disc.hot{{color:var(--hot);background:var(--hot-bg)}}
.disc.warm{{color:var(--warm);background:var(--warm-bg)}}
.disc.mild{{color:var(--mild);background:var(--mild-bg)}}
.method{{background:var(--surface-alt);border:1px solid var(--line);border-radius:3px;
  padding:1.4rem 1.6rem;display:flex;flex-direction:column;gap:.7rem}}
.method h2{{font-family:"IBM Plex Mono",monospace;font-size:.68rem;letter-spacing:.13em;
  text-transform:uppercase;color:var(--ink-soft);margin:0}}
.method p{{margin:0;font-size:.94rem;color:var(--ink-mid);max-width:54em}}
.method code{{font-family:"IBM Plex Mono",monospace;font-size:.86em;background:var(--surface);
  border:1px solid var(--line-soft);border-radius:2px;padding:.06em .32em}}
footer{{font-family:"IBM Plex Mono",monospace;font-size:.68rem;letter-spacing:.06em;
  color:var(--ink-soft);border-top:1px solid var(--line);padding-top:1.1rem}}
a:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
</style>
<div class="wrap">
<header>
  <div class="eyebrow"><span>Live scan</span><i>/</i><span>{ts}</span><i>/</i><span>{names}</span></div>
  <h1>Live Sourcing Report</h1>
  <p class="sub">Discounted, in-stock products pulled directly from retailer catalogs.
     Every price below was read from the retailer within the last few minutes.</p>
</header>

<div class="caution">
  <b>Read this before the numbers</b>
  <p>Retailer prices and discounts are <strong>real</strong>, scanned live. The three
     right-hand columns — Amazon price, net profit and ROI — are <strong>modelled</strong>,
     not live Amazon data. They demonstrate that the fee and margin engine works; they are
     not yet verified sourcing decisions. Live Amazon pricing and sales-rank history require
     a Keepa API key, which is the single remaining dependency.</p>
</div>

<div class="stats">
  <div class="stat"><span class="v">{retailers}</span><span class="k">Retailers</span></div>
  <div class="stat"><span class="v">{products:,}</span><span class="k">Products tracked</span></div>
  <div class="stat"><span class="v">{snapshots:,}</span><span class="k">Price snapshots</span></div>
  <div class="stat"><span class="v">{leads}</span><span class="k">Discounts found</span></div>
  <div class="stat"><span class="v">{top:.0f}%</span><span class="k">Deepest discount</span></div>
</div>

<div class="tablewrap">
<table>
  <thead><tr>
    <th>Retailer</th><th>Product</th><th>Pack</th><th>Now</th><th>Was</th><th>Off</th>
    <th class="m">Amazon*</th><th class="m">Net*</th><th class="m">ROI*</th>
  </tr></thead>
  <tbody>
{rows}
  </tbody>
</table>
</div>

<div class="method">
  <h2>How this was produced</h2>
  <p>A platform fingerprinter sorts each retailer domain into an acquisition tier. Retailers
     on supported ecommerce platforms expose their full catalog as structured JSON, so no
     retailer API keys and no per-retailer approvals are needed. Sale detection reads the
     retailer's own list price against the current price — no price-history diffing required.</p>
  <p>Ingestion is idempotent: re-running writes a price snapshot only when a price actually
     moved, which keeps daily refreshes cheap indefinitely. Colourway and size variants sharing
     a product URL are collapsed to a single lead.</p>
  <p><strong>*</strong> Amazon columns model the sale price at <code>list_price x 0.85</code>
     and subtract estimated FBA and referral fees. Replacing the model with Keepa data is a
     drop-in change — the fee engine already accepts authoritative per-ASIN fees.</p>
</div>

<footer>Generated from a live scan · Phase 1 · retailer data real, Amazon data modelled</footer>
</div>
"""


def main(out="report.html", **kw):
    conn = db.init()
    open(out, "w").write(render(conn, **kw))
    return out


if __name__ == "__main__":
    print("wrote", main())

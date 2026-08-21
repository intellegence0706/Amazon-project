"""SQLite store. Chosen over Postgres for phase 1 so the demo runs with zero setup.

Migration path: the schema is plain SQL with no SQLite-specific types. Moving to
Postgres means swapping the connect() call and adding pg_trgm for fuzzy matching.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "arbitrage.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS retailers (
    id          INTEGER PRIMARY KEY,
    slug        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    host        TEXT NOT NULL,
    platform    TEXT NOT NULL,          -- shopify | woocommerce | feed | api | scrape
    tier        INTEGER NOT NULL,       -- 1 open catalog .. 4 paid scraping
    enabled     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS products (
    id            INTEGER PRIMARY KEY,
    retailer_id   INTEGER NOT NULL REFERENCES retailers(id),
    external_id   TEXT NOT NULL,        -- retailer's own variant id
    url           TEXT,
    title         TEXT NOT NULL,
    brand         TEXT,
    sku           TEXT,
    upc           TEXT,                 -- often NULL on tier-1 retailers
    pack_qty      INTEGER,              -- parsed from title; hard gate when matching
    grams         INTEGER,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    UNIQUE (retailer_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);
CREATE INDEX IF NOT EXISTS idx_products_upc   ON products(upc);

-- One row per observed price CHANGE, not per scan. Keeps the table small enough
-- that daily refreshes over years stay cheap.
CREATE TABLE IF NOT EXISTS price_snapshots (
    id           INTEGER PRIMARY KEY,
    product_id   INTEGER NOT NULL REFERENCES products(id),
    price        REAL NOT NULL,
    list_price   REAL,                  -- compare_at_price; > price means on sale
    in_stock     INTEGER NOT NULL,
    captured_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snap_product ON price_snapshots(product_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS amazon_products (
    asin           TEXT PRIMARY KEY,
    title          TEXT,
    brand          TEXT,
    upc            TEXT,
    buybox_price   REAL,
    offer_count    INTEGER,
    amazon_on_listing INTEGER,
    bsr            INTEGER,
    category       TEXT,
    fba_fee        REAL,                -- authoritative value comes from Keepa
    referral_pct   REAL,
    refreshed_at   TEXT
);

CREATE TABLE IF NOT EXISTS matches (
    id          INTEGER PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    asin        TEXT NOT NULL REFERENCES amazon_products(asin),
    confidence  REAL NOT NULL,
    method      TEXT NOT NULL,          -- upc | fuzzy | manual
    status      TEXT NOT NULL,          -- auto | pending | confirmed | rejected
    created_at  TEXT NOT NULL,
    UNIQUE (product_id, asin)
);
"""


def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init(path=DB_PATH):
    conn = connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn

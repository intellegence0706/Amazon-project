"""Data layer. SQLite locally, Postgres in serverless deployment.

Vercel's filesystem is ephemeral, so SQLite cannot persist there. Rather than
fork the codebase, both backends run the same SQL: SQLite 3.35+ supports
RETURNING, so inserts are identical, and only placeholder style and the
autoincrement declaration differ.

Selected by DATABASE_URL:
    unset                              -> SQLite at ./arbitrage.db
    postgres://... / postgresql://...  -> Postgres via psycopg3 (Supabase)

SUPABASE NOTE. Serverless functions must connect through the Supavisor pooler on
port 6543, not the direct connection on 5432 - every invocation opens its own
connection and a direct pool is exhausted quickly. Transaction-mode pooling also
forbids prepared statements, which psycopg3 starts using automatically after a
few executions, so prepared statements are disabled below. Without that, queries
begin failing only under load, which is the worst way to find out.
"""
import os
import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "arbitrage.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS retailers (
    id          {pk},
    slug        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    host        TEXT NOT NULL,
    platform    TEXT NOT NULL,
    tier        INTEGER NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS products (
    id            {pk},
    retailer_id   INTEGER NOT NULL REFERENCES retailers(id),
    external_id   TEXT NOT NULL,
    url           TEXT,
    title         TEXT NOT NULL,
    brand         TEXT,
    sku           TEXT,
    upc           TEXT,
    pack_qty      INTEGER,
    grams         INTEGER,
    image_url     TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    UNIQUE (retailer_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);
CREATE INDEX IF NOT EXISTS idx_products_upc   ON products(upc);
CREATE INDEX IF NOT EXISTS idx_products_ret   ON products(retailer_id);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id           {pk},
    product_id   INTEGER NOT NULL REFERENCES products(id),
    price        REAL NOT NULL,
    list_price   REAL,
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
    fba_fee        REAL,
    referral_pct   REAL,
    refreshed_at   TEXT
);

CREATE TABLE IF NOT EXISTS matches (
    id          {pk},
    product_id  INTEGER NOT NULL REFERENCES products(id),
    asin        TEXT NOT NULL REFERENCES amazon_products(asin),
    confidence  REAL NOT NULL,
    method      TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (product_id, asin)
);
"""

SCHEMA_SQLITE = _SCHEMA.format(pk="INTEGER PRIMARY KEY")
SCHEMA_PG = _SCHEMA.format(pk="INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY")


def database_url():
    return os.environ.get("DATABASE_URL", "").strip()


def is_postgres():
    return database_url().startswith(("postgres://", "postgresql://"))


# --------------------------------------------------------------- postgres shim
# Presents the sqlite3 surface the rest of the codebase already uses: execute()
# returns a cursor, rows behave like mappings, '?' placeholders work.

_PARAM = re.compile(r"\?(?=(?:[^']*'[^']*')*[^']*$)")


class Row(dict):
    """A row that works by name AND by position, like sqlite3.Row.

    psycopg's dict_row returns plain dicts, so row[0] raises KeyError - which is
    how this first surfaced, as a 500 on every endpoint once a real Postgres
    connection was in play. Supporting both styles here means call sites never
    have to care which backend they are talking to.
    """

    __slots__ = ()

    def __getitem__(self, key):
        if isinstance(key, int):
            try:
                return list(self.values())[key]
            except IndexError:
                raise IndexError(f"row has {len(self)} columns, asked for {key}") from None
        if isinstance(key, slice):
            return list(self.values())[key]
        return super().__getitem__(key)

    def keys(self):
        return list(super().keys())


def _row_factory(cursor):
    """psycopg row factory producing Row instances."""
    cols = [c.name for c in (cursor.description or [])]

    def make(values):
        return Row(zip(cols, values))

    return make


class _PGCursor:
    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)

    @property
    def lastrowid(self):
        row = self._cur.fetchone()
        return row["id"] if row else None


def pooled(url=None) -> bool:
    """True when pointed at Supabase's transaction-mode pooler."""
    u = url or database_url()
    return ":6543" in u or "pooler.supabase.com" in u


class _PGConnection:
    def __init__(self, dsn):
        import psycopg

        # Supabase requires TLS; add it if the URL does not already say so.
        if "sslmode=" not in dsn and "supabase" in dsn:
            dsn += ("&" if "?" in dsn else "?") + "sslmode=require"

        self._conn = psycopg.connect(
            dsn,
            row_factory=_row_factory,
            autocommit=False,
            # Transaction-mode pooling rejects prepared statements. Disabling
            # them costs a little planning time and avoids a class of failure
            # that only appears once traffic arrives.
            prepare_threshold=None,
            connect_timeout=10,
        )

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        cur.execute(_PARAM.sub("%s", sql), tuple(params))
        return _PGCursor(cur)

    def executescript(self, script):
        with self._conn.cursor() as cur:
            for stmt in filter(str.strip, script.split(";")):
                cur.execute(stmt)
        self._conn.commit()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


class BadDatabaseURL(RuntimeError):
    pass


def check_url(url):
    """Fail with a readable message rather than a Unicode traceback.

    A malformed DATABASE_URL surfaces deep inside the DNS resolver as
    "encoding with 'idna' codec failed", which says nothing useful. Checking
    the shape here costs nothing and turns it into an actionable error.
    """
    rest = url.split("://", 1)[-1]
    hostpart = rest.rsplit("@", 1)[-1].split("/")[0]
    host = hostpart.rsplit(":", 1)[0] if ":" in hostpart else hostpart

    if "..." in url or url.rstrip("/").endswith("://"):
        raise BadDatabaseURL(
            "DATABASE_URL still contains the example placeholder '...'.\n\n"
            "Use your real Supabase connection string, for example:\n"
            "  export DATABASE_URL='postgresql://postgres.PROJECTREF:PASSWORD"
            "@aws-1-REGION.pooler.supabase.com:6543/postgres'")

    if not host or "." not in host:
        raise BadDatabaseURL(
            f"DATABASE_URL has no valid host (got {host!r}).\n\n"
            "Expected: postgresql://USER:PASSWORD@HOST:6543/postgres\n"
            "Copy the 'Transaction pooler' string from "
            "Supabase → Settings → Database.")

    if "@" not in rest:
        raise BadDatabaseURL(
            "DATABASE_URL has no username or password.\n\n"
            "Expected: postgresql://USER:PASSWORD@HOST:6543/postgres")

    return True


def connect(path=DB_PATH):
    if is_postgres():
        check_url(database_url())
        return _PGConnection(database_url())
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# Columns added after the first release. CREATE TABLE IF NOT EXISTS will not
# add them to a database that already exists, so apply them separately.
_MIGRATIONS = [
    ("products", "image_url", "TEXT"),
]


def _migrate(conn):
    for table, column, coltype in _MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
            conn.commit()
        except Exception:                       # noqa: BLE001 - already present
            conn.rollback() if hasattr(conn, "rollback") else None


def init(path=DB_PATH):
    conn = connect(path)
    conn.executescript(SCHEMA_PG if is_postgres() else SCHEMA_SQLITE)
    conn.commit()
    _migrate(conn)
    return conn


# Kept for callers that imported it directly.
SCHEMA = SCHEMA_SQLITE

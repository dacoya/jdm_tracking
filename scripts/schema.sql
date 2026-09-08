-- tablero-cl canonical schema.
--
-- Design notes that matter for consumers (including the Android app):
--   * Prices are stored as REAL, already parsed. No consumer needs parse_price.
--   * `norm` (the cross-store matching key) is persisted, not recomputed. No
--     consumer needs to reimplement clean_title/normalize.
--   * Product identity is (store, url_canon) -- stable across scrapes, which is
--     what lets price_obs and the new/restock flags mean anything over time.
--   * A `game` row clusters products across stores. That cluster is the unit a
--     shopper actually cares about.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Stores
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS store (
    name      TEXT PRIMARY KEY,
    base_url  TEXT,
    city      TEXT,
    active    INTEGER NOT NULL DEFAULT 1
);

-- ---------------------------------------------------------------------------
-- Games: one row per distinct title cluster, shared across stores.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS game (
    id         INTEGER PRIMARY KEY,
    norm       TEXT    NOT NULL UNIQUE,
    title      TEXT    NOT NULL,
    kind       TEXT    NOT NULL DEFAULT 'game',
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_game_kind ON game(kind);

-- ---------------------------------------------------------------------------
-- Products: one row per (store, canonical URL).
--
-- price_eff is maintained by the writer rather than declared GENERATED so the
-- schema stays loadable on older SQLite builds (generated columns need 3.31+,
-- and Android ships whatever the OS ships).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product (
    id             INTEGER PRIMARY KEY,
    store          TEXT    NOT NULL REFERENCES store(name) ON DELETE CASCADE,
    url_canon      TEXT    NOT NULL,
    url            TEXT    NOT NULL,
    game_id        INTEGER REFERENCES game(id) ON DELETE SET NULL,
    title_raw      TEXT    NOT NULL,
    title          TEXT    NOT NULL,
    norm           TEXT    NOT NULL,
    kind           TEXT    NOT NULL DEFAULT 'game',
    price_original REAL,
    price_current  REAL,
    price_eff      REAL,
    in_stock       INTEGER,
    flag           TEXT CHECK (flag IN ('new', 'restock') OR flag IS NULL),
    first_seen     INTEGER NOT NULL,
    last_seen      INTEGER NOT NULL,
    UNIQUE (store, url_canon)
);

CREATE INDEX IF NOT EXISTS idx_product_game  ON product(game_id);
CREATE INDEX IF NOT EXISTS idx_product_store ON product(store);
CREATE INDEX IF NOT EXISTS idx_product_price ON product(price_eff);
CREATE INDEX IF NOT EXISTS idx_product_norm  ON product(norm);
CREATE INDEX IF NOT EXISTS idx_product_kind  ON product(kind);
CREATE INDEX IF NOT EXISTS idx_product_flag  ON product(flag) WHERE flag IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Price observations, keyed on the stable product id.
--
-- The legacy history.json keyed on "norm|store", which collides whenever two
-- distinct products in one store normalize to the same string -- 77 series in
-- the old file had duplicate timestamps and meaningless trend lines.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS price_obs (
    product_id INTEGER NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    ts         INTEGER NOT NULL,
    price      REAL    NOT NULL,
    PRIMARY KEY (product_id, ts)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_price_obs_ts ON price_obs(ts);

-- ---------------------------------------------------------------------------
-- Scrape bookkeeping (replaces metadata.json["sites"]).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scrape_run (
    store      TEXT    NOT NULL,
    ts         INTEGER NOT NULL,
    n_products INTEGER,
    success    INTEGER NOT NULL,
    PRIMARY KEY (store, ts)
) WITHOUT ROWID;

-- ---------------------------------------------------------------------------
-- Watchlist / favourites. Replaces the ephemeral --watch flag.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS watchlist (
    game_id  INTEGER PRIMARY KEY REFERENCES game(id) ON DELETE CASCADE,
    target   REAL,
    note     TEXT,
    added_at INTEGER NOT NULL
);

-- ---------------------------------------------------------------------------
-- Named read cursors, so "since I last looked" is answerable.
--
-- The `flag` column on product only survives one update cycle; it means
-- "changed in the most recent scrape", not "changed since you last looked".
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cursor (
    name TEXT    PRIMARY KEY,
    ts   INTEGER NOT NULL
);

-- ---------------------------------------------------------------------------
-- Full-text search over product titles.
-- ---------------------------------------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS product_fts USING fts5(
    norm,
    title,
    content = 'product',
    content_rowid = 'id',
    tokenize = 'unicode61'
);

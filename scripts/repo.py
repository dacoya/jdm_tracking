"""
Query layer. All SQL lives here.

Every function takes a connection and returns plain JSON-serializable data
(``list[dict]`` / ``dict``) -- never a DataFrame, never printed output. That is
what makes the same queries reusable by the terminal today and by an HTTP or
export layer later without touching this module.
"""
import re

# A product is stale when its store was scraped successfully more recently than
# the product was last seen -- it was delisted, or its URL changed. Such rows
# keep their last known price and would otherwise still be offered as live
# deals; 152 games had their advertised "desde" price set by one.
#
# They are excluded from queries rather than deleted, so their price history
# survives and a store that merely served a bad page recovers on the next run.
STALE_CLAUSE = """
    p.last_seen >= COALESCE(
        (SELECT MAX(r.ts) FROM scrape_run r WHERE r.store = p.store AND r.success = 1),
        p.last_seen
    )
"""


# FTS5 treats a lot of punctuation as syntax. User input is reduced to bare
# alphanumeric tokens before it ever reaches MATCH, so a stray quote or NEAR
# cannot alter the query's meaning.
_FTS_TOKEN = re.compile(r"[^\w]+", re.UNICODE)


def fts_query(text: str) -> str:
    """Build a safe FTS5 prefix query from free-form user input."""
    tokens = [t for t in _FTS_TOKEN.split(text or "") if t]
    return " ".join(f'"{t}"*' for t in tokens)


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------

def _game_agg(include_stale: bool = False) -> str:
    """
    Per-game aggregate. Stale rows are joined out by default so the advertised
    "desde" price and store count reflect offers that actually still exist.
    """
    stale = "" if include_stale else f" AND {STALE_CLAUSE}"
    return f"""
    SELECT g.id            AS game_id,
           g.norm          AS norm,
           g.title         AS title,
           g.kind          AS kind,
           COUNT(DISTINCT p.store)                        AS n_stores,
           MIN(NULLIF(p.price_eff, 0))                    AS min_price,
           MAX(p.in_stock)                                AS in_stock,
           MAX(CASE WHEN p.flag = 'new' THEN 1 ELSE 0 END)     AS is_new,
           MAX(CASE WHEN p.flag = 'restock' THEN 1 ELSE 0 END) AS is_restock
      FROM game g
      JOIN product p ON p.game_id = g.id{stale}
"""


def candidate_games(conn, query: str, pool: int = 400,
                    include_stale: bool = False) -> list[dict]:
    """
    Games whose title matches `query`, for ranking by the caller.

    Deliberately over-fetches: FTS decides only what is *plausible*, and the
    ranker decides what is *relevant*. Matching on the product index rather than
    game titles alone means a game is still found when only one store spells it
    in full.
    """
    match = fts_query(query)
    if not match:
        return []

    sql = f"""
        {_game_agg(include_stale)}
         WHERE g.id IN (
               SELECT DISTINCT p2.game_id
                 FROM product_fts f
                 JOIN product p2 ON p2.id = f.rowid
                WHERE product_fts MATCH ?
                  AND p2.game_id IS NOT NULL
               LIMIT ?
         )
         GROUP BY g.id
    """
    return [dict(r) for r in conn.execute(sql, (match, pool))]


def games_by_ids(conn, ids, include_stale: bool = False) -> list[dict]:
    """Per-game aggregates for a set of ids."""
    ids = list(ids)
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    sql = f"{_game_agg(include_stale)} WHERE g.id IN ({placeholders}) GROUP BY g.id"
    return [dict(r) for r in conn.execute(sql, ids)]


def game_norms(conn) -> list[tuple[int, str]]:
    """
    Every (game_id, norm) pair -- the search space for typo-tolerant fallback.

    Kept deliberately narrow (two columns over ~11k games, not ~29k products)
    so a full fuzzy scan stays cheap when FTS cannot bridge a misspelling.
    """
    return [(r[0], r[1]) for r in conn.execute("SELECT id, norm FROM game")]


def game_prices(conn, game_id: int, include_stale: bool = False) -> list[dict]:
    """Per-store offers for one game, cheapest first."""
    stale = "" if include_stale else f" AND {STALE_CLAUSE}"
    sql = f"""
        SELECT {_PRODUCT_COLS}
          FROM product p
         WHERE p.game_id = ?{stale}
         ORDER BY (p.price_eff IS NULL), p.price_eff
    """
    return [dict(r) for r in conn.execute(sql, (game_id,))]


# ---------------------------------------------------------------------------
# Browsing: deals and catalog
# ---------------------------------------------------------------------------


def _filters(store=None, in_stock_only=False, min_price=None, max_price=None,
             on_sale=False, flag=None, kind=None, include_stale=False):
    """Compose an SQL WHERE fragment plus bound parameters."""
    clauses, params = ["1=1"], []
    if not include_stale:
        clauses.append(STALE_CLAUSE)
    if store:
        clauses.append("p.store = ?")
        params.append(store)
    if kind:
        kinds = [kind] if isinstance(kind, str) else list(kind)
        clauses.append(f"p.kind IN ({','.join('?' * len(kinds))})")
        params.extend(kinds)
    if in_stock_only:
        clauses.append("p.in_stock = 1")
    if min_price is not None:
        clauses.append("p.price_eff >= ?")
        params.append(float(min_price))
    if max_price is not None:
        clauses.append("p.price_eff <= ?")
        params.append(float(max_price))
    if on_sale:
        clauses.append("p.price_current IS NOT NULL AND p.price_original > p.price_current")
    if flag:
        clauses.append("p.flag = ?")
        params.append(flag)
    return " AND ".join(clauses), params


# Single definition of the discount expression, shared with analytics.py so the
# two cannot drift apart.
DISCOUNT_PCT_SQL = """
    CASE WHEN p.price_current IS NOT NULL AND p.price_original > 0
              AND p.price_original > p.price_current
         THEN ROUND((p.price_original - p.price_current) * 100.0 / p.price_original, 1)
    END
"""

_PRODUCT_COLS = f"""
    p.id AS product_id, p.store, p.title, p.url, p.game_id, p.kind,
    p.price_original, p.price_current, p.price_eff, p.in_stock, p.flag,
    {DISCOUNT_PCT_SQL} AS discount_pct
"""

_ORDER_BY = {
    "discount": "discount_pct DESC NULLS LAST, p.price_eff",
    "price":    "(p.price_eff IS NULL), p.price_eff",
    "price_desc": "p.price_eff DESC NULLS LAST",
    "store":    "p.store, p.title",
    "title":    "p.title",
}


def products(conn, sort="discount", limit=None, offset=0, **filters) -> list[dict]:
    """Filtered product rows. `sort` must be a key of _ORDER_BY."""
    if sort not in _ORDER_BY:
        raise ValueError(f"Unknown sort '{sort}'. Valid: {', '.join(sorted(_ORDER_BY))}")

    where, params = _filters(**filters)
    sql = f"SELECT {_PRODUCT_COLS} FROM product p WHERE {where} ORDER BY {_ORDER_BY[sort]}"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params += [int(limit), int(offset)]
    return [dict(r) for r in conn.execute(sql, params)]


def count_products(conn, **filters) -> int:
    """Row count under the same filters `products` applies."""
    where, params = _filters(**filters)
    return conn.execute(f"SELECT COUNT(*) FROM product p WHERE {where}", params).fetchone()[0]


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------

def stores(conn, active_only: bool = False) -> list[dict]:
    """Every store with its product counts and last scrape time."""
    sql = """
        SELECT s.name, s.base_url, s.city, s.active,
               COUNT(p.id) AS n_products,
               SUM(COALESCE(p.in_stock, 0)) AS n_in_stock,
               (SELECT MAX(ts) FROM scrape_run r WHERE r.store = s.name) AS last_scrape
          FROM store s
          LEFT JOIN product p ON p.store = s.name
    """
    if active_only:
        sql += " WHERE s.active = 1"
    sql += " GROUP BY s.name ORDER BY s.name"
    return [dict(r) for r in conn.execute(sql)]


def store_names(conn, active_only: bool = True) -> list[str]:
    """Just the names, for pickers and validation."""
    sql = "SELECT name FROM store"
    if active_only:
        sql += " WHERE active = 1"
    return [r[0] for r in conn.execute(sql + " ORDER BY name")]


def fresh_stores(conn, cutoff_ts: int) -> set[str]:
    """Stores with a successful scrape at or after `cutoff_ts`."""
    return {
        r[0] for r in conn.execute(
            "SELECT store FROM scrape_run WHERE success = 1 "
            "GROUP BY store HAVING MAX(ts) >= ?",
            (int(cutoff_ts),),
        )
    }


def products_without_price(conn) -> int:
    """Rows carrying no usable price -- surfaced by `tablero doctor`."""
    return conn.execute(
        "SELECT COUNT(*) FROM product WHERE price_eff IS NULL").fetchone()[0]


def stale_count(conn) -> int:
    """Products missing from their store's most recent successful scrape."""
    return conn.execute(
        f"SELECT COUNT(*) FROM product p WHERE NOT ({STALE_CLAUSE})").fetchone()[0]


def resolve_store(conn, text: str) -> list[str]:
    """
    Store names matching `text` case-insensitively (exact first, else substring).

    The old CLI required an exact `--store` string and errored without listing
    the valid names; this lets the caller accept partial input or show options.
    """
    if not text:
        return []
    needle = text.strip().lower()
    names = store_names(conn, active_only=False)
    exact = [n for n in names if n.lower() == needle]
    return exact or [n for n in names if needle in n.lower()]


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

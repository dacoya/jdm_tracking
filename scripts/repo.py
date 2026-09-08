"""
Query layer. All SQL lives here.

Every function takes a connection and returns plain JSON-serializable data
(``list[dict]`` / ``dict``) -- never a DataFrame, never printed output. That is
what makes the same queries reusable by the terminal today and by an HTTP or
export layer later without touching this module.
"""
import re

OUT_OF_STOCK = "agotado"

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

_GAME_AGG = """
    SELECT g.id            AS game_id,
           g.norm          AS norm,
           g.title         AS title,
           g.kind          AS kind,
           COUNT(DISTINCT p.store)                        AS n_stores,
           MIN(NULLIF(p.price_eff, 0))                    AS min_price,
           MAX(p.in_stock)                                AS in_stock,
           MAX(CASE WHEN p.flag IS NOT NULL THEN 1 ELSE 0 END) AS changed
      FROM game g
      JOIN product p ON p.game_id = g.id
"""


def candidate_games(conn, query: str, pool: int = 400) -> list[dict]:
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
        {_GAME_AGG}
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


def game_by_id(conn, game_id: int) -> dict | None:
    row = conn.execute(f"{_GAME_AGG} WHERE g.id = ? GROUP BY g.id", (game_id,)).fetchone()
    return dict(row) if row else None


def games_by_ids(conn, ids) -> list[dict]:
    ids = list(ids)
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    sql = f"{_GAME_AGG} WHERE g.id IN ({placeholders}) GROUP BY g.id"
    return [dict(r) for r in conn.execute(sql, ids)]


def game_norms(conn, kinds=None) -> list[tuple[int, str]]:
    """
    Every (game_id, norm) pair -- the search space for typo-tolerant fallback.

    Kept deliberately narrow (two columns over ~11k games, not ~29k products)
    so a full fuzzy scan stays cheap when FTS cannot bridge a misspelling.
    """
    sql = "SELECT id, norm FROM game"
    params: list = []
    if kinds:
        kinds = list(kinds)
        sql += f" WHERE kind IN ({','.join('?' * len(kinds))})"
        params = kinds
    return [(r[0], r[1]) for r in conn.execute(sql, params)]


def game_prices(conn, game_id: int) -> list[dict]:
    """Per-store offers for one game, cheapest first."""
    sql = f"""
        SELECT {_PRODUCT_COLS}
          FROM product p
         WHERE p.game_id = ?
         ORDER BY (p.price_eff IS NULL), p.price_eff
    """
    return [dict(r) for r in conn.execute(sql, (game_id,))]


# ---------------------------------------------------------------------------
# Browsing: deals and catalog
# ---------------------------------------------------------------------------

def _filters(store=None, in_stock_only=False, min_price=None, max_price=None,
             on_sale=False, flag=None, kind=None):
    """Compose an SQL WHERE fragment plus bound parameters."""
    clauses, params = ["1=1"], []
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


_PRODUCT_COLS = """
    p.id AS product_id, p.store, p.title, p.url, p.game_id, p.kind,
    p.price_original, p.price_current, p.price_eff, p.in_stock, p.flag,
    CASE WHEN p.price_current IS NOT NULL AND p.price_original > 0
              AND p.price_original > p.price_current
         THEN ROUND((p.price_original - p.price_current) * 100.0 / p.price_original, 1)
    END AS discount_pct
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
    where, params = _filters(**filters)
    return conn.execute(f"SELECT COUNT(*) FROM product p WHERE {where}", params).fetchone()[0]


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------

def stores(conn, active_only: bool = False) -> list[dict]:
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
    sql = "SELECT name FROM store"
    if active_only:
        sql += " WHERE active = 1"
    return [r[0] for r in conn.execute(sql + " ORDER BY name")]


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

def price_series(conn, game_id: int) -> dict[str, list[dict]]:
    """Price observations for a game, grouped by store and ordered by time."""
    sql = """
        SELECT p.store, o.ts, o.price
          FROM price_obs o
          JOIN product p ON p.id = o.product_id
         WHERE p.game_id = ?
         ORDER BY p.store, o.ts
    """
    out: dict[str, list[dict]] = {}
    for r in conn.execute(sql, (game_id,)):
        out.setdefault(r["store"], []).append({"ts": r["ts"], "price": r["price"]})
    return out

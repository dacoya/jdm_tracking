"""
Derived rankings: smart sorts and the store leaderboard.

Rewritten over SQL. The previous version operated on DataFrames and re-parsed
price strings on every row; prices are numeric on disk now, so converting them
back into "$45.990" just to re-parse would be pure waste.

SQLite has no median aggregate, so the median-per-game CTE below picks the
middle row(s) by ROW_NUMBER and averages them -- correct for both odd and even
counts. Median matters here rather than mean: one absurdly-priced listing should
not redefine what a game "normally" costs.

Pure: connection in, list[dict] out. Nothing prints.
"""
try:
    from . import repo
except ImportError:
    import repo

SMART_SORT_OPTIONS = ("value", "scarcity", "volatility")

# Median effective price per game, over rows with a usable price.
_MEDIAN_CTE = """
    WITH priced AS (
        SELECT id, game_id, store, price_eff, in_stock,
               ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY price_eff) AS rn,
               COUNT(*)     OVER (PARTITION BY game_id)                    AS cnt
          FROM product
         WHERE price_eff IS NOT NULL AND price_eff > 0
    ),
    med AS (
        SELECT game_id, AVG(price_eff) AS median
          FROM priced
         WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
         GROUP BY game_id
    ),
    spread AS (
        SELECT game_id,
               MIN(price_eff) AS lo,
               MAX(price_eff) AS hi,
               COUNT(DISTINCT store) AS n_stores
          FROM priced
         GROUP BY game_id
    )
"""

# Each smart sort scores a row; all are ordered descending by that score.
_SCORE = {
    # Cheap relative to the game's own median, with a bonus for being buyable.
    "value": "((m.median - p.price_eff) / m.median) + (CASE WHEN p.in_stock THEN 0.5 ELSE 0 END)",
    # Carried by few stores: concentrated availability.
    "scarcity": "-s.n_stores",
    # Wide cross-store spread: the same game costs very different amounts.
    "volatility": "(s.hi - s.lo) / m.median",
}


def smart_products(conn, by: str = "value", limit: int | None = None,
                   store: str | None = None, in_stock_only: bool = False,
                   kind=None, on_sale: bool = False,
                   min_price=None, max_price=None,
                   include_stale: bool = False) -> list[dict]:
    """
    Products ranked by a derived metric rather than a single column.

    Takes the same filters as `repo.products`. It previously accepted no price
    bounds at all, so `--max-price` was silently dropped whenever a smart sort
    was chosen and the output contradicted the flag the user had passed.
    """
    if by not in SMART_SORT_OPTIONS:
        raise ValueError(
            f"Unknown smart sort '{by}'. Options: {', '.join(SMART_SORT_OPTIONS)}")

    clauses, params = ["m.median > 0"], []
    if not include_stale:
        clauses.append(repo.STALE_CLAUSE)
    if store:
        clauses.append("p.store = ?")
        params.append(store)
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
    if kind:
        kinds = [kind] if isinstance(kind, str) else list(kind)
        clauses.append(f"p.kind IN ({','.join('?' * len(kinds))})")
        params.extend(kinds)

    sql = f"""
        {_MEDIAN_CTE}
        SELECT p.id AS product_id, p.store, p.title, p.url, p.game_id, p.kind,
               p.price_original, p.price_current, p.price_eff, p.in_stock, p.flag,
               s.n_stores, m.median,
               {repo.DISCOUNT_PCT_SQL} AS discount_pct,
               ROUND({_SCORE[by]}, 4) AS score
          FROM product p
          JOIN med    m ON m.game_id = p.game_id
          JOIN spread s ON s.game_id = p.game_id
         WHERE {' AND '.join(clauses)}
         ORDER BY score DESC
    """
    # limit=None means "everything", the same contract as repo.products.
    if limit is not None:
        sql += " LIMIT ?"
        params = [*params, int(limit)]
    return [dict(r) for r in conn.execute(sql, params)]


def store_leaderboard(conn, limit: int | None = None) -> list[dict]:
    """
    Stores ranked cheapest-first.

    `competitiveness` is the share of contested games (those a store shares with
    at least one other) where this store is priced above the cross-store median.
    Lower is cheaper. Comparing only contested games is what stops a store
    looking cheap merely by stocking different, cheaper products.
    """
    sql = f"""
        {_MEDIAN_CTE},
        contested AS (
            SELECT p.store, p.price_eff, m.median
              FROM priced p
              JOIN med    m ON m.game_id = p.game_id
              JOIN spread s ON s.game_id = p.game_id
             WHERE s.n_stores > 1
        ),
        comp AS (
            SELECT store,
                   COUNT(*) AS n_contested,
                   AVG(CASE WHEN price_eff > median THEN 1.0 ELSE 0.0 END) AS competitiveness
              FROM contested
             GROUP BY store
        ),
        totals AS (
            SELECT store,
                   COUNT(*) AS n,
                   AVG(CASE WHEN in_stock = 0 THEN 1.0 ELSE 0.0 END) AS oos_ratio,
                   AVG(CASE WHEN price_current IS NOT NULL AND price_original > 0
                                 AND price_original > price_current
                            THEN (price_original - price_current) / price_original
                            ELSE 0.0 END) AS mean_discount
              FROM product
             GROUP BY store
        ),
        medians AS (
            SELECT store, AVG(price_eff) AS median_price FROM (
                SELECT store, price_eff,
                       ROW_NUMBER() OVER (PARTITION BY store ORDER BY price_eff) rn,
                       COUNT(*)     OVER (PARTITION BY store)                   cnt
                  FROM product
                 WHERE price_eff IS NOT NULL AND price_eff > 0
            ) WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
            GROUP BY store
        )
        SELECT t.store, t.n, t.oos_ratio, t.mean_discount,
               md.median_price, c.competitiveness, c.n_contested
          FROM totals t
          LEFT JOIN comp    c  ON c.store  = t.store
          LEFT JOIN medians md ON md.store = t.store
         WHERE t.n > 0
         ORDER BY (c.competitiveness IS NULL), c.competitiveness, md.median_price
    """
    rows = [dict(r) for r in conn.execute(sql)]
    return rows[:limit] if limit else rows

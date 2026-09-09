"""
"What changed since I last looked."

The `flag` column on product only survives one update cycle -- it means
"changed in the most recent scrape", so anything missed while away is gone for
good. These queries work off recorded price observations and a named cursor
instead, which makes the answer independent of how many scrapes have run.

Cursors are named so several consumers can each keep their own position (the
terminal and the phone should not clobber each other's "last seen").
"""
import time

DEFAULT_CURSOR = "last_reviewed"


def get_cursor(conn, name: str = DEFAULT_CURSOR) -> int | None:
    row = conn.execute("SELECT ts FROM cursor WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def set_cursor(conn, ts: int | None = None, name: str = DEFAULT_CURSOR) -> int:
    ts = int(ts if ts is not None else time.time())
    conn.execute(
        "INSERT INTO cursor(name, ts) VALUES (?,?) "
        "ON CONFLICT(name) DO UPDATE SET ts=excluded.ts",
        (name, ts),
    )
    conn.commit()
    return ts


def _limit(limit) -> int:
    """SQL bind value for `limit`; None means no limit (SQLite reads -1 that way)."""
    return -1 if limit is None else int(limit)


def price_drops(conn, since: int | None = None, name: str = DEFAULT_CURSOR,
                min_pct: float = 5.0, limit: int | None = 100) -> list[dict]:
    """
    Products whose price fell since `since` (default: the stored cursor).

    Compares the newest observation at or after the cutoff with the newest one
    before it, so a drop is measured against what the price actually was when
    you last looked -- not against the list price the store advertises.

    `min_pct` filters out rounding noise and tiny fluctuations.
    """
    since = since if since is not None else get_cursor(conn, name)
    if since is None:
        return []

    sql = """
        WITH before AS (
            SELECT product_id, price, ts,
                   ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY ts DESC) rn
              FROM price_obs WHERE ts < ?
        ), after AS (
            SELECT product_id, price, ts,
                   ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY ts DESC) rn
              FROM price_obs WHERE ts >= ?
        )
        SELECT p.id AS product_id, p.store, p.title, p.url, p.game_id, p.kind,
               p.in_stock,
               b.price AS old_price, a.price AS new_price, a.ts AS seen_at,
               ROUND((b.price - a.price) * 100.0 / b.price, 1) AS drop_pct
          FROM after a
          JOIN before b ON b.product_id = a.product_id AND b.rn = 1
          JOIN product p ON p.id = a.product_id
         WHERE a.rn = 1
           AND b.price > 0
           AND a.price < b.price
           AND (b.price - a.price) * 100.0 / b.price >= ?
         ORDER BY drop_pct DESC
         LIMIT ?
    """
    return [dict(r) for r in conn.execute(sql, (since, since, float(min_pct), _limit(limit)))]


def new_arrivals(conn, since: int | None = None, name: str = DEFAULT_CURSOR,
                 limit: int | None = 100) -> list[dict]:
    """Products first seen at or after the cutoff."""
    since = since if since is not None else get_cursor(conn, name)
    if since is None:
        return []
    sql = """
        SELECT id AS product_id, store, title, url, game_id, kind,
               price_eff, in_stock, first_seen
          FROM product
         WHERE first_seen >= ?
         ORDER BY first_seen DESC, store
         LIMIT ?
    """
    return [dict(r) for r in conn.execute(sql, (since, _limit(limit)))]

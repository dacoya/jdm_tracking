"""
Persistent watchlist / favourites.

Replaces the ephemeral ``--watch`` flag, which had to be retyped on every
invocation and could not be shared with the TUI, a cron job, or the phone.

A watched row optionally carries a target price; `hits` reports the entries
currently at or below their target.
"""
import time


def add(conn, game_id: int, target: float | None = None, note: str | None = None) -> bool:
    """Add or update a watch. True when the game exists and was stored."""
    if not conn.execute("SELECT 1 FROM game WHERE id = ?", (game_id,)).fetchone():
        return False
    conn.execute(
        """INSERT INTO watchlist(game_id, target, note, added_at) VALUES (?,?,?,?)
           ON CONFLICT(game_id) DO UPDATE SET target=excluded.target, note=excluded.note""",
        (game_id, target, note, int(time.time())),
    )
    conn.commit()
    return True


def remove(conn, game_id: int) -> bool:
    cur = conn.execute("DELETE FROM watchlist WHERE game_id = ?", (game_id,))
    conn.commit()
    return cur.rowcount > 0


def game_ids(conn) -> list[int]:
    return [r[0] for r in conn.execute("SELECT game_id FROM watchlist ORDER BY added_at")]


def entries(conn) -> list[dict]:
    """Watched games enriched with current cheapest price and stock."""
    sql = """
        SELECT w.game_id, w.target, w.note, w.added_at,
               g.title, g.kind,
               MIN(NULLIF(p.price_eff, 0)) AS min_price,
               COUNT(DISTINCT p.store)     AS n_stores,
               MAX(p.in_stock)             AS in_stock
          FROM watchlist w
          JOIN game g    ON g.id = w.game_id
          LEFT JOIN product p ON p.game_id = g.id
         GROUP BY w.game_id
         ORDER BY w.added_at
    """
    rows = []
    for r in conn.execute(sql):
        row = dict(r)
        target, price = row.get("target"), row.get("min_price")
        row["hit"] = bool(target and price and price <= target)
        rows.append(row)
    return rows

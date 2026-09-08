"""
Price history over recorded observations.

Rewritten against the price_obs table. The previous version read a JSON file
keyed on "norm|store", which collided whenever two distinct products in one
store normalised to the same string -- 77 series in the old file had duplicate
timestamps and meaningless trend lines. Keying on product id removes the
ambiguity entirely.

Pure: connection in, plain data out. `sparkline` is the one presentation piece
and takes a plain list, so it stays usable anywhere.
"""
_SPARK_BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values: list) -> str:
    """Render a list of numbers as an ASCII sparkline (▁▂▃▄▅▆▇█)."""
    nums = [v for v in values if v is not None]
    if not nums:
        return ""
    lo, hi = min(nums), max(nums)
    if hi == lo:
        return _SPARK_BLOCKS[0] * len(nums)
    span = hi - lo
    return "".join(
        _SPARK_BLOCKS[int((v - lo) / span * (len(_SPARK_BLOCKS) - 1))] for v in nums
    )


def _summarise(store: str, points: list) -> dict:
    prices = [p["price"] for p in points]
    first, last = prices[0], prices[-1]
    return {
        "store": store,
        "first": first,
        "last": last,
        "min": min(prices),
        "max": max(prices),
        "change_pct": ((last - first) / first * 100) if first else 0.0,
        "n": len(prices),
        "spark": sparkline(prices),
        "points": points,
    }


def game_trends(conn, game_id: int, min_points: int = 1) -> list[dict]:
    """
    Per-store price trends for a game, most-moved first.

    `min_points` hides stores observed only once: a single point is a price, not
    a trend, and showing it as a flat line implies stability that was never
    measured.
    """
    sql = """
        SELECT p.store, o.ts, o.price
          FROM price_obs o
          JOIN product p ON p.id = o.product_id
         WHERE p.game_id = ?
         ORDER BY p.store, o.ts
    """
    by_store: dict[str, list] = {}
    for row in conn.execute(sql, (game_id,)):
        by_store.setdefault(row["store"], []).append(
            {"ts": row["ts"], "price": row["price"]}
        )

    trends = [
        _summarise(store, points)
        for store, points in by_store.items()
        if len(points) >= min_points
    ]
    trends.sort(key=lambda t: abs(t["change_pct"]), reverse=True)
    return trends


def observation_span(conn) -> dict:
    """Oldest and newest observation, so callers can say how deep history goes."""
    row = conn.execute(
        "SELECT MIN(ts) AS first, MAX(ts) AS last, COUNT(*) AS n FROM price_obs"
    ).fetchone()
    return dict(row) if row else {"first": None, "last": None, "n": 0}

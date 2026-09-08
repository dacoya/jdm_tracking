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


def _summarise(store: str, label: str, points: list) -> dict:
    prices = [p["price"] for p in points]
    first, last = prices[0], prices[-1]
    return {
        "store": store,
        "label": label,
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
    Price trends for a game, most-moved first, one series per listing.

    Grouped by product, not by store. A store can list the same game more than
    once (a reissue, a second edition, a changed URL); grouping those together
    concatenated unrelated prices into a single line and invented a trend --
    Terraforming Mars showed "+175%" purely from two different listings being
    stitched end to end. Where a store does have several listings, the label
    disambiguates them.
    """
    sql = """
        SELECT p.id AS product_id, p.store, p.title, o.ts, o.price
          FROM price_obs o
          JOIN product p ON p.id = o.product_id
         WHERE p.game_id = ?
         ORDER BY p.store, p.id, o.ts
    """
    series: dict[int, dict] = {}
    for row in conn.execute(sql, (game_id,)):
        entry = series.setdefault(
            row["product_id"],
            {"store": row["store"], "title": row["title"], "points": []},
        )
        entry["points"].append({"ts": row["ts"], "price": row["price"]})

    per_store: dict[str, int] = {}
    for entry in series.values():
        per_store[entry["store"]] = per_store.get(entry["store"], 0) + 1

    trends = [
        _summarise(
            entry["store"],
            # Only qualify the label when it is actually ambiguous.
            entry["store"] if per_store[entry["store"]] == 1
            else f"{entry['store']} · {entry['title']}",
            entry["points"],
        )
        for entry in series.values()
        if len(entry["points"]) >= min_points
    ]
    trends.sort(key=lambda t: abs(t["change_pct"]), reverse=True)
    return trends


def observation_span(conn) -> dict:
    """Oldest and newest observation, so callers can say how deep history goes."""
    row = conn.execute(
        "SELECT MIN(ts) AS first, MAX(ts) AS last, COUNT(*) AS n FROM price_obs"
    ).fetchone()
    return dict(row) if row else {"first": None, "last": None, "n": 0}

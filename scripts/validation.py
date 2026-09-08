"""
Price sanity checks, applied at ingest.

Stores publish impossible prices: a "sale" above the list price, a $0 listing, a
99% discount that is really a data-entry slip. Letting those in corrupts the
cross-store median, which in turn corrupts every derived ranking.

Rewritten to work on the numeric rows `derive` produces rather than on
DataFrames of price strings.

Deliberately limited to rules that are decidable from a single row. The old
version also dropped rows more than 5 sigma from a game's median, which is not
safe as a silent filter: the whole point of this tool is finding the one store
selling something far below everyone else. Statistical outliers are surfaced by
`tablero doctor` instead of being discarded.
"""
MAX_PLAUSIBLE_DISCOUNT = 0.90


def check(row: dict) -> str | None:
    """Return a rejection reason for a derived row, or None when it is sane."""
    original = row.get("price_original")
    current = row.get("price_current")

    if original is not None and original <= 0:
        return "nonpositive_original"
    if current is not None and current <= 0:
        return "nonpositive_current"
    if original is None and current is None:
        return "no_price"
    if original is not None and current is not None:
        if current > original:
            return "offer_above_original"
        if original > 0 and (original - current) / original > MAX_PLAUSIBLE_DISCOUNT:
            return "discount_over_90pct"
    return None


def partition(rows: list) -> tuple[list, dict]:
    """
    Split rows into (clean, {reason: count}).

    Counts rather than the rejected rows themselves: the caller reports totals,
    and keeping thousands of bad rows around to print one summary line is waste.
    """
    clean, reasons = [], {}
    for row in rows:
        reason = check(row)
        if reason is None:
            clean.append(row)
        else:
            reasons[reason] = reasons.get(reason, 0) + 1
    return clean, reasons


def price_outliers(conn, sigma: float = 5.0, limit: int = 50) -> list[dict]:
    """
    Products far from their game's mean price -- reported, never auto-dropped.

    A genuine bargain and a data error look identical here, so this is a
    "look at these" list, not a filter.
    """
    sql = """
        WITH stats AS (
            SELECT game_id,
                   AVG(price_eff) AS mean,
                   COUNT(*)       AS n,
                   AVG(price_eff * price_eff) - AVG(price_eff) * AVG(price_eff) AS var
              FROM product
             WHERE price_eff IS NOT NULL AND price_eff > 0
             GROUP BY game_id
            HAVING COUNT(*) >= 3
        )
        SELECT p.id AS product_id, p.store, p.title, p.url, p.price_eff,
               s.mean, s.n,
               ROUND(ABS(p.price_eff - s.mean) / NULLIF(SQRT(s.var), 0), 1) AS sigmas
          FROM product p
          JOIN stats s ON s.game_id = p.game_id
         WHERE s.var > 0
           AND ABS(p.price_eff - s.mean) / SQRT(s.var) > ?
         ORDER BY sigmas DESC
         LIMIT ?
    """
    return [dict(r) for r in conn.execute(sql, (float(sigma), int(limit)))]

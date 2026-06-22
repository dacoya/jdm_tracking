"""
Per-store price statistics and a market-wide summary.

Powers contextual renders ("Devir: +18% caro vs mediana") and the store
leaderboard.  Prices are parsed from the raw Chilean-format strings; the
*effective* price of a row is its current (sale) price when present, else the
original price.
"""
import pandas as pd

try:
    from .utils import parse_price
except ImportError:
    from utils import parse_price


def effective_price(df: pd.DataFrame) -> pd.Series:
    """Series of effective prices (current if present, else original)."""
    n = len(df)
    orig = (df["original_price"] if "original_price" in df else pd.Series([None] * n, index=df.index)).apply(parse_price)
    curr = (df["current_price"] if "current_price" in df else pd.Series([None] * n, index=df.index)).apply(parse_price)
    return curr.where(curr.notna(), orig)


def _discount(df: pd.DataFrame) -> pd.Series:
    """Fractional discount per row (0 when no valid sale price)."""
    orig = (df["original_price"] if "original_price" in df else pd.Series([None] * len(df), index=df.index)).apply(parse_price)
    curr = (df["current_price"] if "current_price" in df else pd.Series([None] * len(df), index=df.index)).apply(parse_price)
    disc = 1 - (curr / orig)
    return disc.where(orig.notna() & curr.notna() & (orig > 0) & (disc > 0), 0.0)


def price_stats_per_store(df: pd.DataFrame) -> dict:
    """
    Per-store statistics keyed by store name:

      n                  number of priced products
      median             median effective price
      std                std-dev of effective price
      mean_discount_pct  average discount across products (0..1)
      oos_ratio          fraction marked "Agotado"
      competitiveness    fraction of shared games where this store is priced
                         ABOVE the cross-store median (lower = cheaper overall)
    """
    if df.empty or "store" not in df.columns:
        return {}

    work = df.copy()
    work["_price"] = effective_price(work)
    work["_discount"] = _discount(work)
    work = work[work["_price"].notna() & (work["_price"] > 0)]
    if work.empty:
        return {}

    status = (work["stock_status"] if "stock_status" in work else pd.Series([""] * len(work), index=work.index))
    work["_oos"] = status.fillna("").astype(str).str.lower().eq("agotado")

    if "norm" in work.columns:
        work["_game_median"] = work.groupby("norm")["_price"].transform("median")
        work["_pricier"] = work["_price"] > work["_game_median"]
    else:
        work["_pricier"] = False

    stats = {}
    for store, g in work.groupby("store"):
        stats[store] = {
            "n": int(len(g)),
            "median": float(g["_price"].median()),
            "std": float(g["_price"].std(ddof=0)) if len(g) > 1 else 0.0,
            "mean_discount_pct": float(g["_discount"].mean()),
            "oos_ratio": float(g["_oos"].mean()),
            "competitiveness": float(g["_pricier"].mean()),
        }
    return stats


def market_summary(df: pd.DataFrame) -> dict:
    """
    Market-wide summary cached in metadata.json:

      median_discount  median of per-store average discounts
      volatility_mean  mean cross-store price spread (max-min)/median per game
    """
    stats = price_stats_per_store(df)
    if not stats:
        return {"median_discount": 0.0, "volatility_mean": 0.0}

    discounts = pd.Series([s["mean_discount_pct"] for s in stats.values()])

    volatility_mean = 0.0
    if "norm" in df.columns:
        work = df.copy()
        work["_price"] = effective_price(work)
        work = work[work["_price"].notna() & (work["_price"] > 0)]
        if not work.empty:
            grp = work.groupby("norm")["_price"]
            spread = (grp.max() - grp.min()) / grp.median().replace(0, pd.NA)
            volatility_mean = float(spread.dropna().mean()) if not spread.dropna().empty else 0.0

    return {
        "median_discount": float(discounts.median()),
        "volatility_mean": volatility_mean,
    }

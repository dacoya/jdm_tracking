"""
Price / data anomaly detection for scraped product rows.

`validate_prices` returns a copy of the DataFrame with two added columns:
  - ``is_anomaly``     (bool)  — whether the row looks wrong
  - ``anomaly_reason`` (str)   — ';'-joined reason codes (empty if clean)

Used by ``merge_to_json`` to reject obviously-broken rows before persisting, and
available standalone for auditing the catalog.
"""
import pandas as pd

try:
    from .utils import parse_price
except ImportError:
    from utils import parse_price

# A discount steeper than this is almost always a scraping error, not a real sale.
MAX_PLAUSIBLE_DISCOUNT = 0.90

# How many standard deviations from a game's median price counts as an outlier.
OUTLIER_SIGMA = 5.0


def _effective(orig: pd.Series, curr: pd.Series) -> pd.Series:
    """Current price when present, else the original price."""
    return curr.where(curr.notna(), orig)


def validate_prices(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag anomalous rows. Returns a copy with ``is_anomaly`` / ``anomaly_reason``.

    Reason codes:
      empty_title           — missing/blank title
      nonpositive_original  — original price <= 0
      nonpositive_current   — current price <= 0
      offer_above_original  — current price > original (impossible discount)
      discount_over_90pct   — > 90% off (probable scraping error)
      price_outlier         — > OUTLIER_SIGMA from the median price for that game
                              (only when a 'norm' column groups cross-store rows)
    """
    out = df.copy()
    n = len(out)
    if n == 0:
        out["is_anomaly"] = pd.Series(dtype=bool)
        out["anomaly_reason"] = pd.Series(dtype=object)
        return out

    def _col(name):
        return out[name] if name in out.columns else pd.Series([None] * n, index=out.index)

    orig = _col("original_price").apply(parse_price)
    curr = _col("current_price").apply(parse_price)
    eff = _effective(orig, curr)

    reasons = {i: [] for i in out.index}

    def _flag(mask, code):
        for i in out.index[mask.fillna(False)]:
            reasons[i].append(code)

    title = _col("title").fillna("").astype(str).str.strip()
    _flag(title == "", "empty_title")

    _flag(orig.notna() & (orig <= 0), "nonpositive_original")
    _flag(curr.notna() & (curr <= 0), "nonpositive_current")

    both = orig.notna() & curr.notna()
    _flag(both & (curr > orig), "offer_above_original")

    discount = 1 - (curr / orig)
    _flag(both & (orig > 0) & (discount > MAX_PLAUSIBLE_DISCOUNT), "discount_over_90pct")

    # Statistical outlier — needs cross-store grouping by game (the 'norm' key).
    if "norm" in out.columns:
        median = eff.groupby(out["norm"]).transform("median")
        std = eff.groupby(out["norm"]).transform("std")
        outlier = eff.notna() & std.notna() & (std > 0) & ((eff - median).abs() > OUTLIER_SIGMA * std)
        _flag(outlier, "price_outlier")

    out["anomaly_reason"] = [";".join(reasons[i]) for i in out.index]
    out["is_anomaly"] = out["anomaly_reason"].str.len() > 0
    return out

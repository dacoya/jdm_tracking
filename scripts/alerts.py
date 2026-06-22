"""
Keyword price monitoring for unattended (cron) use.

`alert_on_keywords` scans the current catalog for a watchlist of games and emits
an alert for any whose best (lowest) effective price is at or below a threshold.
Designed to run periodically and append machine-readable alerts to a JSON file.
"""
import json
import time

import pandas as pd
from rapidfuzz import fuzz

try:
    from .utils import normalize, parse_price
except ImportError:
    from utils import normalize, parse_price


def _effective(df: pd.DataFrame) -> pd.Series:
    n = len(df)
    orig = (df["original_price"] if "original_price" in df else pd.Series([None] * n, index=df.index)).apply(parse_price)
    curr = (df["current_price"] if "current_price" in df else pd.Series([None] * n, index=df.index)).apply(parse_price)
    return curr.where(curr.notna(), orig)


def alert_on_keywords(query_list, price_threshold, df, output_file=None, score_cutoff=80) -> list:
    """
    For each query, find the cheapest matching product and alert if it's at or
    below the threshold.

    `price_threshold` is either a single number (applies to every query) or a
    dict mapping query -> threshold.  Returns the list of alert dicts and, if
    `output_file` is given, writes them there as JSON.
    """
    alerts = []
    if df is None or df.empty or "norm" not in df.columns:
        if output_file is not None:
            _write(output_file, alerts)
        return alerts

    norms = df["norm"].fillna("").astype(str)
    eff_all = _effective(df)
    now = int(time.time())

    for query in query_list:
        qn = normalize(query)
        threshold = price_threshold.get(query) if isinstance(price_threshold, dict) else price_threshold
        if threshold is None:
            continue

        scores = norms.map(lambda nrm: fuzz.token_set_ratio(qn, nrm))
        match_mask = scores >= score_cutoff
        if not match_mask.any():
            continue

        prices = eff_all[match_mask]
        prices = prices[prices.notna() & (prices > 0)]
        if prices.empty:
            continue

        best_idx = prices.idxmin()
        best_price = float(prices.min())
        if best_price <= float(threshold):
            row = df.loc[best_idx]
            alerts.append({
                "query": query,
                "matched_title": row.get("title"),
                "store": row.get("store"),
                "price": best_price,
                "threshold": float(threshold),
                "url": row.get("url"),
                "timestamp": now,
            })

    if output_file is not None:
        _write(output_file, alerts)
    return alerts


def _write(output_file, alerts) -> None:
    from pathlib import Path
    p = Path(output_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)

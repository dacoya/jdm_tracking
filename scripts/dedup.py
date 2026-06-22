"""
Stronger product deduplication.

- ``deduplicate_by_url`` collapses rows that point at the same product page
  (same canonical URL) but were scraped with slightly different titles, keeping
  the cheapest effective price.
- ``merge_variants`` clusters near-identical normalized titles under a single
  canonical name so cross-store comparisons aren't fragmented.

Both return copies; neither mutates the input.
"""
import re

import pandas as pd
from rapidfuzz import fuzz

try:
    from .utils import parse_price
except ImportError:
    from utils import parse_price


def _canonical_url(url) -> str:
    """Normalise a URL for identity comparison (scheme/host/query/slash stripped)."""
    if not isinstance(url, str):
        return ""
    u = url.strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = u.split("?")[0].split("#")[0]
    return u.rstrip("/")


def _effective(df: pd.DataFrame) -> pd.Series:
    n = len(df)
    orig = (df["original_price"] if "original_price" in df else pd.Series([None] * n, index=df.index)).apply(parse_price)
    curr = (df["current_price"] if "current_price" in df else pd.Series([None] * n, index=df.index)).apply(parse_price)
    return curr.where(curr.notna(), orig)


def deduplicate_by_url(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop rows sharing a canonical URL, keeping the one with the lowest effective
    price.  Rows without a URL are always kept (can't be identified).  Original
    row order is preserved.
    """
    if df.empty or "url" not in df.columns:
        return df.copy()

    out = df.copy()
    out["_canon"] = out["url"].map(_canonical_url)
    out["_price"] = _effective(out)

    has_url = out["_canon"] != ""
    keepable = out[has_url].sort_values("_price", na_position="last")
    deduped = keepable.drop_duplicates(subset="_canon", keep="first")

    result = pd.concat([deduped, out[~has_url]]).sort_index()
    return result.drop(columns=["_canon", "_price"])


def merge_variants(df: pd.DataFrame, similarity_threshold: float = 0.92) -> pd.DataFrame:
    """
    Cluster near-identical normalized titles into variant groups.

    Adds two columns:
      variant_group  integer cluster id
      canonical      representative title per cluster (the shortest member —
                     base products tend to have the shortest titles)

    `similarity_threshold` in [0, 1] maps to a token_sort_ratio cutoff.  Uses a
    greedy representative scan (O(n·clusters)) rather than full pairwise
    comparison, so it stays usable on large result sets.
    """
    out = df.copy()
    if out.empty or "norm" not in out.columns:
        out["variant_group"] = range(len(out))
        out["canonical"] = out["title"] if "title" in out else ""
        return out

    cutoff = similarity_threshold * 100
    reps = []  # list of (norm, cluster_id)
    cluster_of = {}
    next_id = 0

    for norm in out["norm"].dropna().unique():
        found = None
        for rep_norm, rep_id in reps:
            if fuzz.token_sort_ratio(norm, rep_norm) >= cutoff:
                found = rep_id
                break
        if found is None:
            found = next_id
            reps.append((norm, found))
            next_id += 1
        cluster_of[norm] = found

    out["variant_group"] = out["norm"].map(cluster_of)

    # Canonical title per cluster = shortest title among its members.
    titles = out.get("title", pd.Series([""] * len(out), index=out.index)).fillna("")
    canon = (
        out.assign(_len=titles.str.len(), _title=titles)
        .sort_values("_len")
        .groupby("variant_group")["_title"]
        .first()
    )
    out["canonical"] = out["variant_group"].map(canon)
    return out

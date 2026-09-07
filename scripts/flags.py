"""
New / restock detection across catalog updates.

On each update every scraped item is compared, by canonical product URL, to the
store's PREVIOUS snapshot in products.json. Each item gets a transient ``flag``:

    'new'      — its URL was not present in the previous snapshot
    'restock'  — its URL was present but out of stock, and is now available

Items that are unchanged (or newly out of stock) get no flag. Flags are
recomputed on every update from the just-previous snapshot, so they always
describe the most recent change set — the previous update's flags are simply
not carried forward (see merge_to_json), which clears them automatically.
"""
import pandas as pd

try:
    from .dedup import _canonical_url
except ImportError:
    from dedup import _canonical_url

FLAG_NEW = "new"
FLAG_RESTOCK = "restock"


def _is_oos(status) -> bool:
    """True when a stock_status marks the item out of stock."""
    return str(status or "").strip().lower() == "agotado"


def flag_changes(new_df: pd.DataFrame, prev_records: list) -> pd.DataFrame:
    """
    Return a copy of `new_df` with a 'flag' column ('new' / 'restock' / None).

    `prev_records` is the store's previous list of product dicts. If it's empty
    (the store's first-ever scrape) nothing is flagged — that snapshot is the
    baseline. Items without a URL can't be tracked and are left unflagged.
    """
    out = new_df.copy()
    if out.empty:
        out["flag"] = pd.Series(dtype=object)
        return out

    if not prev_records:
        out["flag"] = None
        return out

    prev_by_url = {}
    for r in prev_records:
        url = _canonical_url(r.get("url"))
        if url:
            prev_by_url[url] = r

    def _flag(row):
        url = _canonical_url(row.get("url"))
        if not url:
            return None
        prev = prev_by_url.get(url)
        if prev is None:
            return FLAG_NEW
        if _is_oos(prev.get("stock_status")) and not _is_oos(row.get("stock_status")):
            return FLAG_RESTOCK
        return None

    out["flag"] = out.apply(_flag, axis=1)
    return out


def flag_counts(df: pd.DataFrame) -> dict:
    """Return {'new': n, 'restock': m} from a flagged DataFrame."""
    if "flag" not in df.columns:
        return {"new": 0, "restock": 0}
    vc = df["flag"].value_counts()
    return {"new": int(vc.get(FLAG_NEW, 0)), "restock": int(vc.get(FLAG_RESTOCK, 0))}

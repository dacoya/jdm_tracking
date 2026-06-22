"""
Per-site scrape metadata and cached market statistics.

Stored alongside products.json in ``data/metadata.json``.  Tracks when each store
was last scraped (and whether it succeeded) so updates can be *incremental* —
rescraping only stale sites — and caches market-wide price stats for contextual
renders without recomputing on every run.

All mutators are immutable: they return a new metadata dict rather than editing
the argument in place.
"""
import json
import time

try:
    from .paths import DATA_DIR
except ImportError:
    from paths import DATA_DIR

METADATA_PATH = DATA_DIR / "metadata.json"


def _empty() -> dict:
    return {"sites": {}, "price_stats": {}}


def load_metadata() -> dict:
    """Read metadata.json, or return an empty skeleton if absent/corrupt."""
    if METADATA_PATH.exists():
        try:
            with open(METADATA_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Defensive: guarantee the expected top-level keys exist.
            return {"sites": data.get("sites", {}), "price_stats": data.get("price_stats", {})}
        except (json.JSONDecodeError, OSError):
            pass
    return _empty()


def save_metadata(meta: dict) -> None:
    """Persist metadata to metadata.json (creates the data dir if needed)."""
    METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def record_scrape(meta: dict, name: str, product_count: int, success: bool = True,
                  timestamp: int = None) -> dict:
    """
    Return a new metadata dict with `name`'s scrape state updated.

    Records the current time as `last_scrape`, the product count, and whether
    the scrape succeeded.
    """
    ts = int(timestamp if timestamp is not None else time.time())
    sites = {**meta.get("sites", {})}
    sites[name] = {
        "last_scrape": ts,
        "product_count": int(product_count),
        "success": bool(success),
    }
    return {**meta, "sites": sites}


def set_price_stats(meta: dict, price_stats: dict) -> dict:
    """Return a new metadata dict with the cached market price stats replaced."""
    return {**meta, "price_stats": dict(price_stats)}


def site_age_hours(meta: dict, name: str):
    """Hours since `name` was last scraped, or None if never scraped."""
    info = meta.get("sites", {}).get(name)
    if not info or "last_scrape" not in info:
        return None
    return (time.time() - info["last_scrape"]) / 3600.0


def stale_sites(meta: dict, names, max_age_hours: float = 24.0) -> list:
    """
    Names that need rescraping: never scraped, last scrape failed, or older than
    `max_age_hours`.  Preserves the input order.
    """
    stale = []
    sites = meta.get("sites", {})
    for name in names:
        info = sites.get(name)
        age = site_age_hours(meta, name)
        if info is None or not info.get("success", False) or age is None or age > max_age_hours:
            stale.append(name)
    return stale

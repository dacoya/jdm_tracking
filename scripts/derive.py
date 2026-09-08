"""
Turn a raw scraped record into a database row.

Shared by the one-time JSON migration and the live scrape ingest so both
produce byte-identical rows -- if these ever drifted, a re-scrape would look
like a catalog-wide change.
"""
try:
    from .classify import classify
    from .dedup import _canonical_url
    from .utils import clean_title, normalize, parse_price
except ImportError:
    from classify import classify
    from dedup import _canonical_url
    from utils import clean_title, normalize, parse_price

OUT_OF_STOCK = "agotado"
VALID_FLAGS = ("new", "restock")


def text(value):
    """Coerce a scraped value to a clean string, mapping NaN/None to None."""
    if value is None or not isinstance(value, str):
        return None
    return value.strip() or None


def in_stock(status) -> int:
    return 0 if str(status or "").strip().lower() == OUT_OF_STOCK else 1


def flag_value(value):
    return value if value in VALID_FLAGS else None


def derive(store: str, record: dict) -> dict | None:
    """
    Build a product row from one scraped record. None when unusable.

    A record with no URL still gets a stable synthetic identity rather than
    being dropped -- identity is what makes price history and new/restock
    detection meaningful across runs.
    """
    title_raw = text(record.get("title"))
    if not title_raw:
        return None

    title = clean_title(title_raw)
    norm = normalize(title)
    if not norm:
        return None

    url = text(record.get("url")) or ""
    url_canon = _canonical_url(url) or f"urn:tablero:{store}:{norm}"

    price_original = parse_price(record.get("original_price"))
    price_current = parse_price(record.get("current_price"))

    return {
        "store": store,
        "url_canon": url_canon,
        "url": url,
        "title_raw": title_raw,
        "title": title,
        "norm": norm,
        "kind": classify(title),
        "price_original": price_original,
        "price_current": price_current,
        "price_eff": price_current if price_current is not None else price_original,
        "in_stock": in_stock(record.get("stock_status")),
        "flag": flag_value(record.get("flag")),
    }

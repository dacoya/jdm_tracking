"""
Turn a raw scraped record into a database row.

Shared by the one-time JSON migration and the live scrape ingest so both
produce byte-identical rows -- if these ever drifted, a re-scrape would look
like a catalog-wide change.
"""
import re

try:
    from .classify import classify
    from .utils import clean_title, normalize, parse_price
except ImportError:
    from classify import classify
    from utils import clean_title, normalize, parse_price


def canonical_url(url) -> str:
    """
    Normalise a URL for identity comparison.

    Scheme, www, query string and trailing slash are dropped, so the same
    product page reached by different links is recognised as one product.
    This pairing of store + canonical URL is what makes price history and
    new/restock detection meaningful across scrapes.
    """
    if not isinstance(url, str):
        return ""
    u = url.strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = u.split("?")[0].split("#")[0]
    return u.rstrip("/")

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


def _is_truncated(title: str) -> bool:
    """True when a store cut the title short ('Terraforming Mars -...')."""
    return title.rstrip().endswith(("...", "…"))


def slug_name(url: str) -> str:
    """
    Recover a product name from a URL slug.

    Several stores publish titles truncated for their own layout, and every one
    of those collapses to the same prefix: planetaloz lists 'Terraforming Mars
    -...' (Preludio 2) and 'Terraforming Mars...' (Expedición Ares), which
    merged into the base game and advertised an expansion's price as its own.
    The slug still carries the full name.
    """
    if not url:
        return ""
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    tail = re.sub(r"\.(html?|php|aspx)$", "", tail, flags=re.IGNORECASE)
    tail = re.sub(r"^\d+[-_]", "", tail)          # leading catalogue id
    tail = re.sub(r"[-_]p?\d+$", "", tail)        # trailing product id
    return tail.replace("-", " ").replace("_", " ").strip()


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

    # A truncated title is not a reliable identity: match on the slug instead,
    # while still displaying what the store actually wrote.
    if _is_truncated(title_raw):
        from_slug = normalize(clean_title(slug_name(url)))
        if from_slug and from_slug.startswith(norm) and from_slug != norm:
            norm = from_slug

    url_canon = canonical_url(url) or f"urn:tablero:{store}:{norm}"

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

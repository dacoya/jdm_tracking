"""
Longitudinal price history.

Price observations are appended to ``data/history.json`` keyed by
``"<norm>|<store>"``, each entry ``{"t": unix_ts, "price": float}``.  Consecutive
identical prices are collapsed so the file only grows when a price actually
changes — enabling trend detection, threshold alerts, and ASCII price charts.
"""
import json
import time

try:
    from .paths import DATA_DIR
    from .utils import parse_price
except ImportError:
    from paths import DATA_DIR
    from utils import parse_price

HISTORY_PATH = DATA_DIR / "history.json"

_SPARK_BLOCKS = "▁▂▃▄▅▆▇█"


def _key(norm_key: str, store: str) -> str:
    return f"{norm_key}|{store}"


def load_history() -> dict:
    """Read history.json, or return {} if absent/corrupt."""
    if HISTORY_PATH.exists():
        try:
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_history(history: dict) -> None:
    """Persist the history dict to history.json."""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False)


def track_price_history(product_norm_key: str, store: str, price: float,
                        history: dict = None, timestamp: int = None) -> dict:
    """
    Append one (timestamp, price) observation for a product+store.

    Returns a NEW history dict (the input is not mutated).  A repeat of the most
    recent price is ignored so only genuine changes are stored.
    """
    base = load_history() if history is None else history
    if price is None:
        return base
    ts = int(timestamp if timestamp is not None else time.time())
    key = _key(product_norm_key, store)
    series = base.get(key, [])
    if series and series[-1].get("price") == price:
        return base
    return {**base, key: series + [{"t": ts, "price": float(price)}]}


def record_dataframe_history(df, history: dict = None) -> dict:
    """
    Bulk-record the current effective price of every row in a scraped catalog.

    Builds and returns a new history dict efficiently (one pass; does not mutate
    the input).  Rows without a parseable price or missing norm/store are skipped.
    """
    base = load_history() if history is None else history
    updated = {k: list(v) for k, v in base.items()}
    ts = int(time.time())

    for _, row in df.iterrows():
        price = parse_price(row.get("current_price"))
        if price is None:
            price = parse_price(row.get("original_price"))
        norm, store = row.get("norm"), row.get("store")
        if price is None or not norm or not store:
            continue
        series = updated.setdefault(_key(norm, store), [])
        if not series or series[-1].get("price") != price:
            series.append({"t": ts, "price": float(price)})

    return updated


def price_trend(norm_key: str, store: str, history: dict = None) -> dict:
    """
    Summarise a product+store price series, or None if there's no history.

    Returns ``{first, last, min, max, change_pct, n, points}`` where ``points``
    is the raw list of observations.
    """
    base = load_history() if history is None else history
    series = base.get(_key(norm_key, store), [])
    if not series:
        return None
    prices = [p["price"] for p in series]
    first, last = prices[0], prices[-1]
    change_pct = ((last - first) / first * 100) if first else 0.0
    return {
        "first": first,
        "last": last,
        "min": min(prices),
        "max": max(prices),
        "change_pct": change_pct,
        "n": len(prices),
        "points": series,
    }


def sparkline(values: list) -> str:
    """Render a list of numbers as an ASCII sparkline (▁▂▃▄▅▆▇█)."""
    nums = [v for v in values if v is not None]
    if not nums:
        return ""
    lo, hi = min(nums), max(nums)
    if hi == lo:
        return _SPARK_BLOCKS[0] * len(nums)
    span = hi - lo
    return "".join(_SPARK_BLOCKS[int((v - lo) / span * (len(_SPARK_BLOCKS) - 1))] for v in nums)

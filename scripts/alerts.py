"""
Price alerts, for cron.

Rewritten over the database. Two sources:

    watchlist -- every watched game with a target price (the normal case)
    ad-hoc    -- explicit queries plus one shared threshold

The watchlist path is the reason this is worth having: targets are stored, so a
scheduled run needs no arguments and cannot drift out of sync with what you
actually told the tool you wanted.

Emits the same alert shape the previous JSON-file version did, so anything
already consuming that output keeps working.
"""
import json
import time
from pathlib import Path

try:
    from . import repo, search as search_mod, watchlist as watch_mod
except ImportError:
    import repo
    import search as search_mod
    import watchlist as watch_mod


def _cheapest(conn, game_id: int, in_stock_only: bool = False):
    """Cheapest usable offer for a game, or None."""
    for offer in repo.game_prices(conn, game_id):
        price = offer.get("price_eff")
        if price is None or price <= 0:
            continue
        if in_stock_only and not offer.get("in_stock"):
            continue
        return offer
    return None


def _alert(game: dict, offer: dict, threshold: float, query: str) -> dict:
    return {
        "query": query,
        "matched_title": game.get("title"),
        "game_id": game.get("game_id"),
        "store": offer["store"],
        "price": float(offer["price_eff"]),
        "threshold": float(threshold),
        "url": offer.get("url"),
        "in_stock": bool(offer.get("in_stock")),
        "timestamp": int(time.time()),
    }


def from_watchlist(conn, in_stock_only: bool = False) -> list[dict]:
    """Alerts for watched games at or below their stored target."""
    alerts = []
    for entry in watch_mod.entries(conn):
        target = entry.get("target")
        if not target:
            continue
        offer = _cheapest(conn, entry["game_id"], in_stock_only=in_stock_only)
        if offer and offer["price_eff"] <= target:
            alerts.append(_alert(
                {"title": entry["title"], "game_id": entry["game_id"]},
                offer, target, entry["title"],
            ))
    return alerts


def from_queries(conn, queries, threshold: float,
                 in_stock_only: bool = False) -> list[dict]:
    """Alerts for ad-hoc queries sharing one threshold."""
    if threshold is None:
        raise ValueError("A threshold is required when alerting on queries.")

    alerts = []
    for query in queries:
        game = search_mod.best_match(conn, query)
        if not game:
            continue
        offer = _cheapest(conn, game["game_id"], in_stock_only=in_stock_only)
        if offer and offer["price_eff"] <= threshold:
            alerts.append(_alert(game, offer, threshold, query))
    return alerts


def write(alerts: list, path) -> str:
    """Write alerts as JSON. Returns the path."""
    # Create the directory: `--out reports/hoy.json` otherwise raised an
    # uncaught FileNotFoundError, unlike export which already handles this.
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)
    return str(target)

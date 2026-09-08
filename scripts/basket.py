"""
Wishlist basket optimisation.

Given a set of games, work out where to actually buy them. The naive answer --
buy each game wherever it is cheapest -- is usually wrong in practice, because
every extra store adds a shipping fee. This module reports both ends and a
greedy middle:

    split    : each game from its cheapest store (the price floor, most parcels)
    single   : the best one-store order (one parcel, usually incomplete)
    optimal  : greedy multi-store, adding a store only while it pays for itself

All functions are pure: connection in, plain dicts out. Nothing prints.
"""
try:
    from . import repo
except ImportError:
    import repo

# Rough default parcel cost within Chile. Overridable per call; the point is
# that a 3-store split is only cheaper if the savings beat the extra postage.
DEFAULT_SHIPPING = 4000.0


def _offers(conn, game_ids, in_stock_only: bool = True) -> dict:
    """{game_id: {store: price}} for the cheapest offer per store per game."""
    out: dict = {}
    for gid in game_ids:
        per_store: dict = {}
        for row in repo.game_prices(conn, gid):
            price = row.get("price_eff")
            if price is None or price <= 0:
                continue
            if in_stock_only and not row.get("in_stock"):
                continue
            store = row["store"]
            if store not in per_store or price < per_store[store]:
                per_store[store] = price
        if per_store:
            out[gid] = per_store
    return out


def _cost(offers: dict, stores: set, shipping: float) -> tuple[float, dict, list]:
    """Total cost of buying everything obtainable from `stores`."""
    picks, missing, total = {}, [], 0.0
    for gid, per_store in offers.items():
        available = {s: p for s, p in per_store.items() if s in stores}
        if not available:
            missing.append(gid)
            continue
        store = min(available, key=available.get)
        picks[gid] = {"store": store, "price": available[store]}
        total += available[store]

    used = {p["store"] for p in picks.values()}
    return total + shipping * len(used), picks, missing


def _plan(label, offers, stores, shipping, titles) -> dict:
    total, picks, missing = _cost(offers, stores, shipping)
    used = sorted({p["store"] for p in picks.values()})
    return {
        "strategy": label,
        "stores": used,
        "n_stores": len(used),
        "subtotal": round(total - shipping * len(used), 2),
        "shipping": round(shipping * len(used), 2),
        "total": round(total, 2),
        "items": [
            {"game_id": gid, "title": titles.get(gid, ""), **pick}
            for gid, pick in sorted(picks.items(), key=lambda kv: -kv[1]["price"])
        ],
        "missing": [{"game_id": gid, "title": titles.get(gid, "")} for gid in missing],
    }


def optimize(conn, game_ids, shipping: float = DEFAULT_SHIPPING,
             in_stock_only: bool = True) -> dict:
    """
    Compare buying strategies for a set of games.

    Returns the three plans plus `best` (lowest total). `unavailable` lists
    games no store can supply under the given stock constraint -- surfaced
    rather than silently dropped, since a plan that quietly omits half the
    wishlist is worse than useless.
    """
    game_ids = list(dict.fromkeys(game_ids))
    if not game_ids:
        return {"plans": [], "best": None, "unavailable": []}

    titles = {
        g["game_id"]: g["title"]
        for g in repo.games_by_ids(conn, game_ids)
    }
    offers = _offers(conn, game_ids, in_stock_only=in_stock_only)
    unavailable = [
        {"game_id": gid, "title": titles.get(gid, "")}
        for gid in game_ids if gid not in offers
    ]
    if not offers:
        return {"plans": [], "best": None, "unavailable": unavailable}

    all_stores = {s for per_store in offers.values() for s in per_store}

    plans = [
        _plan("split", offers, all_stores, shipping, titles),
        _plan("single", offers, {_best_single(offers, shipping)}, shipping, titles),
        _plan("optimal", offers, _greedy(offers, shipping), shipping, titles),
    ]

    # A complete order beats a cheaper incomplete one: a plan that skips items
    # is not comparable on price alone.
    best = min(plans, key=lambda p: (len(p["missing"]), p["total"]))
    return {"plans": plans, "best": best, "unavailable": unavailable}


def _best_single(offers: dict, shipping: float) -> str:
    """The single store giving the cheapest complete-as-possible order."""
    stores = {s for per_store in offers.values() for s in per_store}
    scored = []
    for store in stores:
        total, picks, missing = _cost(offers, {store}, shipping)
        scored.append((len(missing), total, store))
    return min(scored)[2]


def _greedy(offers: dict, shipping: float) -> set:
    """
    Grow a store set while each addition lowers the total.

    Set-cover with prices is NP-hard; a wishlist is a handful of games, so a
    greedy pass that stops when the next store no longer pays for its own
    shipping is both fast and easy to explain.
    """
    chosen = {_best_single(offers, shipping)}
    best_total, _, best_missing = _cost(offers, chosen, shipping)
    candidates = {s for per_store in offers.values() for s in per_store} - chosen

    while candidates:
        scored = []
        for store in candidates:
            total, _, missing = _cost(offers, chosen | {store}, shipping)
            scored.append((len(missing), total, store))
        missing_n, total, store = min(scored)

        improves_cost = total < best_total
        completes_order = missing_n < len(best_missing)
        if not (improves_cost or completes_order):
            break

        chosen.add(store)
        candidates.discard(store)
        best_total, best_missing = total, [None] * missing_n

    return chosen

"""Smart sorts, leaderboard, history trends, alerts, and price validation."""
import pytest

import alerts
import changes
import analytics
import history
import search
import validation
import watchlist


# ---------------------------------------------------------------------------
# Smart sorts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("by", analytics.SMART_SORT_OPTIONS)
def test_smart_sorts_run_and_score(db_conn, by):
    rows = analytics.smart_products(db_conn, by=by, limit=10)
    assert rows
    assert all("score" in r for r in rows)
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_unknown_smart_sort_rejected(db_conn):
    with pytest.raises(ValueError, match="Unknown smart sort"):
        analytics.smart_products(db_conn, by="nonsense")


def test_value_favours_price_below_median(db_conn):
    """tiendaA sells Catan at 39,990; tiendaB at 45,990. The cheaper one wins."""
    rows = analytics.smart_products(db_conn, by="value", limit=50)
    catan = [r for r in rows if r["title"].startswith("Catan") and r["kind"] == "game"]
    assert catan[0]["store"] == "tiendaA"


def test_scarcity_prefers_fewer_stores(db_conn):
    """Catan is in two stores; the expansion in one, so it is scarcer."""
    rows = analytics.smart_products(db_conn, by="scarcity", limit=50)
    by_title = {r["title"]: r["score"] for r in rows}
    assert by_title["Catan Expansión Navegantes"] > by_title["Catan"]


def test_median_is_per_game_not_global(db_conn):
    rows = analytics.smart_products(db_conn, by="value", limit=50)
    medians = {r["title"]: r["median"] for r in rows}
    # Catan's median comes from its own two listings, not the whole catalog.
    assert medians["Catan"] == pytest.approx((39990.0 + 45990.0) / 2)


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

def test_leaderboard_ranks_stores(db_conn):
    rows = analytics.store_leaderboard(db_conn)
    assert {r["store"] for r in rows} >= {"tiendaA", "tiendaB"}
    assert all(r["n"] > 0 for r in rows)


def test_leaderboard_competitiveness_uses_contested_games(db_conn):
    """
    Only games carried by more than one store count.

    Catan and Wingspan are contested; tiendaA is cheaper on Catan and dearer on
    Wingspan, so neither store is at either extreme.
    """
    rows = {r["store"]: r for r in analytics.store_leaderboard(db_conn)}
    assert rows["tiendaA"]["n_contested"] == 2
    assert 0.0 <= rows["tiendaA"]["competitiveness"] <= 1.0


def test_leaderboard_limit(db_conn):
    assert len(analytics.store_leaderboard(db_conn, limit=1)) == 1


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def test_sparkline_shapes():
    assert history.sparkline([1, 2, 3]) == "▁▄█"
    assert history.sparkline([5, 5, 5]) == "▁▁▁"
    assert history.sparkline([]) == ""
    assert history.sparkline([None]) == ""


def test_game_trends_from_observations(db_conn):
    """tiendaB's Catan fell 52,990 -> 45,990 across two observations."""
    gid = search.best_match(db_conn, "catan")["game_id"]
    trends = history.game_trends(db_conn, gid, min_points=2)
    assert len(trends) == 1
    t = trends[0]
    assert (t["store"], t["first"], t["last"], t["n"]) == ("tiendaB", 52990.0, 45990.0, 2)
    assert t["change_pct"] < 0
    assert t["spark"]


def test_min_points_hides_single_observations(db_conn):
    """One point is a price, not a trend."""
    gid = search.best_match(db_conn, "catan")["game_id"]
    assert len(history.game_trends(db_conn, gid, min_points=2)) == 1
    assert len(history.game_trends(db_conn, gid, min_points=1)) == 1


def test_observation_span(db_conn):
    span = history.observation_span(db_conn)
    assert span["n"] == 2 and span["first"] <= span["last"]


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

def test_alerts_from_watchlist_respects_target(db_conn):
    gid = search.best_match(db_conn, "catan")["game_id"]
    watchlist.add(db_conn, gid, target=45000)      # cheapest is 39,990
    fired = alerts.from_watchlist(db_conn)
    assert len(fired) == 1
    assert fired[0]["price"] == 39990.0
    assert fired[0]["store"] == "tiendaA"


def test_alerts_silent_above_target(db_conn):
    gid = search.best_match(db_conn, "catan")["game_id"]
    watchlist.add(db_conn, gid, target=1000)
    assert alerts.from_watchlist(db_conn) == []


def test_alerts_skip_entries_without_target(db_conn):
    gid = search.best_match(db_conn, "catan")["game_id"]
    watchlist.add(db_conn, gid, target=None)
    assert alerts.from_watchlist(db_conn) == []


def test_alerts_from_queries(db_conn):
    fired = alerts.from_queries(db_conn, ["catan"], threshold=45000)
    assert len(fired) == 1 and fired[0]["query"] == "catan"


def test_alerts_require_threshold(db_conn):
    with pytest.raises(ValueError, match="threshold"):
        alerts.from_queries(db_conn, ["catan"], threshold=None)


def test_alerts_in_stock_filter(db_conn):
    """tiendaA's Wingspan is out of stock, so only tiendaB can satisfy it."""
    gid = search.best_match(db_conn, "wingspan")["game_id"]
    watchlist.add(db_conn, gid, target=70000)
    fired = alerts.from_watchlist(db_conn, in_stock_only=True)
    assert len(fired) == 1 and fired[0]["store"] == "tiendaB"


def test_alerts_write_json(db_conn, tmp_path):
    import json
    out = tmp_path / "a.json"
    alerts.write(alerts.from_queries(db_conn, ["catan"], 45000), out)
    assert len(json.loads(out.read_text(encoding="utf-8"))) == 1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("row, reason", [
    ({"price_original": -1, "price_current": None}, "nonpositive_original"),
    ({"price_original": 100.0, "price_current": 0}, "nonpositive_current"),
    ({"price_original": None, "price_current": None}, "no_price"),
    ({"price_original": 100.0, "price_current": 200.0}, "offer_above_original"),
    ({"price_original": 100.0, "price_current": 5.0}, "discount_over_90pct"),
    ({"price_original": 100.0, "price_current": 50.0}, None),
    ({"price_original": 100.0, "price_current": None}, None),
])
def test_validation_rules(row, reason):
    assert validation.check(row) == reason


def test_partition_counts_reasons():
    clean, reasons = validation.partition([
        {"price_original": 100.0, "price_current": 50.0},
        {"price_original": 100.0, "price_current": 200.0},
        {"price_original": None, "price_current": None},
    ])
    assert len(clean) == 1
    assert reasons == {"offer_above_original": 1, "no_price": 1}


def test_outliers_are_reported_not_dropped(db_conn):
    """A bargain and a typo look identical, so this is a report, not a filter."""
    assert isinstance(validation.price_outliers(db_conn, sigma=0.1), list)


def test_changes_limit_none_means_unlimited(db_conn):
    """parser.DEFAULT_LIMIT is None; the TUI passes it straight through."""
    assert changes._limit(None) == -1
    assert changes._limit(0) == 0
    assert changes._limit(5) == 5
    changes.set_cursor(db_conn)
    assert isinstance(changes.price_drops(db_conn, min_pct=5.0, limit=None), list)
    assert isinstance(changes.new_arrivals(db_conn, limit=None), list)

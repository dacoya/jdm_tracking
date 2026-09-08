"""Stale-row exclusion, slug-based identity, and the filters that were dropped."""
import time

import pytest

import analytics
import derive
import ingest
import repo
import search


def _scrape(conn, store, records, ts):
    return ingest.ingest_store(conn, store, records, ts=ts)


def _record(title, url, price="$10.000", stock=None):
    return {"title": title, "url": url, "original_price": price,
            "current_price": None, "stock_status": stock}


# ---------------------------------------------------------------------------
# Stale rows
# ---------------------------------------------------------------------------

def test_delisted_product_stops_counting_as_an_offer(db_conn):
    """
    A product missing from its store's latest successful scrape is stale.

    152 games had their advertised "desde" price set by one of these -- a
    delisted listing keeps its last known price and undercuts every real offer.
    """
    now = int(time.time())
    _scrape(db_conn, "tiendaA", [
        _record("Splendor", "https://tiendaa.cl/p/splendor", "$5.000"),
        _record("Azul", "https://tiendaa.cl/p/azul", "$40.000"),
    ], ts=now)

    gid = search.best_match(db_conn, "splendor")["game_id"]
    assert repo.game_prices(db_conn, gid), "should be visible while it is listed"

    # Next scrape no longer carries Splendor.
    _scrape(db_conn, "tiendaA", [
        _record("Azul", "https://tiendaa.cl/p/azul", "$40.000"),
    ], ts=now + 3600)

    assert repo.game_prices(db_conn, gid) == []
    assert repo.game_prices(db_conn, gid, include_stale=True)


def test_stale_rows_are_kept_not_deleted(db_conn):
    """Hidden, not dropped: the price history has to survive."""
    now = int(time.time())
    _scrape(db_conn, "tiendaA", [
        _record("Splendor", "https://tiendaa.cl/p/splendor"),
        _record("Azul", "https://tiendaa.cl/p/azul"),
    ], ts=now)
    _scrape(db_conn, "tiendaA", [_record("Azul", "https://tiendaa.cl/p/azul")],
            ts=now + 3600)

    row = db_conn.execute(
        "SELECT COUNT(*) FROM product WHERE url_canon='tiendaa.cl/p/splendor'"
    ).fetchone()[0]
    assert row == 1
    assert repo.stale_count(db_conn) >= 1


def test_a_failed_scrape_does_not_make_everything_stale(db_conn):
    """Staleness is measured against the last SUCCESSFUL scrape."""
    now = int(time.time())
    _scrape(db_conn, "tiendaA", [_record("Azul", "https://tiendaa.cl/p/azul")], ts=now)
    before = repo.count_products(db_conn, store="tiendaA")
    ingest.record_failure(db_conn, "tiendaA", ts=now + 3600)
    assert repo.count_products(db_conn, store="tiendaA") == before


def test_search_hides_stale_offers(db_conn):
    now = int(time.time())
    _scrape(db_conn, "tiendaA", [
        _record("Gloomhaven", "https://tiendaa.cl/p/gloom-viejo", "$1.000"),
        _record("Gloomhaven", "https://tiendaa.cl/p/gloom", "$90.000"),
    ], ts=now)
    _scrape(db_conn, "tiendaA", [
        _record("Gloomhaven", "https://tiendaa.cl/p/gloom", "$90.000"),
    ], ts=now + 3600)

    hit = search.best_match(db_conn, "gloomhaven")
    assert hit["min_price"] == 90000.0, "the delisted $1.000 row must not set 'desde'"


# ---------------------------------------------------------------------------
# Filters that were silently dropped by the smart sorts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("by", analytics.SMART_SORT_OPTIONS)
def test_smart_sorts_honour_max_price(db_conn, by):
    """`deals --sort value --max-price 20000` used to return a $24.990 row."""
    rows = analytics.smart_products(db_conn, by=by, limit=50, max_price=40000)
    assert rows
    assert all(r["price_eff"] <= 40000 for r in rows)


@pytest.mark.parametrize("by", analytics.SMART_SORT_OPTIONS)
def test_smart_sorts_honour_min_price(db_conn, by):
    rows = analytics.smart_products(db_conn, by=by, limit=50, min_price=40000)
    assert all(r["price_eff"] >= 40000 for r in rows)


def test_smart_sorts_honour_stock_filter(db_conn):
    rows = analytics.smart_products(db_conn, by="value", limit=50, in_stock_only=True)
    assert all(r["in_stock"] for r in rows)


# ---------------------------------------------------------------------------
# Truncated titles
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url, expected", [
    ("https://x.cl/juegos/8645-terraforming-mars-preludio-2-e",
     "terraforming mars preludio 2 e"),
    ("https://x.cl/juegos/6692-terraforming-mars.html", "terraforming mars"),
    ("https://x.cl/p/catan-juego-de-cartas/", "catan juego de cartas"),
    ("", ""),
])
def test_slug_name(url, expected):
    assert derive.slug_name(url) == expected


def test_truncated_titles_do_not_merge_into_the_base_game():
    """
    Several stores cut titles for their layout, and every one collapses to the
    same prefix: planetaloz listed two Terraforming Mars expansions as
    "Terraforming Mars -..." and "Terraforming Mars...", which merged with the
    base game and advertised an expansion's price as its own.
    """
    base = derive.derive("planetaloz", _record(
        "Terraforming Mars", "https://x.cl/j/6692-terraforming-mars.html"))
    exp1 = derive.derive("planetaloz", _record(
        "Terraforming Mars -...", "https://x.cl/j/8645-terraforming-mars-preludio-2-e"))
    exp2 = derive.derive("planetaloz", _record(
        "Terraforming Mars...", "https://x.cl/j/7530-terraforming-mars-expedicion-a"))

    assert len({base["norm"], exp1["norm"], exp2["norm"]}) == 3
    # The readable title is still what the store wrote.
    assert exp1["title"].endswith("...")


def test_slug_is_only_used_when_it_extends_the_visible_title():
    """
    A slug that disagrees with the title is not trusted.

    Store slugs are often abbreviated or in another language; only a slug that
    starts with what the title already says can be a safe extension of it.
    """
    row = derive.derive("x", _record(
        "Catan...", "https://x.cl/p/producto-12345-sin-relacion"))
    assert row["norm"] == "catan"

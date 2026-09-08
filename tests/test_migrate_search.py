"""Migration integrity, search ranking, and the personal-use features."""
import basket
import changes
import repo
import search
import watchlist


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def test_all_products_imported(db_conn):
    assert db_conn.execute("SELECT COUNT(*) FROM product").fetchone()[0] == 6


def test_prices_are_numeric(db_conn):
    """The whole point of the SQLite move: no consumer should re-parse strings."""
    rows = db_conn.execute(
        "SELECT price_eff FROM product WHERE price_eff IS NOT NULL"
    ).fetchall()
    assert rows
    assert all(isinstance(r[0], float) for r in rows)


def test_sale_price_wins_over_original(db_conn):
    row = db_conn.execute(
        "SELECT price_original, price_current, price_eff FROM product "
        "WHERE store='tiendaA' AND title='Catan'"
    ).fetchone()
    assert (row["price_original"], row["price_current"], row["price_eff"]) == (49990.0, 39990.0, 39990.0)


def test_norm_is_persisted(db_conn):
    assert db_conn.execute(
        "SELECT COUNT(*) FROM product WHERE norm IS NULL OR norm = ''"
    ).fetchone()[0] == 0


def test_out_of_stock_detected(db_conn):
    row = db_conn.execute(
        "SELECT in_stock FROM product WHERE store='tiendaA' AND title='Wingspan'"
    ).fetchone()
    assert row["in_stock"] == 0


def test_same_game_clusters_across_stores(db_conn):
    """Catan in two stores is one game, which is what makes comparison work."""
    row = db_conn.execute(
        "SELECT g.id, COUNT(DISTINCT p.store) n FROM game g "
        "JOIN product p ON p.game_id=g.id WHERE g.norm='catan' GROUP BY g.id"
    ).fetchone()
    assert row["n"] == 2


def test_expansion_is_its_own_game(db_conn):
    kinds = dict(db_conn.execute("SELECT title, kind FROM game"))
    assert kinds["Catan"] == "game"
    assert kinds["Catan Expansión Navegantes"] == "expansion"


def test_history_mapped_to_product_id(db_conn):
    """The unambiguous series carries over; the orphan is dropped, not guessed."""
    n = db_conn.execute(
        "SELECT COUNT(*) FROM price_obs o JOIN product p ON p.id=o.product_id "
        "WHERE p.store='tiendaB' AND p.norm='catan'"
    ).fetchone()[0]
    assert n == 2
    assert db_conn.execute("SELECT COUNT(*) FROM price_obs").fetchone()[0] == 2


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def test_search_finds_base_game_first(db_conn):
    hits = search.search(db_conn, "catan")
    assert hits[0]["title"] == "Catan"


def test_search_hides_accessories_by_default(db_conn):
    titles = [h["title"] for h in search.search(db_conn, "catan")]
    assert not any("Fundas" in t for t in titles)


def test_search_can_include_accessories(db_conn):
    titles = [h["title"] for h in search.search(db_conn, "fundas", include_accessories=True)]
    assert any("Fundas" in t for t in titles)


def test_search_typo_tolerance(db_conn):
    """FTS cannot bridge a misspelling; the fuzzy fallback must."""
    hits = search.search(db_conn, "wingspn")
    assert hits and hits[0]["title"] == "Wingspan"


def test_search_reports_cheapest_and_store_count(db_conn):
    hit = search.best_match(db_conn, "catan")
    assert hit["n_stores"] == 2
    assert hit["min_price"] == 39990.0


def test_search_empty_query(db_conn):
    assert search.search(db_conn, "") == []


def test_fts_query_is_injection_safe():
    """User input must never reach MATCH as FTS syntax."""
    assert repo.fts_query('catan" OR "x') == '"catan"* "OR"* "x"*'
    assert repo.fts_query("") == ""


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

def test_watchlist_roundtrip(db_conn):
    gid = search.best_match(db_conn, "catan")["game_id"]
    assert watchlist.add(db_conn, gid, target=42000)
    entry = watchlist.entries(db_conn)[0]
    assert entry["title"] == "Catan"
    assert entry["hit"] is True          # cheapest is 39,990 <= 42,000
    assert watchlist.remove(db_conn, gid)
    assert watchlist.entries(db_conn) == []


def test_watchlist_rejects_unknown_game(db_conn):
    assert watchlist.add(db_conn, 999_999) is False


def test_basket_prefers_complete_order(db_conn):
    ids = [search.best_match(db_conn, q)["game_id"] for q in ("catan", "wingspan")]
    result = basket.optimize(db_conn, ids, shipping=4000, in_stock_only=True)
    best = result["best"]
    assert best["missing"] == []
    # tiendaA's Wingspan is out of stock, so a complete order must use tiendaB.
    assert "tiendaB" in best["stores"]


def test_basket_reports_unavailable(db_conn):
    result = basket.optimize(db_conn, [999_999], shipping=0)
    assert result["best"] is None
    assert len(result["unavailable"]) == 1


def test_basket_empty_input(db_conn):
    assert basket.optimize(db_conn, [])["plans"] == []


def test_price_drop_since_cursor(db_conn):
    """Catan at tiendaB fell 52,990 -> 45,990 between the two observations."""
    changes.set_cursor(db_conn, ts=1_700_050_000)
    drops = changes.price_drops(db_conn, min_pct=1.0)
    assert len(drops) == 1
    assert drops[0]["old_price"] == 52990.0
    assert drops[0]["new_price"] == 45990.0
    assert drops[0]["drop_pct"] > 13


def test_no_drops_without_cursor(db_conn):
    assert changes.price_drops(db_conn) == []


def test_resolve_store_partial_match(db_conn):
    """Exact match wins outright; otherwise every substring hit is offered.

    The fixture db also carries the live scrape registry's store names, so this
    asserts membership rather than an exact set.
    """
    assert repo.resolve_store(db_conn, "tiendaa") == ["tiendaA"]
    assert {"tiendaA", "tiendaB"} <= set(repo.resolve_store(db_conn, "tienda"))
    assert repo.resolve_store(db_conn, "nope") == []

"""
Regressions for bugs found in code review of 7331d57.

Each test reproduces the original failure, so a reintroduction fails loudly
rather than silently.
"""
import json
import sqlite3

import pytest

import db as db_mod
import ingest
import migrate
import search
import watchlist


def _seed(tmp_path, sample_products, sample_history):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "products.json").write_text(json.dumps(sample_products), encoding="utf-8")
    (data_dir / "history.json").write_text(json.dumps(sample_history), encoding="utf-8")
    db_path = tmp_path / "t.db"
    migrate.migrate(db_path=db_path, data_dir=data_dir)
    return data_dir, db_path


# ---------------------------------------------------------------------------
# HIGH: rebuild destroyed state it had failed to read
# ---------------------------------------------------------------------------

def test_rebuild_aborts_when_state_unreadable(tmp_path, sample_products, sample_history):
    """
    A rebuild must never delete a database whose state it could not read.

    The original code caught every exception and returned {}, so the rebuild
    proceeded and reported "0 restored" -- indistinguishable from "there was
    nothing to keep" -- while permanently dropping the watchlist.
    """
    data_dir, db_path = _seed(tmp_path, sample_products, sample_history)

    conn = db_mod.connect(db_path)
    watchlist.add(conn, search.best_match(conn, "catan")["game_id"], target=40000)
    conn.close()

    # Make the preservation query fail for a reason other than a missing table.
    conn = db_mod.connect(db_path)
    conn.execute("ALTER TABLE watchlist RENAME COLUMN target TO tgt")
    conn.commit()
    conn.close()

    size_before = db_path.stat().st_size
    with pytest.raises(sqlite3.OperationalError):
        migrate.migrate(db_path=db_path, data_dir=data_dir, rebuild=True)

    assert db_path.exists()
    assert db_path.stat().st_size == size_before

    conn = db_mod.connect(db_path, read_only=True)
    try:
        assert conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] == 1
    finally:
        conn.close()


def test_rebuild_tolerates_a_genuinely_missing_table(tmp_path, sample_products,
                                                     sample_history):
    """A table that does not exist yet really is 'nothing to preserve'."""
    data_dir, db_path = _seed(tmp_path, sample_products, sample_history)

    conn = db_mod.connect(db_path)
    watchlist.add(conn, search.best_match(conn, "catan")["game_id"], target=40000)
    conn.execute("DROP TABLE cursor")
    conn.commit()
    conn.close()

    report = migrate.migrate(db_path=db_path, data_dir=data_dir, rebuild=True)
    assert report["watchlist_found"] == 1
    assert report["watchlist_restored"] == 1


def test_report_distinguishes_nothing_to_keep_from_kept_nothing(tmp_path,
                                                                sample_products,
                                                                sample_history):
    data_dir, db_path = _seed(tmp_path, sample_products, sample_history)
    report = migrate.migrate(db_path=db_path, data_dir=data_dir, rebuild=True)
    assert report["watchlist_found"] == 0
    assert report["watchlist_restored"] == 0


# ---------------------------------------------------------------------------
# MEDIUM: statements exceeded SQLite's variable cap on large stores
# ---------------------------------------------------------------------------

# SQLite builds before 3.32 default to 999 host parameters. The project's own
# catalog has stores well past that (updown ~3,300 products), so an unbounded
# "IN (?,?,...)" made `update` fail outright on any older environment.
LEGACY_VARIABLE_LIMIT = 999

# Connection.setlimit is Python 3.11+. Where it is unavailable the constraint
# cannot be simulated, so these skip rather than pass vacuously.
requires_setlimit = pytest.mark.skipif(
    not hasattr(sqlite3.Connection, "setlimit"),
    reason="sqlite3.Connection.setlimit requires Python 3.11+",
)


def _many_records(n: int) -> list:
    return [
        {"title": f"Juego Numero {i}", "url": f"https://tiendaa.cl/p/{i}",
         "original_price": f"${10000 + i}", "current_price": None,
         "stock_status": None}
        for i in range(n)
    ]


@requires_setlimit
@pytest.mark.parametrize("count", [1200, 2500])
def test_ingest_survives_legacy_variable_limit(tmp_path, sample_products,
                                               sample_history, count):
    _, db_path = _seed(tmp_path, sample_products, sample_history)
    conn = db_mod.connect(db_path)
    conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, LEGACY_VARIABLE_LIMIT)
    try:
        result = ingest.ingest_store(conn, "tiendaA", _many_records(count))
        assert result["ingested"] == count
    finally:
        conn.close()


@requires_setlimit
def test_price_observations_recorded_under_legacy_limit(tmp_path, sample_products,
                                                        sample_history):
    """The price-history write is the other statement that scaled with store size."""
    _, db_path = _seed(tmp_path, sample_products, sample_history)
    conn = db_mod.connect(db_path)
    conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, LEGACY_VARIABLE_LIMIT)
    try:
        ingest.ingest_store(conn, "tiendaA", _many_records(1500), ts=1_700_100_000)
        assert conn.execute("SELECT COUNT(*) FROM price_obs").fetchone()[0] >= 1500
    finally:
        conn.close()


def test_flags_still_clear_for_unseen_products(db_conn):
    """
    Clearing flags up front must stay equivalent to the old NOT IN.

    tiendaB's Catan carries flag='new' from the fixture and is absent from this
    scrape, so it must end up unflagged.
    """
    ingest.ingest_store(db_conn, "tiendaB", [
        {"title": "Wingspan", "url": "https://tiendab.cl/p/wingspan",
         "original_price": "$59.990", "current_price": None, "stock_status": None},
    ], ts=1_700_200_000)

    assert db_conn.execute(
        "SELECT flag FROM product WHERE store='tiendaB' AND norm='catan'"
    ).fetchone()[0] is None


def test_price_observation_still_collapses_unchanged_prices(db_conn):
    """The INSERT...SELECT rewrite must keep the no-change-no-row behaviour."""
    records = [{"title": "Catan", "url": "https://tiendaa.cl/producto/catan/",
                "original_price": "$49.990", "current_price": "$39.990",
                "stock_status": None}]
    ingest.ingest_store(db_conn, "tiendaA", records, ts=1_700_200_000)
    first = db_conn.execute("SELECT COUNT(*) FROM price_obs").fetchone()[0]
    ingest.ingest_store(db_conn, "tiendaA", records, ts=1_700_300_000)
    assert db_conn.execute("SELECT COUNT(*) FROM price_obs").fetchone()[0] == first


# ---------------------------------------------------------------------------
# LOW: identifier quoting
# ---------------------------------------------------------------------------

def test_table_counts_quotes_identifiers(db_conn):
    """A table name cannot be bound, so it must at least be quoted."""
    db_conn.execute('CREATE TABLE "weird ""name"" table" (x INTEGER)')
    db_conn.commit()
    counts = db_mod.table_counts(db_conn)
    assert counts['weird "name" table'] == 0
    assert counts["product"] > 0

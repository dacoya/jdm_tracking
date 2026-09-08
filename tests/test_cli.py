"""
CLI dispatch and path configuration.

These carry real logic (store resolution, incremental site selection, the data
root override) and were the largest untested surface after the restructure.
"""
import importlib
import os

import pytest

import cli
import update


# ---------------------------------------------------------------------------
# Store resolution
# ---------------------------------------------------------------------------

def test_resolve_store_exact(db_conn):
    assert cli._resolve_store(db_conn, "tiendaA") == "tiendaA"


def test_resolve_store_is_case_insensitive(db_conn):
    assert cli._resolve_store(db_conn, "TIENDAA") == "tiendaA"


def test_resolve_store_none_passes_through(db_conn):
    assert cli._resolve_store(db_conn, None) is None


def test_resolve_store_unknown_explains(db_conn):
    """The old CLI errored without telling you what the valid names were."""
    with pytest.raises(cli.CommandError, match="tablero stores"):
        cli._resolve_store(db_conn, "no-existe")


def test_resolve_store_ambiguous_lists_candidates(db_conn):
    with pytest.raises(cli.CommandError) as exc:
        cli._resolve_store(db_conn, "tienda")
    assert "tiendaA" in str(exc.value) and "tiendaB" in str(exc.value)


# ---------------------------------------------------------------------------
# Update site selection
# ---------------------------------------------------------------------------

SITES = [{"name": "alpha"}, {"name": "beta"}, {"name": "gamma"}]


def test_select_named_sites(db_conn):
    chosen = update.select_sites(db_conn, SITES, ["beta"], False, 24)
    assert [s["name"] for s in chosen] == ["beta"]


def test_select_named_sites_is_case_insensitive(db_conn):
    assert update.select_sites(db_conn, SITES, ["BETA"], False, 24)[0]["name"] == "beta"


def test_unknown_site_rejected(db_conn):
    with pytest.raises(update.UnknownSiteError, match="desconocida"):
        update.select_sites(db_conn, SITES, ["nope"], False, 24)


def test_full_run_selects_everything(db_conn):
    assert len(update.select_sites(db_conn, SITES, None, False, 24)) == 3


def test_incremental_skips_recently_scraped(db_conn):
    """A store scraped inside the window is not re-scraped."""
    import time
    now = int(time.time())
    db_conn.execute(
        "INSERT OR REPLACE INTO scrape_run(store, ts, n_products, success) VALUES (?,?,?,1)",
        ("alpha", now, 10),
    )
    db_conn.commit()
    chosen = [s["name"] for s in update.select_sites(db_conn, SITES, None, True, 24)]
    assert "alpha" not in chosen
    assert {"beta", "gamma"} <= set(chosen)


def test_incremental_reselects_stale_and_failed(db_conn):
    """A stale success and a recent failure both need re-scraping."""
    import time
    now = int(time.time())
    db_conn.executemany(
        "INSERT OR REPLACE INTO scrape_run(store, ts, n_products, success) VALUES (?,?,?,?)",
        [("alpha", now - 90000, 10, 1),   # succeeded, but 25h ago
         ("beta", now, None, 0)],         # just failed
    )
    db_conn.commit()
    chosen = [s["name"] for s in update.select_sites(db_conn, SITES, None, True, 24)]
    assert {"alpha", "beta"} <= set(chosen)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def test_modes_are_mutually_exclusive():
    """
    The old flat-flag CLI silently mis-dispatched: `tablero -u --name x` ran a
    search and never scraped. Subcommands make that unrepresentable.
    """
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["update", "--name", "catan"])


def test_smart_sorts_are_accepted():
    for sort in ("value", "scarcity", "volatility"):
        assert cli.build_parser().parse_args(["deals", "--sort", sort]).sort == sort


def test_invalid_sort_rejected():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["deals", "--sort", "nonsense"])


def test_alerts_watch_requires_threshold():
    """--watch without --threshold would otherwise fire on every price."""
    with pytest.raises(SystemExit):
        cli.main(["alerts", "--watch", "catan"])


def test_watch_add_requires_a_game():
    with pytest.raises(SystemExit):
        cli.main(["watch", "add"])


# ---------------------------------------------------------------------------
# Data root override
# ---------------------------------------------------------------------------

def test_data_dir_env_override(tmp_path, monkeypatch):
    """TABLERO_DATA_DIR is what lets a sync job or test relocate the data root."""
    monkeypatch.setenv("TABLERO_DATA_DIR", str(tmp_path))
    import paths
    reloaded = importlib.reload(paths)
    try:
        assert reloaded.DATA_DIR == tmp_path.resolve()
        assert reloaded.JSON_PATH == tmp_path.resolve() / "products.json"
    finally:
        monkeypatch.delenv("TABLERO_DATA_DIR", raising=False)
        importlib.reload(paths)


def test_data_dir_defaults_to_repo(monkeypatch):
    monkeypatch.delenv("TABLERO_DATA_DIR", raising=False)
    import paths
    reloaded = importlib.reload(paths)
    assert reloaded.DATA_DIR == reloaded.REPO_ROOT / "data"


def test_blank_env_var_falls_back(monkeypatch):
    """An exported-but-empty variable must not resolve the root to the cwd."""
    monkeypatch.setenv("TABLERO_DATA_DIR", "   ")
    import paths
    reloaded = importlib.reload(paths)
    try:
        assert reloaded.DATA_DIR == reloaded.REPO_ROOT / "data"
    finally:
        monkeypatch.delenv("TABLERO_DATA_DIR", raising=False)
        importlib.reload(paths)


def test_installed_package_does_not_write_into_site_packages(monkeypatch, tmp_path):
    """
    A normal `pip install` puts the package under site-packages. Writing a
    15 MB database there would be wrong -- it is not the user's data, and a
    reinstall would delete it -- so a non-checkout falls back to a user dir.
    """
    monkeypatch.delenv("TABLERO_DATA_DIR", raising=False)
    import paths

    fake_site_packages = tmp_path / "site-packages"
    (fake_site_packages / "tablero").mkdir(parents=True)
    monkeypatch.setattr(paths, "REPO_ROOT", fake_site_packages)
    monkeypatch.setattr(paths, "PKG_DIR", fake_site_packages / "tablero")

    resolved = paths.default_data_dir()
    assert fake_site_packages not in resolved.parents
    assert resolved == paths._user_data_dir()


def test_source_checkout_still_uses_repo_data(monkeypatch, tmp_path):
    """A checkout keeps using its tracked data/, which is what development needs."""
    monkeypatch.delenv("TABLERO_DATA_DIR", raising=False)
    import paths

    checkout = tmp_path / "repo"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    monkeypatch.setattr(paths, "REPO_ROOT", checkout)

    assert paths.default_data_dir() == checkout / "data"


def test_env_override_beats_both(monkeypatch, tmp_path):
    monkeypatch.setenv("TABLERO_DATA_DIR", str(tmp_path))
    import paths
    assert paths.default_data_dir() == tmp_path.resolve()


def test_resolve_output_keeps_absolute_paths():
    import paths
    absolute = paths.Path("/tmp/somewhere/x.csv")
    assert paths.resolve_output(absolute) == absolute


def test_resolve_output_lands_beside_the_database_when_installed(monkeypatch, tmp_path):
    """An installed copy must not write scraped CSVs into site-packages."""
    import paths
    fake_site_packages = tmp_path / "site-packages"
    (fake_site_packages / "tablero").mkdir(parents=True)
    monkeypatch.setattr(paths, "REPO_ROOT", fake_site_packages)
    monkeypatch.setattr(paths, "PKG_DIR", fake_site_packages / "tablero")
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "userdata")

    assert paths.resolve_output("../data/tienda_jdm.csv") == \
        tmp_path / "userdata" / "tienda_jdm.csv"

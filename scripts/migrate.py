"""
One-time import of the legacy JSON files into SQLite.

Reads products.json / history.json / metadata.json, derives the fields that
previously existed only in memory (numeric prices, cleaned title, norm,
canonical URL), and writes data/tablero.db.

Non-destructive: the JSON files are only read. Returns a report dict; printing
is the caller's job.

The history mapping is the lossy part and is reported honestly. Legacy history
keyed on "norm|store", which collides when two distinct products in one store
normalize to the same string. Where a key maps to exactly one product the
series is carried over; where it is ambiguous or orphaned it is counted and
dropped rather than arbitrarily assigned.
"""
import json
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

try:
    from . import db as db_mod
    from .classify import kind_rank
    from .derive import derive
    from .paths import DATA_DIR
    from . import validation
except ImportError:
    import db as db_mod
    from classify import kind_rank
    from derive import derive
    from paths import DATA_DIR
    import validation


def _load_json(path, default):
    """Read a JSON file, returning `default` when absent or unreadable."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _store_timestamps(metadata: dict) -> dict:
    sites = metadata.get("sites", {}) if isinstance(metadata, dict) else {}
    return {
        name: info.get("last_scrape")
        for name, info in sites.items()
        if isinstance(info, dict) and info.get("last_scrape")
    }


def _sites():
    try:
        from .scrape import sites
    except ImportError:
        from scrape import sites
    return sites


def _site_registry() -> dict:
    """Base URLs from the scrape registry, keyed by store name. Empty on failure."""
    try:
        return {s["name"]: s.get("base_url") for s in _sites()}
    except Exception:
        return {}


def _load_from_csvs(data_dir) -> dict:
    """
    Rebuild the {store: [records]} shape from the per-store CSVs.

    The CSVs are what every scrape writes and what version control tracks, so
    they -- not products.json, which is now frozen legacy -- are the source that
    makes the database reproducible from a clean checkout.
    """
    import csv

    out: dict = {}
    try:
        registry = _sites()
    except Exception:
        return out

    for site in registry:
        path = data_dir / Path(site["output"]).name
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8", newline="") as f:
                rows = [
                    {k: (v if v not in ("", "nan") else None) for k, v in row.items()}
                    for row in csv.DictReader(f)
                ]
        except (OSError, csv.Error):
            continue
        if rows:
            out[site["name"]] = rows
    return out


def _game_rows(rows: list) -> dict:
    """
    Collapse products into one row per norm: {norm: (title, kind)}.

    Title: the shortest cleaned title in the cluster, because store-specific
    noise is additive -- the same game is "Catan" in one store and "Catan Juego
    Base 4 Jugadores" in another. This mirrors dedup.merge_variants' canonical.

    Kind: the most common kind among the cluster's products, ties broken toward
    the more game-like kind. A single store mislabelling one listing should not
    reclassify the game for everyone.
    """
    titles: dict[str, str] = {}
    kinds: dict[str, Counter] = defaultdict(Counter)

    for r in rows:
        norm = r["norm"]
        cur = titles.get(norm)
        if cur is None or len(r["title"]) < len(cur):
            titles[norm] = r["title"]
        kinds[norm][r["kind"]] += 1

    return {
        norm: (title, min(kinds[norm].items(), key=lambda kv: (-kv[1], kind_rank(kv[0])))[0])
        for norm, title in titles.items()
    }


def _read_optional(conn, sql: str) -> list:
    """
    Run a query, tolerating only the table being absent.

    An older database legitimately may not have a table yet -- that means there
    is nothing to preserve. Any other failure means there IS state and we could
    not read it, which must not be mistaken for the empty case.
    """
    try:
        return [dict(r) for r in conn.execute(sql)]
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return []
        raise


def _save_personal_state(path) -> dict:
    """
    Read watchlist and cursors out of an existing database before it is replaced.

    The catalog is regenerable from CSVs, but these rows are not: they are the
    user's own state, and a rebuild that silently dropped them would be a data
    loss bug dressed up as a migration.

    Raises rather than returning empty when the database exists but cannot be
    read. The caller deletes the file straight after this returns, so absorbing
    an error here would destroy exactly the data this function exists to save --
    and it would do it most often during a schema change, which is the one time
    preservation actually matters.
    """
    if path is None or not Path(path).exists():
        return {}

    conn = db_mod.connect(path, read_only=True)
    try:
        return {
            "watchlist": _read_optional(
                conn,
                "SELECT g.norm, w.target, w.note, w.added_at FROM watchlist w "
                "JOIN game g ON g.id = w.game_id",
            ),
            "cursors": _read_optional(conn, "SELECT name, ts FROM cursor"),
        }
    finally:
        conn.close()


def _restore_personal_state(conn, state: dict) -> dict:
    """Re-attach preserved state to the rebuilt game rows."""
    if not state:
        return {"watchlist_found": 0, "watchlist_restored": 0, "watchlist_lost": 0}

    ids = {r["norm"]: r["id"] for r in conn.execute("SELECT id, norm FROM game")}
    rows = [
        (ids[w["norm"]], w["target"], w["note"], w["added_at"])
        for w in state.get("watchlist", []) if w["norm"] in ids
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO watchlist(game_id, target, note, added_at) VALUES (?,?,?,?)",
        rows,
    )
    conn.executemany(
        "INSERT OR REPLACE INTO cursor(name, ts) VALUES (?,?)",
        [(c["name"], c["ts"]) for c in state.get("cursors", [])],
    )
    conn.commit()
    found = len(state.get("watchlist", []))
    return {
        "watchlist_found": found,
        "watchlist_restored": len(rows),
        "watchlist_lost": found - len(rows),
    }


def _load_catalog(data_dir) -> tuple[dict, str]:
    """The {store: [records]} catalog plus which source supplied it."""
    products = _load_json(data_dir / "products.json", {})
    if products:
        return products, "products.json"
    return _load_from_csvs(data_dir), "csv"


def _insert_stores(conn, products: dict) -> int:
    registry = _site_registry()
    names = sorted(set(products) | set(registry))
    conn.executemany(
        "INSERT OR REPLACE INTO store(name, base_url, city, active) VALUES (?, ?, NULL, ?)",
        [(n, registry.get(n), 1 if n in registry else 0) for n in names],
    )
    return len(names)


def _insert_games(conn, rows: list, now: int) -> tuple[dict, int]:
    """Insert the game clusters; return ({norm: game_id}, count)."""
    games = _game_rows(rows)
    conn.executemany(
        "INSERT OR IGNORE INTO game(norm, title, kind, created_at) VALUES (?, ?, ?, ?)",
        [(norm, title, kind, now) for norm, (title, kind) in sorted(games.items())],
    )
    ids = {r["norm"]: r["id"] for r in conn.execute("SELECT id, norm FROM game")}
    return ids, len(games)


def _insert_products(conn, rows: list, game_ids: dict, stamps: dict, now: int) -> None:
    conn.executemany(
        """INSERT OR IGNORE INTO product
           (store, url_canon, url, game_id, title_raw, title, norm, kind,
            price_original, price_current, price_eff, in_stock, flag,
            first_seen, last_seen)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                r["store"], r["url_canon"], r["url"], game_ids[r["norm"]],
                r["title_raw"], r["title"], r["norm"], r["kind"],
                r["price_original"], r["price_current"], r["price_eff"],
                r["in_stock"], r["flag"],
                stamps.get(r["store"], now), stamps.get(r["store"], now),
            )
            for r in rows
        ],
    )


def _insert_scrape_runs(conn, metadata: dict) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO scrape_run(store, ts, n_products, success) VALUES (?,?,?,?)",
        [
            (name, info["last_scrape"], info.get("product_count"),
             1 if info.get("success") else 0)
            for name, info in (metadata.get("sites") or {}).items()
            if isinstance(info, dict) and info.get("last_scrape")
        ],
    )


def migrate(db_path=None, data_dir=None, rebuild: bool = False) -> dict:
    """
    Import the catalog into SQLite. Returns a report.

    `rebuild` replaces an existing database (needed after a schema change).
    Watchlist entries and read cursors are carried across; if that state exists
    but cannot be read, this raises rather than replacing the file.
    """
    data_dir = data_dir or DATA_DIR
    now = int(time.time())

    target = Path(db_path) if db_path is not None else db_mod.DB_PATH
    preserved = {}
    if rebuild and target.exists():
        preserved = _save_personal_state(target)
        for suffix in ("", "-wal", "-shm"):
            Path(str(target) + suffix).unlink(missing_ok=True)

    products, source = _load_catalog(data_dir)
    history = _load_json(data_dir / "history.json", {})
    metadata = _load_json(data_dir / "metadata.json", {})

    rows = [
        derived
        for store, records in products.items()
        for record in records
        if (derived := derive(store, record)) is not None
    ]
    rows, rejected = validation.partition(rows)

    conn = db_mod.connect(db_path)
    try:
        db_mod.init_db(conn)
        n_stores = _insert_stores(conn, products)
        game_ids, n_games = _insert_games(conn, rows, now)
        _insert_products(conn, rows, game_ids, _store_timestamps(metadata), now)

        read = sum(len(v) for v in products.values())
        report = {
            "source": source,
            "records_read": read,
            "records_skipped": read - len(rows),
            "rejected": rejected,
            "stores": n_stores,
            "games": n_games,
            **_import_history(conn, history),
        }

        _insert_scrape_runs(conn, metadata)
        conn.commit()
        db_mod.rebuild_fts(conn)
        report.update(_restore_personal_state(conn, preserved))
        report["tables"] = db_mod.table_counts(conn)
        return report
    finally:
        conn.close()


def _import_history(conn, history: dict) -> dict:
    """
    Map legacy "norm|store" series onto product ids.

    A key is carried over only when it identifies exactly one product. Keys
    matching several products are ambiguous (the collision the old format could
    not represent); keys matching none are orphans left behind by title-cleaning
    changes. Both are counted, not guessed at.
    """
    by_key = defaultdict(list)
    for pid, store, norm in conn.execute("SELECT id, store, norm FROM product"):
        by_key[f"{norm}|{store}"].append(pid)

    observations = []
    mapped = ambiguous = orphaned = 0

    for key, points in history.items():
        pids = by_key.get(key, ())
        if len(pids) != 1:
            if pids:
                ambiguous += 1
            else:
                orphaned += 1
            continue

        pid = pids[0]
        mapped += 1
        # Dedup on ts: the legacy format allowed several prices at one timestamp
        # for a colliding key, and (product_id, ts) is the primary key here.
        seen = {}
        for p in points:
            if isinstance(p, dict) and p.get("t") and p.get("price") is not None:
                seen[int(p["t"])] = float(p["price"])
        observations.extend((pid, ts, price) for ts, price in seen.items())

    conn.executemany(
        "INSERT OR IGNORE INTO price_obs(product_id, ts, price) VALUES (?,?,?)",
        observations,
    )

    return {
        "history_series_total": len(history),
        "history_mapped": mapped,
        "history_ambiguous": ambiguous,
        "history_orphaned": orphaned,
        "observations": len(observations),
    }

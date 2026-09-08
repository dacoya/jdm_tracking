"""
Write scraped records into the database.

Replaces merge_to_json's snapshot diffing. Because product identity is stable
here (store + canonical URL), new/restock detection and price history fall out
of comparing against the rows already present -- no previous-snapshot file has
to be kept around and re-read.

Per store, so a partial or failed scrape never touches another store's data.
"""
import time

try:
    from . import db as db_mod, validation
    from .derive import derive
except ImportError:
    import db as db_mod
    import validation
    from derive import derive


def _existing(conn, store: str) -> dict:
    """{url_canon: row} for a store's current products."""
    sql = """SELECT id, url_canon, in_stock, price_eff, first_seen
               FROM product WHERE store = ?"""
    return {r["url_canon"]: dict(r) for r in conn.execute(sql, (store,))}


def _ensure_games(conn, rows: list, now: int) -> dict:
    """Create game rows for unseen norms; return {norm: game_id}."""
    norms = {r["norm"] for r in rows}
    if not norms:
        return {}

    # Shortest title wins as the cluster's display name, matching the migration.
    best: dict[str, tuple] = {}
    for r in rows:
        cur = best.get(r["norm"])
        if cur is None or len(r["title"]) < len(cur[0]):
            best[r["norm"]] = (r["title"], r["kind"])

    conn.executemany(
        "INSERT OR IGNORE INTO game(norm, title, kind, created_at) VALUES (?,?,?,?)",
        [(norm, title, kind, now) for norm, (title, kind) in best.items()],
    )

    placeholders = ",".join("?" * len(norms))
    return {
        r["norm"]: r["id"]
        for r in conn.execute(
            f"SELECT id, norm FROM game WHERE norm IN ({placeholders})", list(norms)
        )
    }


def _last_prices(conn, product_ids: list) -> dict:
    """{product_id: most recent observed price}, for change detection."""
    if not product_ids:
        return {}
    placeholders = ",".join("?" * len(product_ids))
    sql = f"""
        SELECT product_id, price FROM (
            SELECT product_id, price,
                   ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY ts DESC) rn
              FROM price_obs WHERE product_id IN ({placeholders})
        ) WHERE rn = 1
    """
    return {r["product_id"]: r["price"] for r in conn.execute(sql, product_ids)}


def ingest_store(conn, store: str, records: list, ts: int | None = None) -> dict:
    """
    Upsert one store's scraped records.

    An empty `records` is treated as a failed scrape and leaves existing data
    alone -- a network failure should never look like a store dropping its
    entire catalog.
    """
    ts = int(ts if ts is not None else time.time())
    rows = [d for rec in records if (d := derive(store, rec)) is not None]
    # Reject impossible prices before they reach the database: a bad row would
    # otherwise skew the cross-store median that every ranking depends on.
    rows, rejected = validation.partition(rows)
    if not rows:
        return {"store": store, "ingested": 0, "new": 0, "restock": 0,
                "rejected": rejected, "skipped": True}

    # Last row wins if a store lists the same URL twice in one scrape.
    rows = list({r["url_canon"]: r for r in rows}.values())

    conn.execute("INSERT OR IGNORE INTO store(name, active) VALUES (?, 1)", (store,))
    games = _ensure_games(conn, rows, ts)
    existing = _existing(conn, store)

    inserts, updates = [], []
    for r in rows:
        prev = existing.get(r["url_canon"])
        if prev is None:
            flag = "new"
        elif not prev["in_stock"] and r["in_stock"]:
            flag = "restock"
        else:
            flag = None

        payload = (
            games.get(r["norm"]), r["title_raw"], r["title"], r["norm"], r["kind"],
            r["price_original"], r["price_current"], r["price_eff"],
            r["in_stock"], flag, ts,
        )
        if prev is None:
            inserts.append((store, r["url_canon"], r["url"], *payload, ts))
        else:
            updates.append((*payload, prev["id"]))

    if inserts:
        conn.executemany(
            """INSERT INTO product
               (store, url_canon, url, game_id, title_raw, title, norm, kind,
                price_original, price_current, price_eff, in_stock, flag,
                last_seen, first_seen)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            inserts,
        )
    if updates:
        conn.executemany(
            """UPDATE product SET
                 game_id=?, title_raw=?, title=?, norm=?, kind=?,
                 price_original=?, price_current=?, price_eff=?,
                 in_stock=?, flag=?, last_seen=?
               WHERE id=?""",
            updates,
        )

    # Clear stale flags on rows this scrape did not see: a flag describes the
    # latest change, so carrying an old one forward would misreport it.
    seen_urls = [r["url_canon"] for r in rows]
    placeholders = ",".join("?" * len(seen_urls))
    conn.execute(
        f"UPDATE product SET flag=NULL WHERE store=? AND url_canon NOT IN ({placeholders})",
        [store, *seen_urls],
    )

    _record_prices(conn, store, ts)
    conn.execute(
        "INSERT OR REPLACE INTO scrape_run(store, ts, n_products, success) VALUES (?,?,?,1)",
        (store, ts, len(rows)),
    )
    conn.commit()

    return {
        "store": store,
        "ingested": len(rows),
        "new": len(inserts),
        "restock": sum(1 for u in updates if u[9] == "restock"),
        "rejected": rejected,
        "skipped": False,
    }


def _record_prices(conn, store: str, ts: int) -> None:
    """
    Append a price observation only where the price actually moved.

    Collapsing repeats keeps the series meaningful and the table small -- the
    legacy history module did the same, and without it every scrape would add
    ~29k identical rows.
    """
    current = {
        r["id"]: r["price_eff"]
        for r in conn.execute(
            "SELECT id, price_eff FROM product WHERE store=? AND price_eff IS NOT NULL",
            (store,),
        )
    }
    if not current:
        return

    last = _last_prices(conn, list(current))
    conn.executemany(
        "INSERT OR IGNORE INTO price_obs(product_id, ts, price) VALUES (?,?,?)",
        [(pid, ts, price) for pid, price in current.items() if last.get(pid) != price],
    )


def record_failure(conn, store: str, ts: int | None = None) -> None:
    """Log a failed scrape without touching the store's products."""
    ts = int(ts if ts is not None else time.time())
    conn.execute(
        "INSERT OR REPLACE INTO scrape_run(store, ts, n_products, success) VALUES (?,?,NULL,0)",
        (store, ts),
    )
    conn.commit()


def refresh_indexes(conn) -> None:
    """Resync FTS after a batch of stores has been ingested."""
    db_mod.rebuild_fts(conn)

"""
Scrape orchestration.

Extracted from cli.py so the terminal and the TUI share one implementation.
The TUI previously had to fabricate an argparse Namespace, mutate five of its
attributes and call `cli.cmd_update` -- depending on the CLI's parser shape to
do a job that has nothing to do with parsing.

Scrapes run concurrently; the database is written serially, because a sqlite3
connection is not safe to share across threads and serial writes keep the
transaction simple.
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from . import ingest as ingest_mod, repo
except ImportError:
    import ingest as ingest_mod
    import repo


class UnknownSiteError(ValueError):
    """Raised when a requested store is not in the scrape registry."""


def select_sites(conn, sites, names=None, incremental=False, max_age_hours=24):
    """Resolve which registry entries to scrape this run."""
    if names:
        wanted = {n.lower() for n in names}
        chosen = [s for s in sites if s["name"].lower() in wanted]
        unknown = wanted - {s["name"].lower() for s in chosen}
        if unknown:
            raise UnknownSiteError(f"Tienda(s) desconocida(s): {', '.join(sorted(unknown))}")
        return chosen

    if not incremental:
        return list(sites)

    cutoff = int(time.time()) - int(max_age_hours * 3600)
    fresh = repo.fresh_stores(conn, cutoff)
    return [s for s in sites if s["name"] not in fresh]


def update_stores(conn, targets, workers: int = 5, dry_run: bool = False,
                  on_failure=None) -> dict:
    """
    Scrape `targets` and write the results. Returns totals for the caller to
    report; an empty scrape is treated as a failure and leaves data untouched.
    """
    try:
        from .runner import scrape_site
    except ImportError:
        from runner import scrape_site

    totals = {"ingested": 0, "new": 0, "restock": 0, "failed": 0}
    rejected: dict = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(scrape_site, site, dry_run, i): site
                   for i, site in enumerate(targets)}
        for future in as_completed(futures):
            site = futures[future]
            try:
                df = future.result()
            except Exception as exc:
                if on_failure:
                    on_failure(site["name"], exc)
                ingest_mod.record_failure(conn, site["name"])
                totals["failed"] += 1
                continue

            records = df.to_dict("records") if df is not None and not df.empty else []
            result = ingest_mod.ingest_store(conn, site["name"], records)
            if result["skipped"]:
                ingest_mod.record_failure(conn, site["name"])
                totals["failed"] += 1
                continue
            for key in ("ingested", "new", "restock"):
                totals[key] += result[key]
            for reason, n in (result.get("rejected") or {}).items():
                rejected[reason] = rejected.get(reason, 0) + n

    ingest_mod.refresh_indexes(conn)
    totals["rejected"] = rejected
    return totals

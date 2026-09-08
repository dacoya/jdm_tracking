"""
Command-line interface.

Subcommands rather than the previous flat flag ladder, where modes were checked
in precedence order and combining them failed silently -- `tablero -u --name x`
ran a search and never scraped. With subparsers argparse rejects that outright,
and each command only advertises the options that apply to it.

This module is a thin shell: parse, call a service, hand the result to render.
"""
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from . import alerts, analytics, basket as basket_mod
    from . import changes, db as db_mod, export as exporter, history
    from . import ingest as ingest_mod, migrate as migrate_mod
    from . import render, repo, search as search_mod, validation
    from . import watchlist as watch_mod
    from .classify import KIND_ORDER
except ImportError:
    import alerts
    import analytics
    import basket as basket_mod
    import changes
    import db as db_mod
    import export as exporter
    import history
    import ingest as ingest_mod
    import migrate as migrate_mod
    import render
    import repo
    import search as search_mod
    import validation
    import watchlist as watch_mod
    from classify import KIND_ORDER

SORTS = ("discount", "price", "price_desc", "store", "title",
         "value", "scarcity", "volatility")


class CommandError(RuntimeError):
    """A user-facing failure: reported as a message, not a traceback."""


def _open_db(read_only: bool = True):
    try:
        return db_mod.connect(read_only=read_only)
    except FileNotFoundError:
        raise CommandError(
            "No hay base de datos todavía. Ejecuta primero:  tablero migrate"
        )


def _resolve_store(conn, text):
    """Turn user input into exactly one store name, or explain the options."""
    if not text:
        return None
    matches = repo.resolve_store(conn, text)
    if not matches:
        raise CommandError(
            f"Tienda '{text}' no encontrada. Usa 'tablero stores' para verlas."
        )
    if len(matches) > 1:
        raise CommandError(
            f"'{text}' coincide con varias tiendas: {', '.join(matches)}"
        )
    return matches[0]


def _price_filters(args) -> dict:
    """Shared price/stock/kind filters for browsing commands."""
    return {
        "in_stock_only": getattr(args, "in_stock", False),
        "min_price": getattr(args, "min_price", None),
        "max_price": getattr(args, "max_price", None),
        "kind": getattr(args, "kind", None),
    }


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_search(args) -> int:
    conn = _open_db()
    hits = search_mod.search(
        conn, args.query, limit=args.limit,
        include_accessories=args.all_kinds,
    )
    if not hits:
        print(f"Sin resultados para '{args.query}'.")
        return 1

    render.search_results(hits, args.query)
    if args.first:
        _show_prices(conn, hits[0])
    return 0


def _show_prices(conn, hit) -> None:
    render.price_table(repo.game_prices(conn, hit["game_id"]), hit["title"])


def _browse(conn, args, on_sale: bool) -> list[dict]:
    """Shared fetch for deals/list, dispatching to the smart sorts when asked."""
    store = _resolve_store(conn, args.store)
    if args.sort in analytics.SMART_SORT_OPTIONS:
        return analytics.smart_products(
            conn, by=args.sort, limit=args.limit, store=store,
            on_sale=on_sale, in_stock_only=args.in_stock, kind=args.kind,
        )
    return repo.products(
        conn, sort=args.sort, limit=args.limit, on_sale=on_sale,
        store=store, **_price_filters(args),
    )


def _export(rows: list[dict], fmt: str) -> None:
    """Write rows to data/exports/ in the requested format."""
    if not fmt or not rows:
        return
    import pandas as pd
    path = exporter.export_comparison(pd.DataFrame(rows), fmt)
    print(f"\n  Exportado: {path}")


def cmd_deals(args) -> int:
    conn = _open_db()
    rows = _browse(conn, args, on_sale=True)
    render.product_rows(rows, title=f"Ofertas ({len(rows)}) · orden: {args.sort}")
    _export(rows, args.export)
    return 0


def cmd_list(args) -> int:
    conn = _open_db()
    rows = _browse(conn, args, on_sale=False)
    store = _resolve_store(conn, args.store)
    total = repo.count_products(conn, store=store, **_price_filters(args))
    render.product_rows(rows, title=f"Catálogo ({len(rows)} de {total}) · orden: {args.sort}")
    _export(rows, args.export)
    return 0


def cmd_leaderboard(args) -> int:
    conn = _open_db()
    rows = analytics.store_leaderboard(conn, limit=args.limit)
    render.leaderboard(rows)
    _export(rows, args.export)
    return 0


def cmd_history(args) -> int:
    conn = _open_db()
    hit = search_mod.best_match(conn, args.query)
    if not hit:
        raise CommandError(f"Sin resultados para '{args.query}'.")

    trends = history.game_trends(conn, hit["game_id"], min_points=args.min_points)
    render.trends(trends, hit["title"], min_points=args.min_points)
    _export(
        [{k: v for k, v in t.items() if k != "points"} for t in trends], args.export
    )
    return 0


def cmd_alerts(args) -> int:
    conn = _open_db()
    if args.watch:
        alerts_found = alerts.from_queries(
            conn, args.watch, args.threshold, in_stock_only=args.in_stock)
        source = f"{len(args.watch)} consulta(s)"
    else:
        alerts_found = alerts.from_watchlist(conn, in_stock_only=args.in_stock)
        source = "lista de seguimiento"

    render.alerts(alerts_found, source)
    if args.out:
        print(f"\n  Escrito: {alerts.write(alerts_found, args.out)}")
    # Non-zero when nothing fired, so cron can act on the exit code.
    return 0 if alerts_found else 1


def cmd_stores(args) -> int:
    conn = _open_db()
    rows = [
        {
            "name": s["name"],
            "city": s["city"] or "-",
            "products": s["n_products"],
            "stock": s["n_in_stock"] or 0,
            "active": "sí" if s["active"] else "no",
        }
        for s in repo.stores(conn, active_only=args.active)
    ]
    render.table(rows, [
        ("name", "Tienda", True),
        ("city", "Ciudad", False),
        ("products", "Productos", False),
        ("stock", "En stock", False),
        ("active", "Activa", False),
    ], title=f"Tiendas ({len(rows)})")
    return 0


def cmd_new(args) -> int:
    conn = _open_db(read_only=False)
    if args.reset:
        ts = changes.set_cursor(conn)
        print(f"Marcador actualizado. Los próximos cambios se miden desde ahora ({ts}).")
        return 0

    if changes.get_cursor(conn) is None:
        print(
            "No hay marcador de 'última revisión'. Ejecuta 'tablero new --reset' "
            "para fijarlo; los cambios se listarán a partir de la próxima actualización."
        )
        return 1

    drops = changes.price_drops(conn, min_pct=args.min_pct, limit=args.limit)
    render.product_rows(
        [{**d, "price_current": d["new_price"], "price_original": d["old_price"],
          "discount_pct": d["drop_pct"]} for d in drops],
        title=f"Bajadas de precio desde tu última revisión ({len(drops)})",
    )

    arrivals = changes.new_arrivals(conn, limit=args.limit)
    if arrivals:
        render.product_rows(
            [{**a, "price_original": a["price_eff"]} for a in arrivals],
            title=f"\nNuevos productos ({len(arrivals)})",
        )
    return 0


def cmd_watch(args) -> int:
    conn = _open_db(read_only=False)

    if args.action == "list":
        rows = [
            {
                "title": e["title"],
                "target": render.money(e["target"]),
                "price": render.money(e["min_price"]),
                "stores": e["n_stores"],
                "hit": "¡SÍ!" if e["hit"] else "",
            }
            for e in watch_mod.entries(conn)
        ]
        render.table(rows, [
            ("title", "Juego", True),
            ("target", "Objetivo", False),
            ("price", "Actual", False),
            ("stores", "Tiendas", False),
            ("hit", "Alcanzado", False),
        ], title=f"Lista de seguimiento ({len(rows)})")
        return 0

    hit = search_mod.best_match(conn, args.query)
    if not hit:
        raise CommandError(f"Sin resultados para '{args.query}'.")

    if args.action == "add":
        watch_mod.add(conn, hit["game_id"], target=args.target)
        target = f" (objetivo {render.money(args.target)})" if args.target else ""
        print(f"Siguiendo: {hit['title']}{target}")
    else:
        removed = watch_mod.remove(conn, hit["game_id"])
        print(f"{'Quitado' if removed else 'No estaba en la lista'}: {hit['title']}")
    return 0


def cmd_basket(args) -> int:
    conn = _open_db()

    if args.from_watchlist:
        ids = watch_mod.game_ids(conn)
        if not ids:
            raise CommandError("La lista de seguimiento está vacía.")
    else:
        if not args.games:
            raise CommandError("Indica juegos o usa --from-watchlist.")
        ids = []
        for query in args.games:
            hit = search_mod.best_match(conn, query)
            if hit:
                ids.append(hit["game_id"])
                print(f"  {query:<24} → {hit['title']}")
            else:
                print(f"  {query:<24} → (sin resultados)")
        if not ids:
            raise CommandError("Ningún juego encontrado.")

    render.basket_plans(
        basket_mod.optimize(conn, ids, shipping=args.shipping,
                            in_stock_only=not args.include_oos)
    )
    return 0


def _select_sites(conn, sites, names, incremental, max_age_hours):
    """Resolve which registry entries to scrape this run."""
    if names:
        wanted = {n.lower() for n in names}
        chosen = [s for s in sites if s["name"].lower() in wanted]
        unknown = wanted - {s["name"].lower() for s in chosen}
        if unknown:
            raise CommandError(f"Tienda(s) desconocida(s): {', '.join(sorted(unknown))}")
        return chosen

    if not incremental:
        return list(sites)

    cutoff = int(time.time()) - int(max_age_hours * 3600)
    fresh = {
        r["store"]
        for r in conn.execute(
            "SELECT store, MAX(ts) ts FROM scrape_run WHERE success=1 "
            "GROUP BY store HAVING ts >= ?",
            (cutoff,),
        )
    }
    return [s for s in sites if s["name"] not in fresh]


def cmd_update(args) -> int:
    try:
        from .runner import scrape_site
        from .scrape import sites
    except ImportError:
        from runner import scrape_site
        from scrape import sites

    conn = _open_db(read_only=False)
    targets = _select_sites(conn, sites, args.sites, args.incremental, args.max_age)
    if not targets:
        print("Todo al día. Nada que actualizar.")
        return 0

    print(f"Actualizando {len(targets)} tienda(s) con {args.workers} workers…")
    totals = {"ingested": 0, "new": 0, "restock": 0, "failed": 0}
    rejected: dict = {}

    # Scrape concurrently, ingest serially: a SQLite connection is not safe to
    # share across threads, and serial writes keep the transaction simple.
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(scrape_site, site, args.dry_run, i): site
            for i, site in enumerate(targets)
        }
        for future in as_completed(futures):
            site = futures[future]
            try:
                df = future.result()
            except Exception as exc:
                print(f"  [{site['name']}] falló: {exc}")
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
    print(
        f"\nListo: {totals['ingested']} productos · "
        f"{totals['new']} nuevos · {totals['restock']} restock · "
        f"{totals['failed']} tienda(s) con error"
    )
    if rejected:
        detail = ", ".join(f"{n} {reason}" for reason, n in sorted(rejected.items()))
        print(f"Precios rechazados: {detail}")
    return 0


def cmd_migrate(args) -> int:
    report = migrate_mod.migrate(rebuild=args.rebuild)
    print("Migración completa:")
    print(f"  productos      : {report['records_read']:>7} leídos, "
          f"{report['records_skipped']} omitidos")
    print(f"  juegos         : {report['games']:>7}")
    print(f"  tiendas        : {report['stores']:>7}")
    print(f"  historial      : {report['history_mapped']:>7} series migradas, "
          f"{report['history_ambiguous']} ambiguas, {report['history_orphaned']} huérfanas")
    print(f"  observaciones  : {report['observations']:>7}")
    if report.get("rejected"):
        detail = ", ".join(f"{n} {r}" for r, n in sorted(report["rejected"].items()))
        print(f"  rechazados     : {detail}")
    if report.get("watchlist_restored") or report.get("watchlist_lost"):
        print(f"  seguimiento    : {report['watchlist_restored']:>7} conservados, "
              f"{report['watchlist_lost']} perdidos (el juego ya no existe)")
    print(f"\nBase de datos: {db_mod.DB_PATH}")
    return 0


def cmd_doctor(args) -> int:
    conn = _open_db()
    print(f"Base de datos : {db_mod.DB_PATH}")
    print(f"Esquema       : v{db_mod.schema_version(conn)}")
    for name, count in db_mod.table_counts(conn).items():
        print(f"  {name:<14} {count:>7}")

    missing = conn.execute(
        "SELECT COUNT(*) FROM product WHERE price_eff IS NULL"
    ).fetchone()[0]
    print(f"\nProductos sin precio: {missing}")

    span = history.observation_span(conn)
    print(f"Observaciones       : {span['n']}")

    # Reported, never auto-dropped: a real bargain and a typo look identical.
    outliers = validation.price_outliers(conn, sigma=args.sigma, limit=args.limit)
    if outliers:
        print(f"\nPrecios atípicos (> {args.sigma}σ del promedio del juego) — "
              f"revisar, no se descartan solos:")
        render.table([
            {"store": o["store"], "title": o["title"],
             "price": render.money(o["price_eff"]),
             "mean": render.money(o["mean"]),
             "sigmas": f"{o['sigmas']}σ", "n": o["n"]}
            for o in outliers
        ], [("title", "Producto", True), ("store", "Tienda", False),
            ("price", "Precio", False), ("mean", "Promedio", False),
            ("sigmas", "Desvío", False), ("n", "Tiendas", False)])
    cursor = changes.get_cursor(conn)
    print(f"Última revisión     : {cursor or '(sin fijar)'}")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _add_browse_flags(parser) -> None:
    parser.add_argument("--store", metavar="NAME", help="filtrar por tienda (admite parcial)")
    parser.add_argument("--in-stock", action="store_true", help="solo disponibles")
    parser.add_argument("--min-price", type=float, metavar="N")
    parser.add_argument("--max-price", type=float, metavar="N")
    parser.add_argument("--kind", choices=KIND_ORDER, nargs="+",
                        help="filtrar por tipo de producto")
    parser.add_argument("--sort", choices=SORTS, default="discount",
                        help="value/scarcity/volatility son órdenes derivados")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--export", choices=("csv", "json", "html"), metavar="FMT",
                        help="exportar el resultado a data/exports/")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tablero",
        description="Comparador de precios de juegos de mesa en Chile.",
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("search", help="buscar un juego")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--first", action="store_true", help="mostrar precios del primer resultado")
    p.add_argument("--all-kinds", action="store_true", help="incluir accesorios")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("deals", help="productos en oferta")
    _add_browse_flags(p)
    p.set_defaults(func=cmd_deals)

    p = sub.add_parser("list", help="listar catálogo")
    _add_browse_flags(p)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("stores", help="tiendas cubiertas")
    p.add_argument("--active", action="store_true", help="solo tiendas activas")
    p.set_defaults(func=cmd_stores)

    p = sub.add_parser("new", help="cambios desde tu última revisión")
    p.add_argument("--reset", action="store_true", help="fijar el marcador ahora")
    p.add_argument("--min-pct", type=float, default=5.0)
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("watch", help="lista de seguimiento")
    p.add_argument("action", choices=("add", "rm", "list"))
    p.add_argument("query", nargs="?")
    p.add_argument("--target", type=float, metavar="N", help="precio objetivo")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("basket", help="dónde comprar una lista de juegos")
    p.add_argument("games", nargs="*")
    p.add_argument("--from-watchlist", action="store_true")
    p.add_argument("--shipping", type=float, default=basket_mod.DEFAULT_SHIPPING,
                   help="costo de envío por tienda")
    p.add_argument("--include-oos", action="store_true", help="incluir agotados")
    p.set_defaults(func=cmd_basket)

    p = sub.add_parser("leaderboard", help="ranking de tiendas")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--export", choices=("csv", "json", "html"), metavar="FMT")
    p.set_defaults(func=cmd_leaderboard)

    p = sub.add_parser("history", help="evolución de precios de un juego")
    p.add_argument("query")
    p.add_argument("--min-points", type=int, default=2,
                   help="ocultar tiendas con menos observaciones (default 2)")
    p.add_argument("--export", choices=("csv", "json", "html"), metavar="FMT")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("alerts", help="avisos de precio (para cron)")
    p.add_argument("--watch", nargs="+", metavar="JUEGO",
                   help="consultas ad-hoc; por defecto usa la lista de seguimiento")
    p.add_argument("--threshold", type=float, metavar="N",
                   help="umbral para --watch")
    p.add_argument("--in-stock", action="store_true", help="solo ofertas disponibles")
    p.add_argument("--out", metavar="FILE", help="escribir los avisos como JSON")
    p.set_defaults(func=cmd_alerts)

    p = sub.add_parser("update", help="scrapear tiendas y actualizar la base")
    p.add_argument("--sites", nargs="+", metavar="NAME", help="solo estas tiendas")
    p.add_argument("-w", "--workers", type=int, default=5,
                   help="hilos concurrentes (default 5; subirlo agrava los bloqueos Cloudflare)")
    p.add_argument("--dry-run", action="store_true", help="solo la primera página por tienda")
    p.add_argument("--incremental", action="store_true", help="solo tiendas obsoletas")
    p.add_argument("--max-age", type=float, default=24, metavar="H",
                   help="antigüedad máxima en horas para --incremental")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("migrate", help="construir/reconstruir la base SQLite")
    p.add_argument("--rebuild", action="store_true",
                   help="reemplazar la base existente (necesario tras un cambio de esquema); "
                        "conserva la lista de seguimiento y los marcadores")
    p.set_defaults(func=cmd_migrate)

    p = sub.add_parser("doctor", help="estado de la base de datos")
    p.add_argument("--sigma", type=float, default=5.0,
                   help="umbral de desvío para precios atípicos")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_doctor)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        try:
            from .tui import run_tui
        except ImportError:
            from tui import run_tui
        run_tui()
        return 0

    if args.command == "watch" and args.action in ("add", "rm") and not args.query:
        parser.error(f"'watch {args.action}' necesita un juego")
    if args.command == "alerts" and args.watch and args.threshold is None:
        parser.error("--watch necesita --threshold")

    try:
        return args.func(args)
    except CommandError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())

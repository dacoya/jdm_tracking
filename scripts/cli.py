"""
Command-line interface.

Subcommands rather than the previous flat flag ladder, where modes were checked
in precedence order and combining them failed silently -- `tablero -u --name x`
ran a search and never scraped. With subparsers argparse rejects that outright,
and each command only advertises the options that apply to it.

This module is a thin shell: parse, call a service, hand the result to render.
"""
import sys

try:
    from . import alerts, analytics, basket as basket_mod
    from . import changes, db as db_mod, export as exporter, history
    from . import migrate as migrate_mod, parser as parser_mod
    from . import paths, render, repo, search as search_mod
    from . import update as update_mod, validation
    from . import watchlist as watch_mod
except ImportError:
    import alerts
    import analytics
    import basket as basket_mod
    import changes
    import db as db_mod
    import export as exporter
    import history
    import migrate as migrate_mod
    import parser as parser_mod
    import paths
    import render
    import repo
    import search as search_mod
    import update as update_mod
    import validation
    import watchlist as watch_mod

build_parser = parser_mod.build_parser


class CommandError(RuntimeError):
    """A user-facing failure: reported as a message, not a traceback."""


def _open_db(read_only: bool = True):
    try:
        return db_mod.connect(read_only=read_only)
    except FileNotFoundError:
        raise CommandError(
            f"No hay base de datos en {db_mod.DB_PATH}.\n"
            f"  Ejecuta:  tablero migrate\n"
            f"  (el directorio de datos se puede cambiar con TABLERO_DATA_DIR)"
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
    """
    Shared filters for browsing commands.

    One dict feeds both `repo.products` and `analytics.smart_products`, so a
    flag cannot apply to one sort and be silently dropped by another.
    """
    return {
        "in_stock_only": getattr(args, "in_stock", False),
        "min_price": getattr(args, "min_price", None),
        "max_price": getattr(args, "max_price", None),
        "kind": getattr(args, "kind", None),
        "include_stale": getattr(args, "include_stale", False),
    }


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_search(args) -> int:
    conn = _open_db()
    hits = search_mod.search(
        conn, args.query, limit=args.limit,
        include_accessories=args.all_kinds,
        include_stale=args.include_stale,
    )
    if not hits:
        print(f"Sin resultados para '{args.query}'.")
        return 1

    render.search_results(hits, args.query)
    if args.first:
        _show_prices(conn, hits[0], include_stale=args.include_stale)
    return 0


def _show_prices(conn, hit, include_stale: bool = False) -> None:
    render.price_table(
        repo.game_prices(conn, hit["game_id"], include_stale=include_stale),
        hit["title"],
    )


def _browse(conn, args, on_sale: bool) -> tuple[list[dict], int]:
    """
    Rows for deals/list plus the total matching the SAME filters.

    Returning both together is what keeps the header honest: the count used to
    be computed with the price filters applied while the rows were fetched
    without them, so "Catálogo (5 de 13400)" described two different populations.
    """
    filters = dict(_price_filters(args), store=_resolve_store(conn, args.store))
    fetch = (analytics.smart_products if args.sort in analytics.SMART_SORT_OPTIONS
             else repo.products)
    key = "by" if fetch is analytics.smart_products else "sort"

    rows = fetch(conn, limit=args.limit, on_sale=on_sale,
                 **{key: args.sort}, **filters)
    return rows, repo.count_products(conn, on_sale=on_sale, **filters)


def _export(rows: list[dict], fmt: str) -> None:
    """Write rows to data/exports/ in the requested format."""
    if not fmt or not rows:
        return
    import pandas as pd
    path = exporter.export_comparison(pd.DataFrame(rows), fmt)
    print(f"\n  Exportado: {path}")


def _browse_title(label: str, shown: int, total: int, sort: str) -> str:
    more = f" de {total}" if total > shown else ""
    return f"{label} ({shown}{more}) · orden: {sort}"


def cmd_deals(args) -> int:
    conn = _open_db()
    rows, total = _browse(conn, args, on_sale=True)
    render.product_rows(rows, title=_browse_title("Ofertas", len(rows), total, args.sort))
    _export(rows, args.export)
    return 0


def cmd_list(args) -> int:
    conn = _open_db()
    rows, total = _browse(conn, args, on_sale=False)
    render.product_rows(rows, title=_browse_title("Catálogo", len(rows), total, args.sort))
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
        render.watchlist(watch_mod.entries(conn))
        return 0

    hit = search_mod.best_match(conn, args.query)
    if not hit:
        raise CommandError(f"Sin resultados para '{args.query}'.")

    if args.action == "add":
        if not watch_mod.add(conn, hit["game_id"], target=args.target):
            raise CommandError(f"No se pudo seguir '{hit['title']}'.")
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


def cmd_update(args) -> int:
    try:
        from .scrape import sites
    except ImportError:
        from scrape import sites

    conn = _open_db(read_only=False)
    try:
        targets = update_mod.select_sites(
            conn, sites, args.sites, args.incremental, args.max_age)
    except update_mod.UnknownSiteError as exc:
        raise CommandError(str(exc))

    if not targets:
        print("Todo al día. Nada que actualizar.")
        return 0

    print(f"Actualizando {render.plural(len(targets), 'tienda')} "
          f"con {render.plural(args.workers, 'worker')}…")
    totals = update_mod.update_stores(
        conn, targets, workers=args.workers, dry_run=args.dry_run,
        on_failure=lambda name, exc: print(f"  [{name}] falló: {exc}"),
    )
    render.update_report(totals)
    return 0


def cmd_migrate(args) -> int:
    report = migrate_mod.migrate(rebuild=args.rebuild)
    render.migration_report(report, db_mod.DB_PATH, paths.DATA_DIR)
    return 0


def cmd_doctor(args) -> int:
    conn = _open_db()
    render.doctor(
        data_dir=paths.DATA_DIR,
        db_path=db_mod.DB_PATH,
        version=db_mod.schema_version(conn),
        counts=db_mod.table_counts(conn),
        without_price=repo.products_without_price(conn),
        stale=repo.stale_count(conn),
        cursor=changes.get_cursor(conn),
        outliers=validation.price_outliers(conn, sigma=args.sigma, limit=args.limit),
        sigma=args.sigma,
    )
    return 0


COMMANDS = {
    "search": cmd_search,
    "deals": cmd_deals,
    "list": cmd_list,
    "stores": cmd_stores,
    "leaderboard": cmd_leaderboard,
    "history": cmd_history,
    "new": cmd_new,
    "watch": cmd_watch,
    "alerts": cmd_alerts,
    "basket": cmd_basket,
    "update": cmd_update,
    "migrate": cmd_migrate,
    "doctor": cmd_doctor,
}


def _validate(parser, args) -> None:
    """Cross-flag rules argparse cannot express on its own."""
    if args.command == "watch" and args.action in ("add", "rm") and not args.query:
        parser.error(f"'watch {args.action}' necesita un juego")
    if args.command == "alerts" and args.watch and args.threshold is None:
        parser.error("--watch necesita --threshold")


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

    _validate(parser, args)

    try:
        return COMMANDS[args.command](args)
    except CommandError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except db_mod.SchemaVersionError as exc:
        print(f"Error: la base de datos es de otra versión del esquema.\n"
              f"  {exc}\n"
              f"  Ejecuta:  tablero migrate --rebuild", file=sys.stderr)
        return 1
    except ValueError as exc:
        # repo/analytics/export raise ValueError for bad arguments; without this
        # the user got a raw traceback for what is really a usage mistake.
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())

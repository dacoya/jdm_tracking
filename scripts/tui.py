"""
Interactive menu.

Rewritten over the SQLite query layer. Navigation fixes versus the previous
version:

  * Search results stay addressable -- picking a game shows its prices and
    returns to the same list instead of leaving it scrolled off screen.
  * One consistent widget set. The old drill-down dropped to a raw input()
    loop mid-flow, which broke arrow-key navigation inside the TUI.
  * Enter goes back. The old prompt accepted only a literal "0" and re-asked
    forever on an empty line.
  * The store picker filters as you type instead of listing 47 flat entries.
  * The worker prompt falls back to the documented default of 5; the previous
    fallback silently used 20, which provokes Cloudflare blocks.
"""
import questionary

try:
    from . import alerts as alerts_mod
    from . import analytics, basket as basket_mod
    from . import changes, cli, db as db_mod, export as exporter, history
    from . import render, repo, search as search_mod, watchlist as watch_mod
except ImportError:
    import alerts as alerts_mod
    import analytics
    import basket as basket_mod
    import changes
    import cli
    import db as db_mod
    import export as exporter
    import history
    import render
    import repo
    import search as search_mod
    import watchlist as watch_mod

BANNER = "\n🎲  tablero-cl — comparador de juegos de mesa\n"

SORT_LABELS = {
    "discount": "Mayor descuento",
    "price": "Más barato primero",
    "price_desc": "Más caro primero",
    "store": "Por tienda",
    "title": "Por nombre",
    # Derived orders: computed from cross-store comparison, not a single column.
    "value": "Mejor valor (bajo su mediana)",
    "scarcity": "Escasez (en pocas tiendas)",
    "volatility": "Volatilidad (mayor diferencia entre tiendas)",
}


def _ask(prompt):
    """Run a questionary prompt, returning None when cancelled."""
    try:
        return prompt.ask()
    except (KeyboardInterrupt, EOFError):
        return None


def _pause() -> None:
    """Wait for Enter. Any input returns -- the old version only accepted '0'."""
    try:
        input("\n  [Enter] para volver al menú… ")
    except (KeyboardInterrupt, EOFError):
        print()


def _ask_store(conn):
    """(ok, store_name). ok=False means cancel; store=None means all stores."""
    names = repo.store_names(conn, active_only=False)
    choice = _ask(questionary.autocomplete(
        "Tienda (vacío = todas, Tab para completar):",
        choices=names,
        ignore_case=True,
        match_middle=True,
    ))
    if choice is None:
        return False, None
    choice = choice.strip()
    if not choice:
        return True, None

    matches = repo.resolve_store(conn, choice)
    if len(matches) == 1:
        return True, matches[0]
    if not matches:
        print(f"  Tienda '{choice}' no encontrada.")
    else:
        print(f"  '{choice}' coincide con: {', '.join(matches)}")
    return False, None


def _ask_sort(default="discount"):
    return _ask(questionary.select(
        "Ordenar por:",
        choices=[questionary.Choice(label, value=key) for key, label in SORT_LABELS.items()],
        default=default,
    ))


def _ask_price(label):
    raw = _ask(questionary.text(f"{label} (vacío = sin límite):"))
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw.replace(".", "").replace(",", "."))
    except ValueError:
        print(f"  '{raw}' no es un número; se ignora.")
        return None


# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------

def _search_flow(conn) -> None:
    query = _ask(questionary.text("Nombre del juego:"))
    if not query or not query.strip():
        return

    hits = search_mod.search(conn, query.strip(), limit=20)
    if not hits:
        print(f"\n  Sin resultados para '{query.strip()}'.")
        return

    while True:
        render.search_results(hits, query.strip())
        choice = _ask(questionary.select(
            "Ver precios de:",
            choices=[
                questionary.Choice(
                    f"{h['title'][:44]}  ·  desde {render.money(h.get('min_price'))}"
                    f"  ·  {h.get('n_stores', 0)} tiendas",
                    value=h,
                )
                for h in hits
            ] + [questionary.Choice("← Volver al menú", value=None)],
        ))
        if choice is None:
            return

        render.price_table(repo.game_prices(conn, choice["game_id"]), choice["title"])
        if not _ask(questionary.confirm("¿Ver otro resultado?", default=True)):
            return


def _browse_flow(conn, on_sale: bool) -> None:
    ok, store = _ask_store(conn)
    if not ok:
        return
    in_stock = _ask(questionary.confirm("¿Solo disponibles?", default=False))
    if in_stock is None:
        return
    sort = _ask_sort()
    if sort is None:
        return

    if sort in analytics.SMART_SORT_OPTIONS:
        rows = analytics.smart_products(conn, by=sort, limit=100, store=store,
                                        in_stock_only=in_stock, on_sale=on_sale)
    else:
        rows = repo.products(conn, sort=sort, limit=100, store=store,
                             in_stock_only=in_stock, on_sale=on_sale)
    label = "Ofertas" if on_sale else "Catálogo"
    render.product_rows(rows, title=f"{label} ({len(rows)}) · orden: {sort}")
    _offer_export(rows)


def _offer_export(rows) -> None:
    """After showing results, offer to write them out."""
    if not rows:
        return
    fmt = _ask(questionary.select("¿Exportar?", choices=[
        questionary.Choice("No", value=None),
        questionary.Choice("CSV", value="csv"),
        questionary.Choice("JSON", value="json"),
        questionary.Choice("HTML", value="html"),
    ]))
    if not fmt:
        return
    import pandas as pd
    print(f"  Exportado: {exporter.export_comparison(pd.DataFrame(rows), fmt)}")


def _leaderboard_flow(conn) -> None:
    rows = analytics.store_leaderboard(conn, limit=25)
    render.leaderboard(rows)
    _offer_export(rows)


def _history_flow(conn) -> None:
    query = _ask(questionary.text("Juego:"))
    if not query or not query.strip():
        return
    hit = search_mod.best_match(conn, query.strip())
    if not hit:
        print(f"\n  Sin resultados para '{query.strip()}'.")
        return
    trends = history.game_trends(conn, hit["game_id"], min_points=2)
    if not trends:
        # Fall back rather than showing nothing: one observation is still a
        # price, it just is not yet a trend.
        trends = history.game_trends(conn, hit["game_id"], min_points=1)
        if trends:
            print("\n  (solo una observación por tienda; el historial crece "
                  "con cada actualización)")
    render.trends(trends, hit["title"], min_points=1)


def _alerts_flow(conn) -> None:
    source = _ask(questionary.select("¿Qué vigilar?", choices=[
        questionary.Choice("Mi lista de seguimiento", value="watch"),
        questionary.Choice("Consultas puntuales", value="adhoc"),
    ]))
    if source is None:
        return

    if source == "watch":
        found = alerts_mod.from_watchlist(conn)
        render.alerts(found, "lista de seguimiento")
        return

    raw = _ask(questionary.text("Juegos separados por coma:"))
    if not raw or not raw.strip():
        return
    threshold = _ask_price("Umbral de precio")
    if threshold is None:
        print("  Se necesita un umbral.")
        return
    queries = [q.strip() for q in raw.split(",") if q.strip()]
    render.alerts(alerts_mod.from_queries(conn, queries, threshold),
                  f"{len(queries)} consulta(s)")


def _watch_flow(conn) -> None:
    action = _ask(questionary.select("Lista de seguimiento:", choices=[
        questionary.Choice("Ver la lista", value="list"),
        questionary.Choice("Agregar un juego", value="add"),
        questionary.Choice("Quitar un juego", value="rm"),
    ]))
    if action is None:
        return

    if action == "list":
        entries = watch_mod.entries(conn)
        if not entries:
            print("\n  La lista está vacía.")
            return
        render.table(
            [{
                "title": e["title"],
                "target": render.money(e["target"]),
                "price": render.money(e["min_price"]),
                "stores": e["n_stores"],
                "hit": "¡SÍ!" if e["hit"] else "",
            } for e in entries],
            [("title", "Juego", True), ("target", "Objetivo", False),
             ("price", "Actual", False), ("stores", "Tiendas", False),
             ("hit", "Alcanzado", False)],
            title=f"Lista de seguimiento ({len(entries)})",
        )
        return

    if action == "rm":
        entries = watch_mod.entries(conn)
        if not entries:
            print("\n  La lista está vacía.")
            return
        target = _ask(questionary.select("Quitar:", choices=[
            questionary.Choice(e["title"], value=e["game_id"]) for e in entries
        ]))
        if target is not None:
            watch_mod.remove(conn, target)
            print("  Quitado.")
        return

    query = _ask(questionary.text("Juego a seguir:"))
    if not query or not query.strip():
        return
    hit = search_mod.best_match(conn, query.strip())
    if not hit:
        print(f"  Sin resultados para '{query.strip()}'.")
        return
    target = _ask_price(f"Precio objetivo para {hit['title']}")
    watch_mod.add(conn, hit["game_id"], target=target)
    print(f"  Siguiendo: {hit['title']}")


def _basket_flow(conn) -> None:
    use_watch = _ask(questionary.confirm(
        "¿Usar la lista de seguimiento?", default=True))
    if use_watch is None:
        return

    if use_watch:
        ids = watch_mod.game_ids(conn)
        if not ids:
            print("\n  La lista de seguimiento está vacía.")
            return
    else:
        raw = _ask(questionary.text("Juegos separados por coma:"))
        if not raw or not raw.strip():
            return
        ids = []
        for part in (p.strip() for p in raw.split(",") if p.strip()):
            hit = search_mod.best_match(conn, part)
            print(f"  {part:<24} → {hit['title'] if hit else '(sin resultados)'}")
            if hit:
                ids.append(hit["game_id"])
        if not ids:
            return

    shipping = _ask_price("Costo de envío por tienda")
    render.basket_plans(basket_mod.optimize(
        conn, ids,
        shipping=shipping if shipping is not None else basket_mod.DEFAULT_SHIPPING,
    ))


def _changes_flow(conn) -> None:
    if changes.get_cursor(conn) is None:
        print("\n  No hay marcador de última revisión.")
        if _ask(questionary.confirm("¿Fijarlo ahora?", default=True)):
            changes.set_cursor(conn)
            print("  Marcador fijado. Los cambios se listarán desde la próxima actualización.")
        return

    drops = changes.price_drops(conn, min_pct=5.0, limit=50)
    render.product_rows(
        [{**d, "price_original": d["old_price"], "price_current": d["new_price"],
          "discount_pct": d["drop_pct"]} for d in drops],
        title=f"Bajadas desde tu última revisión ({len(drops)})",
    )
    if drops and _ask(questionary.confirm("¿Marcar como revisado?", default=False)):
        changes.set_cursor(conn)
        print("  Marcador actualizado.")


def _stores_flow(conn) -> None:
    rows = [{
        "name": s["name"],
        "products": s["n_products"],
        "stock": s["n_in_stock"] or 0,
        "active": "sí" if s["active"] else "no",
    } for s in repo.stores(conn)]
    render.table(rows, [
        ("name", "Tienda", True), ("products", "Productos", False),
        ("stock", "En stock", False), ("active", "Activa", False),
    ], title=f"Tiendas ({len(rows)})")


def _update_flow(conn) -> None:
    scope = _ask(questionary.select("¿Qué actualizar?", choices=[
        questionary.Choice("Solo tiendas obsoletas (recomendado)", value="incremental"),
        questionary.Choice("Todas las tiendas", value="all"),
        questionary.Choice("Elegir tiendas", value="some"),
    ]))
    if scope is None:
        return

    names = None
    if scope == "some":
        names = _ask(questionary.checkbox(
            "Tiendas:", choices=repo.store_names(conn, active_only=True)))
        if not names:
            return

    raw = _ask(questionary.text("Workers concurrentes:", default="5"))
    if raw is None:
        return
    try:
        workers = max(1, int(raw))
    except ValueError:
        # The documented default. The old code fell back to 20 here, which is
        # four times this and reliably provokes Cloudflare blocks.
        workers = 5
        print("  Valor inválido; usando 5.")

    dry_run = _ask(questionary.confirm("¿Dry run (solo 1 página)?", default=False))
    if dry_run is None:
        return
    if not _ask(questionary.confirm(
            "Esto hará scraping en vivo. ¿Continuar?", default=True)):
        return

    args = cli.build_parser().parse_args(["update"])
    args.sites, args.workers, args.dry_run = names, workers, dry_run
    args.incremental, args.max_age = (scope == "incremental"), 24
    cli.cmd_update(args)


_ACTIONS = {
    "search": _search_flow,
    "deals": lambda conn: _browse_flow(conn, on_sale=True),
    "list": lambda conn: _browse_flow(conn, on_sale=False),
    "changes": _changes_flow,
    "watch": _watch_flow,
    "basket": _basket_flow,
    "stores": _stores_flow,
    "leaderboard": _leaderboard_flow,
    "history": _history_flow,
    "alerts": _alerts_flow,
    "update": _update_flow,
}


def run_tui() -> None:
    print(BANNER)
    try:
        conn = db_mod.connect()
    except FileNotFoundError:
        print("No hay base de datos. Ejecuta:  tablero migrate")
        return

    try:
        while True:
            action = _ask(questionary.select("¿Qué quieres hacer?", choices=[
                questionary.Choice("🔍  Buscar un juego", value="search"),
                questionary.Choice("🏷   Ver ofertas", value="deals"),
                questionary.Choice("📋  Listar catálogo", value="list"),
                questionary.Choice("📉  Cambios desde mi última revisión", value="changes"),
                questionary.Choice("⭐  Lista de seguimiento", value="watch"),
                questionary.Choice("🛒  Dónde comprar (carrito)", value="basket"),
                questionary.Choice("🏪  Tiendas", value="stores"),
                questionary.Choice("🏆  Leaderboard de tiendas", value="leaderboard"),
                questionary.Choice("📈  Historial de precios", value="history"),
                questionary.Choice("🔔  Avisos de precio", value="alerts"),
                questionary.Choice("🔄  Actualizar precios", value="update"),
                questionary.Choice("✖   Salir", value="quit"),
            ]))
            if action in (None, "quit"):
                break
            _ACTIONS[action](conn)
            _pause()
    finally:
        conn.close()
        print("\n¡Hasta luego! 🎲")


if __name__ == "__main__":
    run_tui()

"""
Interactive terminal UI for tablero-cl.

Wraps the same search / deals / list / update operations exposed by the CLI
flags behind an arrow-key menu, so flag syntax doesn't have to be memorized.
Launched automatically when `tablero` is run with no arguments.

The flows only *gather inputs* and dispatch to the existing mode functions in
main.py — those keep rendering their own tables, so output is unchanged.
"""
import questionary
from questionary import Choice

try:  # installed as the `tablero` package
    from .main import (
        search_mode, deals_mode, list_mode, update_mode,
        incremental_update, leaderboard_mode, history_mode, alerts_mode,
        ALL_SORT_OPTIONS,
    )
    from .scrape import sites
    from . import export as exporter
except ImportError:  # run directly from scripts/
    from main import (
        search_mode, deals_mode, list_mode, update_mode,
        incremental_update, leaderboard_mode, history_mode, alerts_mode,
        ALL_SORT_OPTIONS,
    )
    from scrape import sites
    import export as exporter


_BANNER = "\n🎲  tablero-cl — comparador de precios de juegos de mesa\n"

# Sentinel for the "all stores" choice, kept distinct from None so it can be
# told apart from an ESC/cancel (which makes questionary return None).
_ALL_STORES = "__ALL__"


def _store_names() -> list[str]:
    """Store names from the site registry, alphabetically sorted."""
    return sorted(s["name"] for s in sites)


def _ask_store():
    """
    Prompt for a store filter.

    Returns ``(ok, store)`` where ``ok`` is False if the user cancelled, and
    ``store`` is a store name or None ("all stores") otherwise.
    """
    choices = [Choice("Todas las tiendas", value=_ALL_STORES)]
    choices += [Choice(n, value=n) for n in _store_names()]
    sel = questionary.select("Tienda:", choices=choices).ask()
    if sel is None:
        return False, None
    return True, (None if sel == _ALL_STORES else sel)


def _ask_sort(options, default="discount"):
    """Prompt for a sort order from a tuple of option strings (None if cancelled)."""
    return questionary.select(
        "Ordenar por:",
        choices=list(options),
        default=default if default in options else options[0],
    ).ask()


def _ask_optional_price(label):
    """Optional price prompt — blank or cancel yields None."""
    value = questionary.text(label).ask()
    if not value:
        return None
    return value.strip() or None


def _search_flow():
    query = questionary.text("Nombre del juego a buscar:").ask()
    if not query or not query.strip():
        return
    search_mode(query.strip())


def _offer_export(df):
    """After a result is shown, optionally export it to csv/json/html."""
    if df is None or getattr(df, "empty", True):
        return
    fmt = questionary.select(
        "¿Exportar resultados?",
        choices=[
            Choice("No", value=None),
            Choice("CSV", value="csv"),
            Choice("JSON", value="json"),
            Choice("HTML", value="html"),
        ],
        default="No",
    ).ask()
    if not fmt:
        return
    path = exporter.export_comparison(df, fmt=fmt)
    print(f"Exportado ({fmt}) → {path}")


def _deals_flow():
    ok, store = _ask_store()
    if not ok:
        return
    in_stock = questionary.confirm("¿Solo productos disponibles?", default=False).ask()
    if in_stock is None:
        return
    lower = _ask_optional_price("Precio mínimo (Enter para omitir):")
    higher = _ask_optional_price("Precio máximo (Enter para omitir):")
    sort_by = _ask_sort(ALL_SORT_OPTIONS, "discount")
    if sort_by is None:
        return
    result = deals_mode(
        store_filter=store,
        in_stock_only=bool(in_stock),
        lower_price=lower,
        higher_price=higher,
        sort_by=sort_by,
    )
    _offer_export(result)


def _list_flow():
    ok, store = _ask_store()
    if not ok:
        return
    in_stock = questionary.confirm("¿Solo productos disponibles?", default=False).ask()
    if in_stock is None:
        return
    sort_by = _ask_sort(ALL_SORT_OPTIONS, "discount")
    if sort_by is None:
        return
    result = list_mode(store_filter=store, sort_by=sort_by, in_stock_only=bool(in_stock))
    _offer_export(result)


def _leaderboard_flow():
    leaderboard_mode()


def _history_flow():
    query = questionary.text("Juego para ver historial de precios:").ask()
    if not query or not query.strip():
        return
    history_mode(query.strip())


def _alert_flow():
    raw = questionary.text("Juegos a vigilar (separados por coma):").ask()
    if not raw or not raw.strip():
        return
    games = [g.strip() for g in raw.split(",") if g.strip()]
    if not games:
        return
    threshold_raw = questionary.text("Alertar si el mejor precio es <= (CLP):").ask()
    try:
        threshold = float(threshold_raw.replace(".", "").replace(",", "").strip())
    except (ValueError, AttributeError):
        print("Umbral inválido.")
        return
    alerts_mode(games, threshold)


def _update_flow():
    scope = questionary.select(
        "¿Qué actualizar?",
        choices=[
            Choice("Todas las tiendas", value="all"),
            Choice("Elegir tiendas específicas", value="some"),
        ],
    ).ask()
    if scope is None:
        return

    site_names = None
    if scope == "some":
        site_names = questionary.checkbox(
            "Selecciona tiendas (espacio para marcar, Enter para confirmar):",
            choices=_store_names(),
        ).ask()
        if not site_names:
            print("No se seleccionaron tiendas.")
            return

    dry_run = questionary.confirm(
        "¿Dry-run? (solo página 1 por tienda, para pruebas)", default=False
    ).ask()
    if dry_run is None:
        return

    workers_raw = questionary.text("Workers concurrentes:", default="20").ask()
    if workers_raw is None:
        return
    try:
        workers = max(1, int(workers_raw.strip()))
    except (ValueError, AttributeError):
        print("Número de workers inválido; usando 20.")
        workers = 20

    incremental = questionary.confirm(
        "¿Incremental? (solo tiendas con datos de más de 24h)", default=False
    ).ask()
    if incremental is None:
        return

    if not questionary.confirm(
        "Esto hará scraping en vivo de los sitios. ¿Continuar?", default=True
    ).ask():
        return

    if incremental:
        incremental_update(site_names=site_names, max_age_hours=24,
                           workers=workers, dry_run=dry_run)
    else:
        update_mode(workers=workers, dry_run=dry_run, site_names=site_names)


_ACTIONS = {
    "search": _search_flow,
    "deals": _deals_flow,
    "list": _list_flow,
    "leaderboard": _leaderboard_flow,
    "history": _history_flow,
    "alert": _alert_flow,
    "update": _update_flow,
}

# Search runs its own "0 para volver al menú" drill-down loop, so it shouldn't get
# the shared post-action pause on top of it.
_SELF_PAUSING = {"search"}


def _wait_for_back():
    """Pause after an action; return to the main menu when the user enters 0."""
    while True:
        ans = questionary.text("Ingresa 0 para volver al menú:").ask()
        if ans is None or ans.strip() == "0":
            return


def run_tui():
    """Run the interactive menu loop until the user quits."""
    print(_BANNER)
    try:
        while True:
            action = questionary.select(
                "¿Qué quieres hacer?",
                choices=[
                    Choice("🔍  Buscar un juego", value="search"),
                    Choice("🏷   Ver ofertas", value="deals"),
                    Choice("📋  Listar catálogo", value="list"),
                    Choice("🏆  Leaderboard de tiendas", value="leaderboard"),
                    Choice("📈  Historial de precios", value="history"),
                    Choice("🔔  Alertas de precio", value="alert"),
                    Choice("🔄  Actualizar precios", value="update"),
                    Choice("✖   Salir", value="quit"),
                ],
            ).ask()

            if action is None or action == "quit":
                break

            _ACTIONS[action]()
            if action not in _SELF_PAUSING:
                _wait_for_back()
    except KeyboardInterrupt:
        pass

    print("\n¡Hasta luego! 🎲")

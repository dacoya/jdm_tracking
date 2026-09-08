"""
Argument parser declaration.

Split out of cli.py: this is pure declaration with no logic, and separating it
lets cli.py read as a list of what each command actually does.

Subcommands rather than a flat flag ladder -- the old CLI checked modes in
precedence order, so `tablero -u --name x` ran a search and never scraped.

Commands are named, not bound to functions here, so this module stays free of
any dependency on cli.py; the dispatch table lives there.
"""
import argparse

try:
    from .basket import DEFAULT_SHIPPING
    from .classify import KIND_ORDER
except ImportError:
    from basket import DEFAULT_SHIPPING
    from classify import KIND_ORDER

SORTS = ("discount", "price", "price_desc", "store", "title",
         "value", "scarcity", "volatility")
EXPORT_FORMATS = ("csv", "json", "html")

# Shared with the TUI so both surfaces show the same amount of data. The TUI
# used to hardcode its own numbers (20/100/25/50) that drifted from these.
DEFAULT_LIMIT = 50
SEARCH_LIMIT = 20
LEADERBOARD_LIMIT = 20
DEFAULT_WORKERS = 5
DEFAULT_MIN_DROP_PCT = 5.0
DEFAULT_MIN_POINTS = 2


def _add_export_flag(p) -> None:
    p.add_argument("--export", choices=EXPORT_FORMATS, metavar="FMT",
                   help=f"exportar a data/exports/ ({'/'.join(EXPORT_FORMATS)})")


def _add_browse_flags(p) -> None:
    p.add_argument("--store", metavar="NAME",
                   help="filtrar por tienda (acepta coincidencia parcial)")
    p.add_argument("--in-stock", action="store_true",
                   help="mostrar solo productos disponibles")
    p.add_argument("--min-price", type=float, metavar="N",
                   help="precio mínimo en pesos (sobre el precio efectivo)")
    p.add_argument("--max-price", type=float, metavar="N",
                   help="precio máximo en pesos (sobre el precio efectivo)")
    p.add_argument("--kind", choices=KIND_ORDER, nargs="+",
                   help="filtrar por tipo de producto")
    p.add_argument("--include-stale", action="store_true",
                   help="incluir productos ausentes del último scrape de su tienda")
    p.add_argument("--sort", choices=SORTS, default="discount",
                   help="orden (default: discount). value/scarcity/volatility "
                        "se calculan comparando entre tiendas")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT, metavar="N",
                   help=f"máximo de filas (default: {DEFAULT_LIMIT})")
    _add_export_flag(p)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tablero",
        description="Comparador de precios de juegos de mesa en Chile.",
        epilog="Sin argumentos abre el menú interactivo. "
               "'tablero COMANDO --help' detalla cada comando.",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMANDO")

    p = sub.add_parser("search", help="buscar un juego y comparar precios")
    p.add_argument("query", help="nombre del juego (tolera errores de tipeo)")
    p.add_argument("--limit", type=int, default=SEARCH_LIMIT, metavar="N",
                   help=f"máximo de resultados (default: {SEARCH_LIMIT})")
    p.add_argument("--first", action="store_true",
                   help="mostrar directamente los precios del primer resultado")
    p.add_argument("--all-kinds", action="store_true",
                   help="incluir accesorios (fundas, dados), ocultos por defecto")
    p.add_argument("--include-stale", action="store_true",
                   help="incluir productos ausentes del último scrape de su tienda")

    p = sub.add_parser("deals", help="productos en oferta")
    _add_browse_flags(p)

    p = sub.add_parser("list", help="listar el catálogo")
    _add_browse_flags(p)

    p = sub.add_parser("stores", help="tiendas cubiertas y su estado")
    p.add_argument("--active", action="store_true",
                   help="solo tiendas en el registro de scraping")

    p = sub.add_parser("leaderboard", help="ranking de tiendas, más barata primero")
    p.add_argument("--limit", type=int, default=LEADERBOARD_LIMIT, metavar="N",
                   help=f"máximo de tiendas (default: {LEADERBOARD_LIMIT})")
    _add_export_flag(p)

    p = sub.add_parser("history", help="evolución de precios de un juego")
    p.add_argument("query", help="nombre del juego")
    p.add_argument("--min-points", type=int, default=DEFAULT_MIN_POINTS, metavar="N",
                   help=f"ocultar series con menos observaciones "
                        f"(default: {DEFAULT_MIN_POINTS}; una sola no es tendencia)")
    _add_export_flag(p)

    p = sub.add_parser("new", help="cambios desde tu última revisión")
    p.add_argument("--reset", action="store_true",
                   help="marcar todo como revisado a partir de ahora")
    p.add_argument("--min-pct", type=float, default=DEFAULT_MIN_DROP_PCT, metavar="N",
                   help=f"bajada mínima a reportar (default: {DEFAULT_MIN_DROP_PCT}%%)")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT, metavar="N",
                   help=f"máximo de filas (default: {DEFAULT_LIMIT})")

    p = sub.add_parser("watch", help="lista de seguimiento con precios objetivo")
    p.add_argument("action", choices=("add", "rm", "list"))
    p.add_argument("query", nargs="?", help="juego (para add/rm)")
    p.add_argument("--target", type=float, metavar="N",
                   help="precio objetivo; 'tablero alerts' avisa al alcanzarlo")

    p = sub.add_parser("alerts", help="avisos de precio, pensado para cron")
    p.add_argument("--watch", nargs="+", metavar="JUEGO",
                   help="consultas puntuales; por defecto usa la lista de seguimiento")
    p.add_argument("--threshold", type=float, metavar="N",
                   help="umbral de precio, obligatorio con --watch")
    p.add_argument("--in-stock", action="store_true",
                   help="considerar solo ofertas disponibles")
    p.add_argument("--out", metavar="FILE", help="escribir los avisos como JSON")

    p = sub.add_parser("basket", help="dónde comprar una lista de juegos")
    p.add_argument("games", nargs="*", help="nombres de juegos")
    p.add_argument("--from-watchlist", action="store_true",
                   help="usar la lista de seguimiento en vez de argumentos")
    p.add_argument("--shipping", type=float, default=DEFAULT_SHIPPING, metavar="N",
                   help=f"costo de envío por tienda (default: {DEFAULT_SHIPPING:.0f})")
    p.add_argument("--include-oos", action="store_true",
                   help="considerar también productos agotados")

    p = sub.add_parser("update", help="scrapear tiendas y actualizar la base")
    p.add_argument("--sites", nargs="+", metavar="NAME", help="solo estas tiendas")
    p.add_argument("-w", "--workers", type=int, default=DEFAULT_WORKERS, metavar="N",
                   help=f"hilos concurrentes (default: {DEFAULT_WORKERS}; "
                        f"subirlo agrava los bloqueos de Cloudflare)")
    p.add_argument("--dry-run", action="store_true",
                   help="solo la primera página por tienda, para probar")
    p.add_argument("--incremental", action="store_true",
                   help="solo tiendas sin scrape reciente (ver --max-age)")
    p.add_argument("--max-age", type=float, default=24, metavar="H",
                   help="antigüedad máxima en horas para --incremental (default: 24)")

    p = sub.add_parser("migrate", help="construir o reconstruir la base SQLite")
    p.add_argument("--rebuild", action="store_true",
                   help="reemplazar la base existente, conservando seguimiento "
                        "y marcadores (necesario tras un cambio de esquema)")

    p = sub.add_parser("doctor", help="estado de la base y precios atípicos")
    p.add_argument("--sigma", type=float, default=5.0, metavar="N",
                   help="umbral de desvío para precios atípicos (default: 5)")
    p.add_argument("--limit", type=int, default=10, metavar="N",
                   help="máximo de atípicos a mostrar (default: 10)")

    return parser

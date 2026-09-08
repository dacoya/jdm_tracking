"""
Terminal rendering.

Presentation only -- every function takes plain data (list[dict]) and writes to
stdout. Keeping this separate from the query layer is what lets the same
queries feed a phone export without dragging terminal formatting along.

Tables size themselves to the actual terminal. The previous renderer capped the
URL column at 100 characters with no width awareness, so a listing row ran past
160 columns and wrapped in any normal window.
"""
import os
import shutil
import subprocess
import sys

try:
    from .classify import KIND_GAME
except ImportError:
    from classify import KIND_GAME

FLAG_MARK = {"new": "🆕", "restock": "🔄"}
KIND_MARK = {"expansion": "+exp", "accessory": "acc", "tcg": "tcg", "puzzle": "puz"}

MIN_COL = 6
GUTTER = 2

# Flexible columns stay this narrow by default instead of consuming every spare
# column. Keeps the table compact and scannable; _widths grows past it only to
# keep genuinely different rows distinguishable.
MAX_FLEX_COL = 38

# Fallback when PAGER is unset. Most systems have less; more is the floor.
DEFAULT_PAGER = "less"

# Applied to less only when the user has not set LESS themselves, the same way
# git does it: -F skips the pager when the text already fits, -R keeps styling,
# -X leaves the output on screen instead of wiping it on exit.
DEFAULT_LESS_OPTS = "FRX"


def term_size() -> os.terminal_size:
    return shutil.get_terminal_size((100, 24))


def term_width(default: int = 100) -> int:
    return shutil.get_terminal_size((default, 24)).columns


def _pager_command() -> list[str] | None:
    """The pager to use, or None when output should not be paged."""
    if not sys.stdout.isatty():
        return None                     # piped or redirected: never page
    pager = os.environ.get("PAGER", DEFAULT_PAGER).strip()
    return pager.split() if pager else None


def page(text: str) -> None:
    """
    Print `text`, routing it through a pager when it will not fit on screen.

    Only pages an interactive terminal; a pipe or a redirect gets the raw text
    so `tablero list | head` and `--export` keep working. Falls back to a plain
    print if the pager is missing or the user quits it early.
    """
    lines = text.count("\n") + 1
    command = _pager_command()
    if command is None or lines <= term_size().lines - 1:
        print(text)
        return

    env = dict(os.environ)
    if os.path.basename(command[0]) == "less":
        env.setdefault("LESS", DEFAULT_LESS_OPTS)

    try:
        subprocess.run(command, input=text, text=True, check=False, env=env)
    except (OSError, KeyboardInterrupt):
        # Pager missing, or the user quit it: the output still has to appear.
        print(text)


def plural(n: int, singular: str, plural_form: str = None) -> str:
    """'1 tienda' / '2 tiendas' -- the count and its correctly-inflected noun."""
    word = singular if abs(n) == 1 else (plural_form or singular + "s")
    return f"{n} {word}"


def money(value) -> str:
    """Chilean peso formatting: $69.990 (dot thousands, no decimals)."""
    if value is None:
        return "-"
    try:
        return "$" + f"{float(value):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "-"


def pct(value) -> str:
    return "-" if value is None else f"-{float(value):.0f}%"


def stock_label(in_stock) -> str:
    if in_stock is None:
        return "?"
    return "Disponible" if in_stock else "Agotado"


def _truncate(text: str, width: int) -> str:
    text = "" if text is None else str(text)
    return text if len(text) <= width else text[: max(1, width - 1)] + "…"


def _ambiguous(rows: list[dict], key: str, width: int) -> bool:
    """
    True when truncating `key` to `width` merges rows that really differ.

    Catalogs are full of long shared prefixes -- four different L5R packs all
    begin "La Leyenda de los Cinco Anillos LCG:" -- so a narrow column can
    render genuinely distinct products as the same string.
    """
    values = [str(r.get(key, "") or "") for r in rows]
    shown = [_truncate(v, width) for v in values]
    return len(set(shown)) < len(set(values))


def _widths(rows: list[dict], columns: list[tuple], available: int) -> list[int]:
    """
    Column widths that fit `available`.

    Flexible columns start compact rather than absorbing every spare column --
    a single long title used to stretch the whole table and leave a ragged gap
    after every short one. They grow back only when the compact width would
    make different rows indistinguishable, and shrink again if the terminal
    cannot fit that.
    """
    natural = [
        max(len(label), *(len(str(r.get(key, "") or "")) for r in rows)) if rows else len(label)
        for key, label, _ in columns
    ]
    flexible = [i for i, (_, _, flex) in enumerate(columns) if flex]
    widths = [
        min(w, MAX_FLEX_COL) if i in flexible else w
        for i, w in enumerate(natural)
    ]

    def total() -> int:
        return sum(widths) + GUTTER * (len(widths) - 1)

    for i in flexible:
        key = columns[i][0]
        headroom = min(natural[i], widths[i] + available - total())
        # Only widen when widening actually resolves the ambiguity. Over a full
        # catalog some titles are near-identical no matter how much room they
        # get, and growing regardless would surrender the compact layout on
        # every long listing for no gain.
        if headroom <= widths[i] or _ambiguous(rows, key, headroom):
            continue
        lo, hi = widths[i], headroom
        while lo < hi:                      # smallest width that disambiguates
            mid = (lo + hi) // 2
            if _ambiguous(rows, key, mid):
                lo = mid + 1
            else:
                hi = mid
        widths[i] = lo

    remaining = list(flexible)
    while total() > available and remaining:
        widest = max(remaining, key=lambda i: widths[i])
        if widths[widest] <= MIN_COL:
            remaining.remove(widest)
            continue
        widths[widest] -= 1
    return widths


def table(rows: list[dict], columns: list[tuple], title: str = "",
          limit: int = None, empty: str = "(sin resultados)",
          footer: str = "") -> None:
    """
    Render rows as an aligned table, paging when it will not fit on screen.

    `columns` is a list of (key, label, flexible) -- flexible columns absorb the
    shrinking when the terminal is narrow.

    The heading prints even when there are no rows: a bare "(sin resultados)"
    gives no clue which query came up empty.
    """
    out = []
    if title:
        out.append(f"\n{title}")

    if not rows:
        out.append(f"  {empty}")
        page("\n".join(out))
        return

    shown = rows[:limit] if limit else rows
    widths = _widths(shown, columns, term_width() - 2)

    # Labels are truncated like any other cell. Padding them without truncating
    # let a header outgrow its column on a narrow terminal and slide out of
    # alignment with the data beneath it.
    out.append("  ".join(
        _truncate(label, w).ljust(w) for (_, label, _), w in zip(columns, widths)
    ))
    out.append("  ".join("-" * w for w in widths))

    for row in shown:
        cells = (
            _truncate(row.get(key, ""), w).ljust(w)
            for (key, _, _), w in zip(columns, widths)
        )
        out.append("  ".join(cells).rstrip())

    if limit and len(rows) > limit:
        out.append(f"  … y {len(rows) - limit} más")
    if footer:
        out.append(footer)
    page("\n".join(out))


def _marks(hit: dict) -> str:
    """Kind and change badges for one search hit."""
    kind = hit.get("kind")
    parts = []
    if kind not in (KIND_GAME, None):
        # .get(): a kind added to classify without a mark here must not crash
        # the whole search view.
        parts.append(KIND_MARK.get(kind, kind[:3]))
    if hit.get("is_new"):
        parts.append(FLAG_MARK["new"])
    elif hit.get("is_restock"):
        parts.append(FLAG_MARK["restock"])
    return ("  " + " ".join(parts)) if parts else ""


def hit_label(hit: dict, title_width: int = 38) -> str:
    """
    One search result as a single line.

    Shared by the CLI's numbered list and the TUI's picker so both carry the
    same facts. The TUI used to print the full list and then immediately show
    the identical set again as selectable rows -- every result twice on screen.
    """
    stock = "" if hit.get("in_stock") else " · agotado"
    return (
        f"{_truncate(hit['title'], title_width):<{title_width}} "
        f"desde {money(hit.get('min_price')):>10} · "
        f"{plural(hit.get('n_stores', 0), 'tienda'):>10}{stock}{_marks(hit)}"
    )


def hit_title_width(hits: list[dict], cap: int = MAX_FLEX_COL) -> int:
    """Width for the title column: the longest title shown, never past `cap`."""
    longest = max((len(h.get("title") or "") for h in hits), default=0)
    return max(MIN_COL, min(longest, cap))


def search_results(hits: list[dict], query: str) -> None:
    """The numbered pick list. Compact by design -- it must survive on screen."""
    width = hit_title_width(hits)
    out = [f"\nResultados para '{query}' ({len(hits)} encontrados):\n"]
    out += [f"  {i:>3}. {hit_label(h, width)}" for i, h in enumerate(hits, 1)]
    page("\n".join(out))


def price_table(offers: list[dict], title: str) -> None:
    rows = [
        {
            "store": o["store"],
            "orig": money(o.get("price_original")),
            "offer": money(o.get("price_current")),
            "disc": pct(o["discount_pct"]) if o.get("discount_pct") else "-",
            "stock": stock_label(o.get("in_stock")),
            "url": o.get("url", ""),
        }
        for o in offers
    ]
    table(rows, [
        ("store", "Tienda", False),
        ("orig", "Precio", False),
        ("offer", "Oferta", False),
        ("disc", "Desc.", False),
        ("stock", "Disponibilidad", False),
        ("url", "URL", True),
    ], title=f"\n{title}")


def product_rows(rows: list[dict], title: str = "", limit: int = None) -> None:
    prepared = [
        {
            "title": (FLAG_MARK.get(r.get("flag"), "") + " " + (r.get("title") or "")).strip(),
            "store": r.get("store", ""),
            "price": money(r.get("price_original")),
            "offer": money(r.get("price_current")),
            "disc": pct(r["discount_pct"]) if r.get("discount_pct") else "-",
            "stock": stock_label(r.get("in_stock")),
        }
        for r in rows
    ]
    table(prepared, [
        ("title", "Producto", True),
        ("store", "Tienda", False),
        ("price", "Precio", False),
        ("offer", "Oferta", False),
        ("disc", "Desc.", False),
        ("stock", "Estado", False),
    ], title=title, limit=limit)


def leaderboard(rows: list[dict]) -> None:
    if not rows:
        print("  (sin datos para el leaderboard)")
        return

    prepared = [
        {
            "store": r["store"],
            "n": r["n"],
            "median": money(r.get("median_price")),
            "disc": f"{(r.get('mean_discount') or 0) * 100:.0f}%",
            "oos": f"{(r.get('oos_ratio') or 0) * 100:.0f}%",
            "comp": ("-" if r.get("competitiveness") is None
                     else f"{r['competitiveness'] * 100:.0f}%"),
        }
        for r in rows
    ]
    table(prepared, [
        ("store", "Tienda", True),
        ("n", "Productos", False),
        ("median", "Precio mediano", False),
        ("disc", "Desc. prom.", False),
        ("oos", "Agotado", False),
        ("comp", "Más caro", False),
    ], title="\n🏆  Tiendas — más barata primero",
       footer='\n  "Más caro" = % de juegos disputados en que la tienda supera '
              'la mediana entre tiendas.')


def trends(rows: list[dict], title: str, min_points: int = 2) -> None:
    if not rows:
        print(f"\n  {title}: sin historial suficiente "
              f"(se necesitan {min_points}+ observaciones por tienda).")
        print("  El historial se acumula con cada 'tablero update'.")
        return

    prepared = [
        {
            "store": t.get("label") or t["store"],
            "spark": t["spark"],
            "first": money(t["first"]),
            "last": money(t["last"]),
            "change": f"{t['change_pct']:+.0f}%",
            "range": f"{money(t['min'])} – {money(t['max'])}",
            "n": t["n"],
        }
        for t in rows
    ]
    table(prepared, [
        ("store", "Tienda", True),
        ("spark", "Evolución", False),
        ("first", "Primero", False),
        ("last", "Último", False),
        ("change", "Cambio", False),
        ("range", "Rango", False),
        ("n", "Obs.", False),
    ], title=f"\nHistorial de precios — {title}")


def alerts(rows: list[dict], source: str) -> None:
    if not rows:
        print(f"\n  Sin avisos ({source}).")
        return

    prepared = [
        {
            "title": a["matched_title"],
            "store": a["store"],
            "price": money(a["price"]),
            "target": money(a["threshold"]),
            "stock": "sí" if a.get("in_stock") else "no",
        }
        for a in rows
    ]
    table(prepared, [
        ("title", "Juego", True),
        ("store", "Tienda", False),
        ("price", "Precio", False),
        ("target", "Objetivo", False),
        ("stock", "Stock", False),
    ], title=f"\n🔔  {len(rows)} aviso(s) — {source}")


def watchlist(entries: list[dict]) -> None:
    """The watchlist table. Shared by the CLI and the TUI, which duplicated it."""
    table([
        {
            "title": e["title"],
            "target": money(e["target"]),
            "price": money(e["min_price"]),
            "stores": e["n_stores"],
            "hit": "¡SÍ!" if e["hit"] else "",
        }
        for e in entries
    ], [
        ("title", "Juego", True),
        ("target", "Objetivo", False),
        ("price", "Actual", False),
        ("stores", "Tiendas", False),
        ("hit", "Alcanzado", False),
    ], title=f"Lista de seguimiento ({len(entries)})",
       empty="La lista está vacía. Agrega con: tablero watch add \"<juego>\" --target N")


def update_report(totals: dict) -> None:
    parts = [
        f"\n{plural(totals['ingested'], 'producto')}",
        f"{totals['new']} nuevos",
        f"{totals['restock']} restock",
    ]
    if totals.get("failed"):
        parts.append(f"{plural(totals['failed'], 'tienda')} con error")
    print("Listo: " + " · ".join(parts))

    rejected = totals.get("rejected") or {}
    if rejected:
        detail = ", ".join(f"{n} {reason}" for reason, n in sorted(rejected.items()))
        print(f"Precios rechazados: {detail}")


def migration_report(report: dict, db_path, data_dir) -> None:
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
    if report.get("watchlist_found") or report.get("watchlist_lost"):
        print(f"  seguimiento    : {report['watchlist_restored']:>7} conservados, "
              f"{report['watchlist_lost']} perdidos (el juego ya no existe)")

    print(f"\nBase de datos: {db_path}")
    if not report["records_read"]:
        print(
            f"\nNo se encontraron datos en {data_dir}.\n"
            f"  Copia ahí los CSV (o products.json), o apunta TABLERO_DATA_DIR\n"
            f"  al directorio que los contiene, y vuelve a ejecutar 'tablero migrate'.\n"
            f"  Para poblarlo desde cero:  tablero update"
        )


def doctor(data_dir, db_path, version, counts, without_price, stale,
           cursor, outliers, sigma) -> None:
    print(f"Directorio    : {data_dir}")
    print(f"Base de datos : {db_path}")
    print(f"Esquema       : v{version}")
    for name, count in counts.items():
        print(f"  {name:<14} {count:>7}")

    print(f"\nProductos sin precio  : {without_price}")
    print(f"Productos obsoletos   : {stale}"
          f"{'  (ocultos; --include-stale para verlos)' if stale else ''}")
    print(f"Última revisión       : {cursor or '(sin fijar)'}")

    if outliers:
        # Reported, never auto-dropped: a real bargain and a typo look the same.
        table([
            {"store": o["store"], "title": o["title"],
             "price": money(o["price_eff"]), "mean": money(o["mean"]),
             "sigmas": f"{o['sigmas']}σ", "n": o["n"]}
            for o in outliers
        ], [
            ("title", "Producto", True), ("store", "Tienda", False),
            ("price", "Precio", False), ("mean", "Promedio", False),
            ("sigmas", "Desvío", False), ("n", "Tiendas", False),
        ], title=f"\nPrecios atípicos (> {sigma}σ del promedio del juego) — "
                 f"revisar, no se descartan solos")


def basket_plans(result: dict) -> None:
    """Side-by-side comparison of the buying strategies."""
    labels = {
        "split": "Cada juego en su tienda más barata",
        "single": "Todo en una sola tienda",
        "optimal": "Combinación óptima",
    }
    if not result.get("plans"):
        print("  (no hay ofertas disponibles para esos juegos)")
        for miss in result.get("unavailable", []):
            print(f"    sin stock: {miss['title']}")
        return

    print()
    for plan in result["plans"]:
        best = " ←  MEJOR" if plan is result["best"] else ""
        missing = f" · faltan {len(plan['missing'])}" if plan["missing"] else ""
        print(
            f"  {labels.get(plan['strategy'], plan['strategy']):<36} "
            f"{plan['n_stores']} tienda(s)  "
            f"{money(plan['subtotal']):>10} + envío {money(plan['shipping']):>8}"
            f" = {money(plan['total']):>10}{missing}{best}"
        )

    best = result["best"]
    print(f"\n  Desglose ({best['strategy']}):")
    for item in best["items"]:
        print(f"    {item['store']:<20} {money(item['price']):>10}  {_truncate(item['title'], 40)}")
    for miss in best["missing"] + result.get("unavailable", []):
        print(f"    {'(sin stock)':<20} {'-':>10}  {_truncate(miss['title'], 40)}")

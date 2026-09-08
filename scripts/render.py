"""
Terminal rendering.

Presentation only -- every function takes plain data (list[dict]) and writes to
stdout. Keeping this separate from the query layer is what lets the same
queries feed a phone export without dragging terminal formatting along.

Tables size themselves to the actual terminal. The previous renderer capped the
URL column at 100 characters with no width awareness, so a listing row ran past
160 columns and wrapped in any normal window.
"""
import shutil

try:
    from .classify import KIND_GAME
except ImportError:
    from classify import KIND_GAME

FLAG_MARK = {"new": "🆕", "restock": "🔄"}
KIND_MARK = {"expansion": "+exp", "accessory": "acc", "tcg": "tcg", "puzzle": "puz"}

MIN_COL = 6
GUTTER = 2


def term_width(default: int = 100) -> int:
    return shutil.get_terminal_size((default, 24)).columns


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


def _widths(rows: list[dict], columns: list[tuple], available: int) -> list[int]:
    """
    Column widths that fit `available`, shrinking the widest flexible column
    first so a long title never pushes the price off screen.
    """
    widths = [
        max(len(label), *(len(str(r.get(key, "") or "")) for r in rows)) if rows else len(label)
        for key, label, _ in columns
    ]
    flexible = [i for i, (_, _, flex) in enumerate(columns) if flex]

    while sum(widths) + GUTTER * (len(widths) - 1) > available and flexible:
        widest = max(flexible, key=lambda i: widths[i])
        if widths[widest] <= MIN_COL:
            flexible.remove(widest)
            continue
        widths[widest] -= 1
    return widths


def table(rows: list[dict], columns: list[tuple], title: str = "", limit: int = None) -> None:
    """
    Render rows as an aligned table.

    `columns` is a list of (key, label, flexible) -- flexible columns absorb the
    shrinking when the terminal is narrow.
    """
    if not rows:
        print("  (sin resultados)")
        return

    shown = rows[:limit] if limit else rows
    widths = _widths(shown, columns, term_width() - 2)

    if title:
        print(f"\n{title}")
    header = "  ".join(label.ljust(w) for (_, label, _), w in zip(columns, widths))
    print(header)
    print("  ".join("-" * w for w in widths))

    for row in shown:
        cells = (
            _truncate(row.get(key, ""), w).ljust(w)
            for (key, _, _), w in zip(columns, widths)
        )
        print("  ".join(cells).rstrip())

    if limit and len(rows) > limit:
        print(f"  … y {len(rows) - limit} más")


def search_results(hits: list[dict], query: str) -> None:
    """The numbered pick list. Compact by design -- it must survive on screen."""
    print(f"\nResultados para '{query}' ({len(hits)} encontrados):\n")
    for i, h in enumerate(hits, 1):
        marks = "".join([
            " " + KIND_MARK[h["kind"]] if h.get("kind") not in (KIND_GAME, None) else "",
            " " + FLAG_MARK["new"] if h.get("changed") else "",
        ])
        stock = "" if h.get("in_stock") else " · agotado"
        print(
            f"  {i:>3}. {_truncate(h['title'], 44):<44} "
            f"desde {money(h.get('min_price')):>10} · "
            f"{h.get('n_stores', 0):>2} tiendas{stock}{marks}"
        )


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
    ], title="\n🏆  Tiendas — más barata primero")
    print('\n  "Más caro" = % de juegos disputados en que la tienda supera '
          'la mediana entre tiendas.')


def trends(rows: list[dict], title: str, min_points: int = 2) -> None:
    if not rows:
        print(f"\n  {title}: sin historial suficiente "
              f"(se necesitan {min_points}+ observaciones por tienda).")
        print("  El historial se acumula con cada 'tablero update'.")
        return

    prepared = [
        {
            "store": t["store"],
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

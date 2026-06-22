"""
Derived sorting strategies and the store leaderboard.

`smart_sort` ranks a result set by a computed desirability metric rather than a
single column.  `render_store_leaderboard` gives a quick "where is it cheapest to
buy overall" view built from per-store statistics.
"""
import pandas as pd

try:
    from .stats import price_stats_per_store, effective_price
except ImportError:
    from stats import price_stats_per_store, effective_price

# Sort keys handled by smart_sort (distinct from utils.SORT_OPTIONS columns).
SMART_SORT_OPTIONS = ("value", "scarcity", "volatility")


def smart_sort(df: pd.DataFrame, by: str = "value") -> pd.DataFrame:
    """
    Sort a result set (descending desirability) by a derived metric:

      value       best deal you can actually buy — low price vs. the game's
                  median, with an in-stock bonus
      scarcity    available in the fewest stores (concentrated local demand)
      volatility  largest cross-store price spread (arbitrage opportunity)

    Returns a copy with helper columns removed.
    """
    if by not in SMART_SORT_OPTIONS:
        raise ValueError(f"Unknown smart-sort key '{by}'. Options: {SMART_SORT_OPTIONS}")

    out = df.copy()
    if out.empty:
        return out

    out["_price"] = effective_price(out)
    valid_price = out["_price"].notna() & (out["_price"] > 0)
    grp = out.groupby("norm")["_price"] if "norm" in out.columns else None

    if by == "scarcity":
        # Ranks whole games (by store count), so price validity doesn't matter.
        if "norm" in out.columns:
            out["_score"] = -out.groupby("norm")["store"].transform("nunique")
        else:
            out["_score"] = 0
    elif by == "volatility":
        if grp is not None:
            spread = (grp.transform("max") - grp.transform("min"))
            median = grp.transform("median").replace(0, pd.NA)
            out["_score"] = (spread / median).fillna(0)
        else:
            out["_score"] = 0
    else:  # value — only meaningful for rows with a real price; others sink last.
        median = (grp.transform("median") if grp is not None else out["_price"]).replace(0, pd.NA)
        rel = ((median - out["_price"]) / median).fillna(0)
        status = (out["stock_status"] if "stock_status" in out else pd.Series([""] * len(out), index=out.index))
        in_stock = ~status.fillna("").astype(str).str.lower().eq("agotado")
        out["_score"] = (rel + in_stock.astype(float) * 0.5).where(valid_price)

    out = out.sort_values("_score", ascending=False, na_position="last")
    return out.drop(columns=[c for c in out.columns if c.startswith("_")])


def render_store_leaderboard(df: pd.DataFrame, limit: int = None) -> None:
    """Print stores ranked cheapest-overall first (by competitiveness)."""
    stats = price_stats_per_store(df)
    if not stats:
        print("No hay datos para el leaderboard.")
        return

    rows = [
        {
            "Tienda": store,
            "Productos": s["n"],
            "Precio mediano": s["median"],
            "Descuento prom.": s["mean_discount_pct"],
            "% Agotado": s["oos_ratio"],
            "Competitividad": s["competitiveness"],
        }
        for store, s in stats.items()
    ]
    table = pd.DataFrame(rows).sort_values("Competitividad").reset_index(drop=True)
    if limit:
        table = table.head(limit)

    def _clp(v):
        return f"${v:,.0f}".replace(",", ".")

    table["Precio mediano"] = table["Precio mediano"].map(_clp)
    table["Descuento prom."] = (table["Descuento prom."] * 100).map(lambda v: f"{v:.0f}%")
    table["% Agotado"] = (table["% Agotado"] * 100).map(lambda v: f"{v:.0f}%")
    table["Competitividad"] = (table["Competitividad"] * 100).map(lambda v: f"{v:.0f}% más caro")

    print("\n🏆  Leaderboard de tiendas — más barata primero\n")
    print(table.to_string(index=False))
    print("\n(\"Competitividad\" = % de juegos compartidos en que la tienda es más cara que la mediana)")

"""
Export a comparison result set to CSV, JSON, or a static styled HTML table.

CSV   → importable to Excel / sheets
JSON  → for external APIs
HTML  → standalone table, embeddable in a web page
"""
import time
from pathlib import Path

try:
    from .paths import DATA_DIR
except ImportError:
    from paths import DATA_DIR

EXPORT_DIR = DATA_DIR / "exports"

VALID_FORMATS = ("csv", "json", "html")

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>tablero-cl — comparación</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; color: #1a1a1a; }}
  h1 {{ font-size: 1.25rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
  th, td {{ padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid #e5e5e5; }}
  th {{ background: #f5f5f5; position: sticky; top: 0; }}
  tr:hover {{ background: #fafafa; }}
  caption {{ caption-side: bottom; padding-top: 0.75rem; color: #888; font-size: 0.8rem; }}
</style>
</head>
<body>
<h1>🎲 tablero-cl — comparación de precios</h1>
{table}
</body>
</html>
"""


def export_comparison(df, fmt: str = "csv", path=None) -> str:
    """
    Write `df` in the given format. Returns the path written.

    If `path` is None, writes to data/exports/tablero_export_<ts>.<fmt>.
    """
    fmt = fmt.lower()
    if fmt not in VALID_FORMATS:
        raise ValueError(f"Unknown export format '{fmt}'. Valid: {', '.join(VALID_FORMATS)}")

    if path is None:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = EXPORT_DIR / f"tablero_export_{int(time.time())}.{fmt}"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "csv":
        df.to_csv(path, index=False)
    elif fmt == "json":
        df.to_json(path, orient="records", force_ascii=False, indent=2)
    else:  # html
        table_html = df.to_html(index=False, border=0, na_rep="-", escape=True)
        path.write_text(_HTML_TEMPLATE.format(table=table_html), encoding="utf-8")

    return str(path)

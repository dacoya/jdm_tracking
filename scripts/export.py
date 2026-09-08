"""
Export a comparison result set to CSV, JSON, or a static styled HTML table.

CSV   → importable to Excel / sheets
JSON  → for external APIs
HTML  → standalone table, embeddable in a web page
"""
import csv
import json
import time
from html import escape
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


def export_comparison(rows, fmt: str = "csv", path=None) -> str:
    """
    Write `rows` in the given format. Returns the path written.

    If `path` is None, writes to data/exports/tablero_export_<ts>.<fmt>.

    Takes the `list[dict]` the query layer already returns. It used to require
    a DataFrame, so both callers converted just to hand it straight back --
    pulling pandas (and ~170 ms of import) into a job the standard library
    does natively.
    """
    fmt = fmt.lower()
    if fmt not in VALID_FORMATS:
        raise ValueError(f"Unknown export format '{fmt}'. Valid: {', '.join(VALID_FORMATS)}")

    if path is None:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = EXPORT_DIR / f"tablero_export_{int(time.time())}.{fmt}"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = list(rows or [])
    # Union of keys, first-seen order: rows from different queries do not all
    # carry the same columns.
    columns = list(dict.fromkeys(k for r in rows for k in r))

    if fmt == "csv":
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    elif fmt == "json":
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
    else:  # html
        path.write_text(_HTML_TEMPLATE.format(table=_html_table(rows, columns)),
                        encoding="utf-8")

    return str(path)


def _html_table(rows: list, columns: list) -> str:
    """Minimal escaped HTML table."""
    head = "".join(f"<th>{escape(str(c))}</th>" for c in columns)
    body = "".join(
        "<tr>" + "".join(
            f"<td>{escape('-' if r.get(c) is None else str(r.get(c)))}</td>"
            for c in columns
        ) + "</tr>"
        for r in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

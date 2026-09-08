"""
SQLite connection and schema management.

The database is the canonical store: prices are numeric, the cross-store match
key is persisted, and product identity is stable across scrapes. That makes the
file directly readable by an external consumer (the Android app reads this same
file via Room) with no Python-side translation.

Everything here is I/O plumbing only -- no business logic, no printing.
"""
import sqlite3
from pathlib import Path

try:
    from .paths import DATA_DIR, PKG_DIR
except ImportError:
    from paths import DATA_DIR, PKG_DIR

DB_PATH = DATA_DIR / "tablero.db"
SCHEMA_PATH = PKG_DIR / "schema.sql"

# Bump when schema.sql changes in a way that needs a migration step.
SCHEMA_VERSION = 3


class SchemaVersionError(RuntimeError):
    """Raised when a database was written by an incompatible schema version."""


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets a reader (an export job, a sync agent) work while a scrape writes.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")


def connect(path=None, read_only: bool = False) -> sqlite3.Connection:
    """
    Open a connection with dict-style rows and the standard PRAGMAs applied.

    `read_only` opens via a file: URI so a consumer cannot accidentally write;
    it requires the file to already exist.
    """
    target = Path(path) if path is not None else DB_PATH

    if read_only:
        if not target.exists():
            raise FileNotFoundError(f"No database at {target}")
        conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(target)

    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def init_db(conn: sqlite3.Connection) -> None:
    """Create the schema if absent and stamp the version. Safe to call repeatedly."""
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema file missing: {SCHEMA_PATH}")

    existing = schema_version(conn)
    if existing and existing != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"Database at schema v{existing}, code expects v{SCHEMA_VERSION}. "
            f"Re-run the migration against a fresh file."
        )

    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """
    Resync the FTS index from the product table.

    product_fts is an external-content table, so it does not track writes on its
    own. Rebuilding after a bulk load is cheaper than maintaining triggers
    through a full catalog rewrite.
    """
    conn.execute("INSERT INTO product_fts(product_fts) VALUES('rebuild')")
    conn.commit()


def table_counts(conn: sqlite3.Connection) -> dict:
    """Row count per table -- used by the migration and by `tablero doctor`."""
    names = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'product_fts%' "
            "ORDER BY name"
        )
    ]
    # A table name cannot be a bound parameter, so it is quoted instead. The
    # names come from sqlite_master rather than any caller, but quoting keeps
    # the identifier inert regardless of what a file happens to contain.
    return {
        n: conn.execute(f'SELECT COUNT(*) FROM "{n.replace(chr(34), chr(34) * 2)}"').fetchone()[0]
        for n in names
    }

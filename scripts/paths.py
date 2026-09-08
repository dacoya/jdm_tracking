"""
Filesystem paths for tablero-cl, resolved independently of the current
working directory.

Historically the code used ``'../data/...'`` strings that only resolved
correctly when run from inside ``scripts/``. Resolving from *this module's*
location instead lets the ``tablero`` command work from any directory.

Where the data lives depends on how the package was installed, in this order:

  1. ``TABLERO_DATA_DIR`` -- an explicit override, which is what lets a sync
     job, a scratch copy, or a test fixture point somewhere else.
  2. ``<repo>/data`` when running from a source checkout (editable install or
     ``python scripts/cli.py``), so development keeps using the tracked CSVs.
  3. A per-user data directory otherwise. A normal ``pip install`` puts the
     package under ``site-packages``, and writing a 15 MB database there would
     be wrong: it is not the user's data, and a reinstall would delete it.

Pure ``pathlib`` with no cross-module imports, so it is safe to import in both
package mode (``tablero.paths``) and flat mode (``paths``).
"""
import os
import sys
from pathlib import Path

APP_NAME = "tablero-cl"

# Directory containing the package source (scripts/, or site-packages/tablero/).
PKG_DIR = Path(__file__).resolve().parent

# One level up from the package source.
REPO_ROOT = PKG_DIR.parent


def _user_data_dir() -> Path:
    """Per-user data directory for the current platform."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


def _is_source_checkout(root: Path) -> bool:
    """
    True when `root` looks like the project's own working tree.

    Keyed on pyproject.toml rather than on data/ existing, so a fresh clone
    with no data yet still resolves to the checkout instead of silently
    scattering files into a user directory.
    """
    return (root / "pyproject.toml").is_file()


def default_data_dir() -> Path:
    env = os.environ.get("TABLERO_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if _is_source_checkout(REPO_ROOT):
        return REPO_ROOT / "data"
    return _user_data_dir()


DATA_DIR = default_data_dir()
JSON_PATH = DATA_DIR / "products.json"


def resolve_output(output) -> Path:
    """
    Resolve a ``site['output']`` value to an absolute path.

    Site outputs are declared relative to ``scripts/`` (e.g. ``'../data/foo.csv'``),
    which only lines up with DATA_DIR in a source checkout. Everywhere else the
    filename is taken and placed in DATA_DIR, so an installed copy writes its
    CSVs alongside the database rather than into site-packages.
    """
    p = Path(output)
    if p.is_absolute():
        return p
    if _is_source_checkout(REPO_ROOT):
        return (PKG_DIR / p).resolve()
    return DATA_DIR / p.name

"""
Filesystem paths for tablero-cl, resolved independently of the current
working directory.

The data files live under ``<repo-root>/data/``.  Historically the code used
``'../data/...'`` strings that only resolved correctly when run from inside
``scripts/``.  Resolving paths from *this module's* location instead lets the
``tablero`` command (and direct ``python main.py`` runs) work from any directory.

Pure ``pathlib`` with no cross-module imports, so it is safe to import in both
package mode (``tablero.paths``) and flat mode (``paths``).
"""
from pathlib import Path

# Directory containing the package source (scripts/).
PKG_DIR = Path(__file__).resolve().parent

# Repo root — one level up from the package source.
REPO_ROOT = PKG_DIR.parent

# Data directory and the merged product database.
DATA_DIR = REPO_ROOT / "data"
JSON_PATH = DATA_DIR / "products.json"


def resolve_output(output) -> Path:
    """
    Resolve a ``site['output']`` value to an absolute path.

    Site outputs are declared relative to ``scripts/`` (e.g. ``'../data/foo.csv'``).
    Resolving them against :data:`PKG_DIR` makes CSV reads and writes independent
    of the current working directory.  Absolute paths are returned unchanged.
    """
    p = Path(output)
    return p if p.is_absolute() else (PKG_DIR / p).resolve()

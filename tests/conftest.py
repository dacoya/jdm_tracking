import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def sample_products():
    """A small catalog exercising sales, out-of-stock, flags and noisy titles."""
    return {
        "tiendaA": [
            {"title": "Catan - Juego de Mesa", "original_price": "$49.990",
             "current_price": "$39.990", "stock_status": None,
             "url": "https://tiendaa.cl/producto/catan/"},
            {"title": "Wingspan", "original_price": "$62.000",
             "current_price": None, "stock_status": "Agotado",
             "url": "https://tiendaa.cl/producto/wingspan/"},
            {"title": "Fundas Standard 63x88 para Catan", "original_price": "$3.990",
             "current_price": None, "stock_status": None,
             "url": "https://tiendaa.cl/producto/fundas-catan/"},
        ],
        "tiendaB": [
            {"title": "Catan", "original_price": "$45.990",
             "current_price": None, "stock_status": None,
             "url": "https://tiendab.cl/p/catan", "flag": "new"},
            {"title": "Catan Expansión Navegantes", "original_price": "$34.990",
             "current_price": None, "stock_status": None,
             "url": "https://tiendab.cl/p/catan-navegantes"},
            {"title": "Wingspan", "original_price": "$59.990",
             "current_price": None, "stock_status": None,
             "url": "https://tiendab.cl/p/wingspan"},
        ],
    }


@pytest.fixture
def sample_history():
    return {
        "catan|tiendaB": [
            {"t": 1_700_000_000, "price": 52990.0},
            {"t": 1_700_090_000, "price": 45990.0},
        ],
        "titulo fantasma|tiendaA": [{"t": 1_700_000_000, "price": 1000.0}],
    }


@pytest.fixture
def db_conn(tmp_path, sample_products, sample_history, monkeypatch):
    """A migrated database built from the sample fixtures."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "products.json").write_text(json.dumps(sample_products), encoding="utf-8")
    (data_dir / "history.json").write_text(json.dumps(sample_history), encoding="utf-8")
    (data_dir / "metadata.json").write_text(
        json.dumps({"sites": {"tiendaA": {"last_scrape": 1_700_100_000,
                                          "product_count": 3, "success": True}},
                    "price_stats": {}}),
        encoding="utf-8",
    )

    import db as db_mod
    import migrate

    db_path = tmp_path / "tablero.db"
    migrate.migrate(db_path=db_path, data_dir=data_dir)
    conn = db_mod.connect(db_path)
    yield conn
    conn.close()

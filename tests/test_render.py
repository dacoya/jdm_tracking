"""Terminal rendering: layout, paging, and the empty case."""
import os
import sys

import pytest

import render


COLUMNS = [
    ("title", "Producto", True),
    ("store", "Tienda", False),
    ("price", "Precio", False),
]
ROWS = [
    {"title": "Un juego con un nombre bastante largo", "store": "updown", "price": "$1.000"},
    {"title": "Otro", "store": "flexo", "price": "$2.000"},
]


# ---------------------------------------------------------------------------
# Empty results
# ---------------------------------------------------------------------------

def test_empty_table_still_prints_its_heading(capsys):
    """
    A bare "(sin resultados)" gives no clue which query came up empty.

    The heading used to be printed after the early return, so filtering
    everything out produced a single orphaned line.
    """
    render.table([], COLUMNS, title="Ofertas (0)")
    out = capsys.readouterr().out
    assert "Ofertas (0)" in out
    assert "sin resultados" in out


def test_empty_message_is_customisable(capsys):
    render.table([], COLUMNS, title="Lista", empty="La lista está vacía.")
    assert "La lista está vacía." in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Width handling
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("width", [40, 60, 80, 120])
def test_header_stays_aligned_with_data(capsys, monkeypatch, width):
    """
    Labels are truncated like any other cell.

    They were only ljust-ed, so on a narrow terminal a long label outgrew its
    column and slid the header out of step with the rows beneath it.
    """
    monkeypatch.setattr(render, "term_width", lambda default=100: width)
    render.table(ROWS, COLUMNS, title="T")
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip() and l != "T"]

    separator = next(l for l in lines if set(l) <= {"-", " "})
    body = [l for l in lines if l is not separator and l != "T"]
    assert len({len(l.rstrip()) for l in body}) <= len(body)  # no runaway line
    for line in lines:
        assert len(line) <= width


def test_long_cells_are_truncated_with_an_ellipsis(capsys, monkeypatch):
    monkeypatch.setattr(render, "term_width", lambda default=100: 40)
    render.table(ROWS, COLUMNS)
    assert "…" in capsys.readouterr().out


def test_flexible_columns_stay_compact(monkeypatch):
    """
    One long title used to stretch the whole table, leaving a ragged gap after
    every short one. Flexible columns now start capped.
    """
    rows = [{"title": "x" * 200, "store": "s", "price": "$1"}]
    widths = render._widths(rows, COLUMNS, available=300)
    assert widths[0] == render.MAX_FLEX_COL


def test_column_grows_when_truncation_would_merge_distinct_rows():
    """
    Four different L5R packs all begin "La Leyenda de los Cinco Anillos LCG:".

    Capping the title column rendered them as one identical string, so the
    column widens just enough to keep them apart.
    """
    prefix = "La Leyenda de los Cinco Anillos LCG: "
    rows = [
        {"title": prefix + suffix, "store": "shivano", "price": "$12.000"}
        for suffix in ("Las Lágrimas", "Meditaciones", "Por el Honor", "El Destino")
    ]
    widths = render._widths(rows, COLUMNS, available=200)
    shown = {render._truncate(r["title"], widths[0]) for r in rows}
    assert len(shown) == len(rows)
    assert widths[0] > render.MAX_FLEX_COL


def test_a_narrow_terminal_still_wins_over_disambiguation():
    """Fitting the screen matters more; ambiguity is the lesser evil."""
    prefix = "identico " * 8
    rows = [{"title": prefix + s, "store": "s", "price": "$1"} for s in ("a", "b")]
    widths = render._widths(rows, COLUMNS, available=40)
    assert sum(widths) + render.GUTTER * (len(widths) - 1) <= 40


def test_hit_title_width_tracks_the_longest_title_shown():
    """The picker padded to a fixed 44, leaving a gap after short names."""
    assert render.hit_title_width([{"title": "Clank"}, {"title": "Clank Legacy"}]) == 12
    assert render.hit_title_width([{"title": "x" * 90}]) == render.MAX_FLEX_COL
    assert render.hit_title_width([]) == render.MIN_COL


# ---------------------------------------------------------------------------
# Paging
# ---------------------------------------------------------------------------

def test_no_paging_when_not_a_tty():
    """A pipe or redirect must get raw text, or `| head` and --export break."""
    assert render._pager_command() is None


def test_pager_honours_PAGER(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setenv("PAGER", "more")
    assert render._pager_command() == ["more"]


def test_empty_PAGER_opts_out(monkeypatch):
    """PAGER="" is how a user says 'never page me'."""
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setenv("PAGER", "")
    assert render._pager_command() is None


def test_short_output_is_not_paged(capsys, monkeypatch):
    monkeypatch.setattr(render, "_pager_command", lambda: ["false"])
    monkeypatch.setattr(render, "term_size", lambda: os.terminal_size((80, 24)))
    render.page("una\ndos\ntres")
    assert "tres" in capsys.readouterr().out


def test_long_output_falls_back_when_the_pager_is_missing(capsys, monkeypatch):
    monkeypatch.setattr(render, "_pager_command",
                        lambda: ["definitely-not-a-real-pager-binary"])
    monkeypatch.setattr(render, "term_size", lambda: os.terminal_size((80, 5)))
    render.page("\n".join(f"linea {i}" for i in range(50)))
    assert "linea 49" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n, expected", [
    (0, "0 tiendas"),
    (1, "1 tienda"),
    (2, "2 tiendas"),
])
def test_plural(n, expected):
    """The search list printed '1 tiendas'."""
    assert render.plural(n, "tienda") == expected


def test_money_formats_chilean_pesos():
    assert render.money(69990) == "$69.990"
    assert render.money(None) == "-"
    assert render.money("no es un número") == "-"


# ---------------------------------------------------------------------------
# Search badges
# ---------------------------------------------------------------------------

def test_hit_label_carries_everything_the_numbered_list_shows():
    """
    The picker label and the numbered row are the same string.

    The TUI printed the full result list and then showed the identical set
    again as selectable rows -- every result twice on one screen. Sharing this
    formatter is what lets the picker be the only listing.
    """
    hit = {"title": "Clank", "min_price": 47990, "n_stores": 14,
           "in_stock": True, "kind": "game"}
    label = render.hit_label(hit)
    assert "Clank" in label
    assert "$47.990" in label
    assert "14 tiendas" in label
    assert "agotado" not in label


def test_hit_label_marks_out_of_stock_and_kind():
    label = render.hit_label(
        {"title": "X", "min_price": 1, "n_stores": 1,
         "in_stock": False, "kind": "expansion"})
    assert "agotado" in label
    assert "1 tienda" in label and "1 tiendas" not in label
    assert render.KIND_MARK["expansion"] in label


def test_back_sentinel_is_not_mistaken_for_a_value():
    """
    questionary.Choice falls back to the TITLE when value is None.

    So Choice("No", value=None) handed back the string "No", which reached
    export_comparison as a format name and crashed the TUI with
    ValueError: Unknown export format 'no'. A distinct object cannot collide
    with a real selection.
    """
    import questionary

    import export
    import tui

    assert questionary.Choice("No", value=None).value == "No"      # the trap
    assert questionary.Choice("No", value=tui.BACK).value is tui.BACK
    assert tui.BACK not in export.VALID_FORMATS


def test_unknown_kind_does_not_crash_the_view():
    """KIND_MARK was indexed directly, so a new kind raised KeyError."""
    assert render._marks({"kind": "una-clase-nueva"})


def test_restock_is_not_labelled_as_new():
    """`changed` was true for restocks too, so they showed the 🆕 badge."""
    assert render.FLAG_MARK["restock"] in render._marks({"is_restock": True})
    assert render.FLAG_MARK["new"] in render._marks({"is_new": True})
    assert render._marks({"kind": "game"}) == ""

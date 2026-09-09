"""The TUI's price filter: a picker for the bound, then the amount."""
import pytest

import tui


def _answers(*values):
    """Feed `values` to successive _ask calls, in order."""
    it = iter(values)
    return lambda prompt: next(it)


@pytest.mark.parametrize("raw, expected", [
    ("30000", 30000.0),
    ("30.000", 30000.0),        # Chilean thousands separator
    ("30000,5", 30000.5),       # decimal comma
    ("", None),
    ("   ", None),
    ("basura", None),           # unparseable is ignored, not fatal
])
def test_parse_price(raw, expected):
    assert tui._parse_price(raw) == expected


def test_no_filter(monkeypatch):
    monkeypatch.setattr(tui, "_ask", _answers(tui.BACK))
    assert tui._ask_price_range() == (None, None)


def test_max_only(monkeypatch):
    monkeypatch.setattr(tui, "_ask", _answers("max", "30000"))
    assert tui._ask_price_range() == (None, 30000.0)


def test_min_only(monkeypatch):
    monkeypatch.setattr(tui, "_ask", _answers("min", "10000"))
    assert tui._ask_price_range() == (10000.0, None)


def test_range(monkeypatch):
    monkeypatch.setattr(tui, "_ask", _answers("range", "10000", "30000"))
    assert tui._ask_price_range() == (10000.0, 30000.0)


def test_range_with_one_side_left_blank(monkeypatch):
    """An empty amount means that end stays unbounded."""
    monkeypatch.setattr(tui, "_ask", _answers("range", "", "30000"))
    assert tui._ask_price_range() == (None, 30000.0)


def test_cancelled_picker(monkeypatch):
    """Ctrl-C on the picker must not read as "no filter chosen deliberately"."""
    monkeypatch.setattr(tui, "_ask", _answers(None))
    assert tui._ask_price_range() == (None, None)


def test_browse_title_states_the_bounds():
    assert tui._browse_title("Ofertas", 7, "discount", None, None) == (
        "Ofertas (7) · orden: discount")
    assert tui._browse_title("Ofertas", 7, "price", 10000.0, 30000.0) == (
        "Ofertas (7) · orden: price · desde $10.000 · hasta $30.000")

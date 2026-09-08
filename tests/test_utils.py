"""Price parsing and title normalization -- the shared primitives everything else builds on."""
import pytest

from utils import calc_discount_pct, clean_title, normalize, parse_price


@pytest.mark.parametrize("raw, expected", [
    ("$69.990", 69990.0),        # dot = thousands (Chilean default)
    ("$69.990,50", 69990.5),     # dot thousands + comma decimal
    ("$49,000", 49000.0),        # comma = thousands when 3 digits follow
    ("69,990", 69990.0),
    ("1,234.56", 1234.56),       # comma thousands + dot decimal
    ("9,5", 9.5),                # comma decimal when NOT a 3-digit group
    ("9.5", 9.5),
    ("", None),
    ("sin precio", None),
    (None, None),
])
def test_parse_price(raw, expected):
    assert parse_price(raw) == expected


def test_parse_price_decimal_comma_not_thousands():
    """Regression: deals_mode shadowed this with a version that returned 95.0."""
    assert parse_price("9,5") == 9.5


@pytest.mark.parametrize("raw, expected", [
    ("Catan - Juego de Mesa", "Catan"),
    ("Carcassonne | Board Game", "Carcassonne"),
    ("Arkham Horror: El Juego de Cartas", "Arkham Horror: El Juego de Cartas"),
])
def test_clean_title(raw, expected):
    assert clean_title(raw) == expected


def test_clean_title_preserves_subtitle():
    """A definite article marks a real subtitle, not a category tag."""
    assert "Juego de Cartas" in clean_title("Arkham Horror: El Juego de Cartas")


@pytest.mark.parametrize("raw, expected", [
    ("Clank!: En las Catacumbas (En Español)", "clank en las catacumbas"),
    ("Terraforming Mars Edición Kickstarter", "terraforming mars kickstarter"),
    ("ÁÉÍÓÚ ñ", "aeiou n"),
])
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_normalize_non_string():
    assert normalize(None) == ""


def test_calc_discount_pct():
    assert calc_discount_pct("$50.000", "$40.000") == pytest.approx(20.0)
    assert calc_discount_pct("$50.000", None) is None

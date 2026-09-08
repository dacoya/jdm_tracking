"""Price parsing and title normalization -- the shared primitives everything else builds on."""
import pytest

from utils import clean_title, normalize, parse_price


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


@pytest.mark.parametrize("board, variant", [
    ("Catan", "Catan: Juego de Cartas"),
    ("Terraforming Mars", "Terraforming Mars Juego de Dados"),
    ("Camel Up Edición 2.0", "Camel Up 2.0 Juego de Cartas"),
    ("Sushi Go", "Sushi Go - Party"),
    ("Time's Up!", "Time's Up! - Party"),
])
def test_product_variants_do_not_collapse_into_the_base_game(board, variant):
    """
    A card/dice/party edition is a different product, not a category tag.

    Stripping those phrases merged them with the base game, so the variant's
    price was advertised as the base game's -- `search catan` showed
    "desde $10.990", the price of Catan: Juego de Cartas.
    """
    assert normalize(clean_title(board)) != normalize(clean_title(variant))


@pytest.mark.parametrize("plain, qualified", [
    ("Clank", "Clank Base"),
    ("Clank", "Clank (juego base)"),
    ("Catan", "Catan Base"),
    ("Clank! Tesoros Sumergidos", "Clank! Expansión: Tesoros Sumergidos - Español"),
    ("Clank! La maldición de la momia", "Clank! Expansión: La Maldición de la Momia"),
])
def test_qualifiers_that_do_not_change_the_product_are_merged(plain, qualified):
    """
    "Base" and a leading "Expansión:" name the same product.

    Searching Clank returned "Clank", "Clank Base" and "Clank (juego base)" as
    three separate results with different prices and store counts.
    """
    assert normalize(plain) == normalize(qualified)


@pytest.mark.parametrize("a, b", [
    ("Catan", "Catan Expansión"),          # no name follows: not the base game
    ("Catan", "Catan Expansión Navegantes"),
    ("Base Camp", "Camp"),                 # "Base" as part of a real name
    ("Baseball Highlights 2045", "ball Highlights 2045"),
])
def test_qualifier_stripping_does_not_overreach(a, b):
    assert normalize(a) != normalize(b)


@pytest.mark.parametrize("raw", [
    "Catan - Juego de Mesa",
    "Carcassonne | Board Game",
    "Wingspan - Juego de Mesa Familiar",
    "Azul - Abstracto, estrategia",
])
def test_generic_category_noise_is_still_stripped(raw):
    """Tautological labels and pure attributes carry no identity; drop them."""
    cleaned = clean_title(raw)
    assert "Juego de Mesa" not in cleaned
    assert "Board Game" not in cleaned
    assert cleaned == cleaned.strip(" -|,:;")


@pytest.mark.parametrize("raw, expected", [
    ("Clank!: En las Catacumbas (En Español)", "clank en las catacumbas"),
    ("Terraforming Mars Edición Kickstarter", "terraforming mars kickstarter"),
    ("ÁÉÍÓÚ ñ", "aeiou n"),
])
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_normalize_non_string():
    assert normalize(None) == ""

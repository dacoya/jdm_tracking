"""Product kind classification.

The costly error is labelling a real game as an accessory, since that hides it
from search entirely. These cases pin the ones that actually broke during
development.
"""
import pytest

from classify import (KIND_ACCESSORY, KIND_EXPANSION, KIND_GAME, KIND_PUZZLE,
                      KIND_TCG, classify, kind_rank)


@pytest.mark.parametrize("title", [
    "Catan",
    "Wingspan",
    "Troyes Dice",                        # dice in the name, still a game
    "Flapjacks & Sasquatches Dice Game",
    "7 Wonder Dice",
    "Dice Throne S1",
    "Sagrada",
    "Monopoly Pokémon",                   # brand alone is not TCG evidence
    "Dobble Blister",                     # packaging word, not a TCG product
    "Fábulas de Peluche",
])
def test_games_stay_games(title):
    assert classify(title) == KIND_GAME


@pytest.mark.parametrize("title", [
    "Fundas Prime Mini European 46 x 71 mm",
    "GG: Moon D6 Dice Set 16 mm",
    "Boardgame Sleeves - European Sized",
    "Playmat Scythe",
    "Deck Box Ultra Pro",
])
def test_accessories(title):
    assert classify(title) == KIND_ACCESSORY


@pytest.mark.parametrize("title", [
    "Catan Expansión Navegantes",
    "Smart 10 Ampliación",
    "Not Alone - Sanctuary (EXPANSIÓN)",
])
def test_expansions(title):
    assert classify(title) == KIND_EXPANSION


@pytest.mark.parametrize("title", [
    "Magic The Gathering Play Booster",
    "Pokemon Booster Display",
])
def test_tcg(title):
    assert classify(title) == KIND_TCG


@pytest.mark.parametrize("title", ["Puzzle 1000 piezas", "Booknook Tonecheer 3D Puzzle"])
def test_puzzles(title):
    assert classify(title) == KIND_PUZZLE


def test_empty_defaults_to_game():
    assert classify("") == KIND_GAME
    assert classify(None) == KIND_GAME


def test_kind_rank_orders_games_first():
    assert kind_rank(KIND_GAME) < kind_rank(KIND_EXPANSION) < kind_rank(KIND_ACCESSORY)
    assert kind_rank("nonsense") == 5

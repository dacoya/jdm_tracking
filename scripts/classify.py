"""
Product kind classification.

Store catalogs mix board games with sleeves, dice, TCG boosters and puzzles.
They all match a game's name -- "Fundas ... para Catan" scores highly against
"catan" -- so without a kind the accessories crowd out the game itself.

Classification is title-based and deliberately conservative: anything not
recognisably something else is a base game, because a wrong non-game label
hides a real product from search, which is the costlier error.

Kinds, ordered by how they should rank in a game search:
    game       -- a standalone/base board game
    expansion  -- needs a base game
    tcg        -- trading-card product (boosters, decks, displays)
    puzzle     -- jigsaw / 3D puzzle / booknook
    accessory  -- sleeves, mats, storage, dice sets, merch
"""
import re

KIND_GAME = "game"
KIND_EXPANSION = "expansion"
KIND_TCG = "tcg"
KIND_PUZZLE = "puzzle"
KIND_ACCESSORY = "accessory"

KIND_ORDER = (KIND_GAME, KIND_EXPANSION, KIND_TCG, KIND_PUZZLE, KIND_ACCESSORY)

# Dice and cards appear in real game names ("Troyes Dice", "Dice Throne"), so a
# bare \bdice\b is not evidence of an accessory. These phrases are.
_ACCESSORY = re.compile(
    r"\b("
    r"fundas?|sleeves?|protectores?\s+de\s+cartas?"
    r"|dice\s+(?:set|bag|tower|tray|cup)|set\s+de\s+dados|bolsa\s+de\s+dados"
    r"|torre\s+de\s+dados|dados\s+poli[eé]dricos?|d\d+\s+dice|dados?\s+d\d+"
    r"|playmat|play\s?mat|tapete|alfombrilla|mousepad|mouse\s?pad"
    r"|deck\s?box|caja\s+de\s+mazo|porta\s?mazos?|organizador(?:es)?|insertos?"
    r"|separadores?|dividers?|binder|carpeta\s+de\s+cartas"
    r"|toploader|top\s?loader"
    r"|pinturas?|pinceles?|aer[oó]grafo|imprimaci[oó]n"
    r"|p[oó]ster|lienzo|llavero|polera|pol[eé]r[oó]n|taza\b|mochila"
    r"|funko|figura\s+coleccionable"
    r")\b",
    re.IGNORECASE,
)

# Trading-card product. Matched on product FORM, not brand: "Monopoly Pokémon"
# is a board game and "Dobble Blister" is packaging, so a brand name or a
# packaging word alone is not evidence. Checked before expansion because TCG
# sets are often labelled "expansión" while being a different purchase entirely.
_TCG = re.compile(
    r"\b("
    r"booster|display\b|starter\s+deck|mazo\s+(?:inicial|de\s+torneo)"
    r"|collector\s+booster|set\s+booster|draft\s+booster|play\s+booster"
    r"|caja\s+de\s+sobres|sobres?\s+(?:de|sellad)|carta\s+suelta"
    r"|deck\s+(?:de\s+)?(?:tem[aá]tico|construido)"
    r"|(?:magic\s+the\s+gathering|\bmtg\b|lorcana|yu-?gi-?oh|pok[eé]mon|digimon"
    r"|flesh\s+and\s+blood|one\s+piece\s+card|vanguard)"
    r"\s+(?:booster|sobre|display|deck|mazo|cartas?|tcg|single)"
    r")\b",
    re.IGNORECASE,
)

_PUZZLE = re.compile(
    r"\b(puzzles?|rompecabezas|booknook|book\s?nook|3d\s+puzzle)\b",
    re.IGNORECASE,
)

_EXPANSION = re.compile(
    r"\b("
    r"expansi[oó]n(?:es)?|expansions?|\bexp\.?\b"
    r"|ampliaci[oó]n|mini\s?expansi[oó]n"
    r"|paquete\s+de\s+(?:expansi[oó]n|batalla)"
    r"|escenarios?\s+adicionales?"
    r")\b",
    re.IGNORECASE,
)

# Real games whose names contain a marker word. Matching here forces `game`.
_GAME_NAME_GUARD = re.compile(
    r"\b("
    r"dice\s+game|juego\s+de\s+dados"
    r"|dice\s+throne|dice\s+forge|dice\s+realms|troyes\s+dice|sagrada"
    r"|king\s+of\s+tokyo|rey\s+de\s+los\s+dados|roll\s+player"
    r"|qwixx|quixx|yahtzee|generala|marbles?\b"
    r"|sleeping\s+gods|puzzle\s+strike"
    r")\b",
    re.IGNORECASE,
)

_RULES = (
    (_ACCESSORY, KIND_ACCESSORY),
    (_TCG, KIND_TCG),
    (_PUZZLE, KIND_PUZZLE),
    (_EXPANSION, KIND_EXPANSION),
)


def classify(title: str) -> str:
    """Return the kind for a product title."""
    if not isinstance(title, str) or not title.strip():
        return KIND_GAME
    if _GAME_NAME_GUARD.search(title):
        return KIND_GAME
    for pattern, kind in _RULES:
        if pattern.search(title):
            return kind
    return KIND_GAME


def kind_rank(kind: str) -> int:
    """Sort key: lower ranks first. Unknown kinds sort last."""
    try:
        return KIND_ORDER.index(kind)
    except ValueError:
        return len(KIND_ORDER)

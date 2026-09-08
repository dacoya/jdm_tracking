"""
Title normalization and price parsing.

These turn what a store wrote into the two things the rest of the tool needs:
a display title, and a `norm` key that decides which listings are the same
product. Nothing here touches a database or prints.

Discount maths, table rendering and pagination used to live here too; the
first moved into SQL and the others into render.py.
"""

import re
import unicodedata


# ---------------------------------------------------------------------------
# Title normalization
# ---------------------------------------------------------------------------

# Language tags appended by stores: "en español", "(en inglés)", "castellano", etc.
_LANG_TAG = re.compile(
    r'[\(\[]?\b(en\s+)?(espa[nñ]ol|ingl[eé]s|ingles|english|castellano)\b[\)\]]?',
    re.IGNORECASE,
)

# Edition markers: "edición deluxe", "2da edición", "kickstarter edition", etc.
_EDITION_TAG = re.compile(
    r'\b\d+[aª]?\s*(edici[oó]n|edition)\b|\b(edici[oó]n|edition)\b',
    re.IGNORECASE,
)


# "Base game" qualifiers. These name the plain game, so "Clank", "Clank Base"
# and "Clank (juego base)" are one product listed three ways -- searching Clank
# returned all three as separate results with different prices.
_BASE_QUALIFIER = re.compile(
    r'[\(\[]?\b(juego\s+)?base\b[\)\]]?\s*$',
    re.IGNORECASE,
)

# A leading "expansión:" qualifier. What follows is the expansion's actual name,
# so "Clank! Expansión: Tesoros Sumergidos" and "Clank! Tesoros Sumergidos" are
# the same product. Requires a following word, or "Catan Expansión" alone would
# collapse into "Catan".
_EXPANSION_QUALIFIER = re.compile(
    r'\b(mini\s?)?expansi[oó]n(es)?\b(?=[\s:,\-]+\w)',
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    """
    Return a cleaned, lowercase, accent-free, punctuation-free version of a
    title for fuzzy matching. Original title is NOT modified.

    Pipeline:
      1. Lowercase
      2. Strip language tags   ("en español", "en inglés", etc.)
      3. Strip edition markers ("edición deluxe", "2da edición", etc.)
      4. Strip qualifiers that do not change which product it is
         ("Clank Base" -> "clank"; "Clank Expansión: X" -> "clank x")
      5. Remove accents        (é→e, ñ→n, ü→u, etc.)
      6. Replace punctuation   with space (!, :, -, (, ), /, etc.)
      7. Collapse whitespace

    Note this only affects the MATCH key. The title shown on screen keeps
    whatever the store wrote.
    """
    if not isinstance(text, str):
        return ''

    text = text.lower()
    text = _LANG_TAG.sub(' ', text)
    text = _EDITION_TAG.sub(' ', text)
    text = _EXPANSION_QUALIFIER.sub(' ', text)
    text = _BASE_QUALIFIER.sub(' ', text.strip())

    # NFKD decomposition separates base letters from combining marks (accents).
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))

    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    return text


# ---------------------------------------------------------------------------
# Title cleaning (display)
# ---------------------------------------------------------------------------

# Generic noise phrases stores append to product titles.
#
# Only phrases that carry NO information in a board-game store belong here.
# "Juego de Mesa" is tautological; attributes like "cooperativo" or "familiar"
# describe a game without identifying it.
#
# Deliberately absent: "juego de cartas", "juego de dados", "juego de rol" and
# their English forms. Those name a different PRODUCT, not a category, and
# stripping them merged distinct games under one title -- "Catan" and
# "Catan: Juego de Cartas" became the same entry, so the card game's $10.990
# was advertised as the price of the board game. Over-merging invents a wrong
# price; under-merging just shows two honest rows, so the tie goes to keeping.
_NOISE_PHRASE = (
    r'juegos?\s+de\s+mesa'
    r'|board\s+game'
    r'|juego\s+familiar|juego\s+educativo|juego\s+cooperativo'
    r'|juego\s+de\s+estrategia|party\s+game'
)

# Standalone category words that appear as comma/separator-delimited tokens.
#
# Only pure ATTRIBUTES belong here -- words that describe a game without ever
# naming one. "party", "dados", "cartas" and "rol" were removed because each
# also ends a real product name: "Sushi Go - Party" was being reduced to
# "Sushi Go" and merged with that different, cheaper game, even though 23
# stores sell Sushi Go Party as its own title.
#
# Some stores do use these as genuine tags ("...!Juego de Mesa, Party, Juego de
# Cartas"), so a trailing tag now survives into the display title. That is the
# cheaper mistake: a slightly noisy label, rather than a wrong price.
_NOISE_WORD = (
    r'cooperativo|familiar|educativo|estrategia|competitivo|abstracto'
)

# Pass 1: noise phrase preceded by a proper word boundary (space, separator, or start).
# The optional (?:el|la|los|las) group pulls the Spanish definite article INTO the
# match so that _strip_unless_subtitle can decide whether to keep or drop the whole
# "El Juego de Mesa" cluster in one shot — preventing an orphaned "El" from being
# left behind after the noise phrase is stripped.
# Note: the leading separator (e.g. "- " before "Juego de Mesa") is intentionally
# NOT consumed here.  Leaving it in place lets pass 3 recognise any noise words that
# follow (e.g. "Cooperativo" in "- Juego de Mesa Cooperativo") as punct-separated
# tags that it can strip independently.
_TITLE_NOISE = re.compile(
    r'(?:^|(?<=[\s\-\|,;:]))(?:\b(?:el|la|los|las)\b\s+)?(?:' + _NOISE_PHRASE + r')\s*[\-\|,;:]?',
    re.IGNORECASE,
)

# Pass 2: noise phrase directly concatenated to a preceding word without space
# ("La CuraJuego de Mesa") — matched when the phrase runs to end-of-string or separator.
_TITLE_NOISE_CONCAT = re.compile(
    r'(?<=[A-Za-záéíóúüñÁÉÍÓÚÜÑ])(?:' + _NOISE_PHRASE + r')(?:\s*[\-\|,;:].*)?$',
    re.IGNORECASE,
)

# Pass 3: trailing comma/dash-separated noise words left after primary phrase removal.
# The preceding separator MUST contain at least one punctuation char (comma, colon,
# dash, pipe, semicolon) — pure whitespace is NOT a valid separator here.  This is
# the key guard that prevents stripping noise words that are part of the actual game
# name: "El Rey De Los Dados" has only a space between "Los" and "Dados" (a natural
# word boundary), whereas "Pandemic - Cooperativo, dados" has "-" and "," (real
# tag delimiters).  The lookahead mirrors the same requirement so that chaining
# (" - Cooperativo, Familiar") is also recognised correctly.
_TRAILING_NOISE = re.compile(
    r'(?:[\-\|,;:]\s*|\s+[\-\|,;:]\s*)(?:' + _NOISE_WORD + r')'
    r'(?=(?:[\-\|,;:]\s*|\s+[\-\|,;:]\s*)(?:' + _NOISE_WORD + r')|\s*$)',
    re.IGNORECASE,
)

# Guards that prevent stripping noise phrases that are actually part of a
# product's subtitle (e.g. "Arkham Horror: El Juego de Cartas" → keep whole).
# Spanish definite article immediately before a noise phrase signals a genuine
# subtitle ("El Juego de Cartas" = "The Card Game") not a generic category tag.
_ARTICLE_PREFIX = re.compile(r'\b(?:el|la|los|las)\s*$', re.IGNORECASE)
_SUBTITLE_TAIL  = re.compile(r'\b(?:el|la|los|las)\s+juego\s+de\s*$', re.IGNORECASE)


def _strip_unless_subtitle(m: re.Match) -> str:
    """Pass-1 callback: keep the noise phrase when introduced by a definite article,
    UNLESS the phrase is 'Juego de Mesa'/'Board Game' — those are always redundant
    category labels in a board-game store, never a distinguishing subtitle.

    The optional article group in _TITLE_NOISE may now be INSIDE the match, so we
    check both the matched text itself and the preceding context for an article."""
    phrase = m.group(0)
    if re.search(r'juego\s+de\s+mesa|board\s+game', phrase, re.IGNORECASE):
        return ' '
    article_in_phrase = bool(re.match(r'[\-\|,;:\s]*\b(?:el|la|los|las)\b', phrase, re.IGNORECASE))
    article_before    = bool(_ARTICLE_PREFIX.search(m.string[:m.start()]))
    return phrase if (article_in_phrase or article_before) else ' '


def _keep_if_subtitle_tail(m: re.Match) -> str:
    """Pass-3 callback: keep a trailing noise word when it follows 'article juego de'."""
    return m.group(0) if _SUBTITLE_TAIL.search(m.string[:m.start()]) else ''


def clean_title(text: str) -> str:
    """
    Remove generic category noise from a store title for display.
    Preserves original casing and accent marks — only strips noise tokens.

    Handles:
    - Standard suffixes:   "Catan - Juego de Mesa"       → "Catan"
    - Separator variants:  "Carcassonne | Board Game"    → "Carcassonne"
    - No-space joins:      "Pandemic La CuraJuego de Mesa, Cooperativo, Juego de dados"
                                                         → "Pandemic La Cura"
    - Mid-title noise:     "Clank! Juego de Mesa Aventura" → "Clank! Aventura"
    - Subtitle protection: "Arkham Horror: El Juego de Cartas" → unchanged
    """
    if not isinstance(text, str):
        return text
    cleaned = _TITLE_NOISE.sub(_strip_unless_subtitle, text)
    cleaned = _TITLE_NOISE_CONCAT.sub('', cleaned)
    cleaned = _TRAILING_NOISE.sub(_keep_if_subtitle_tail, cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    # Pass 4: drop a trailing orphaned article left behind by noise stripping
    # (e.g. "Catan el [Juego de Mesa stripped]" → "Catan el" → "Catan").
    cleaned = re.sub(r'\s+\b(?:el|la|los|las)\b\s*$', '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip(' –—-|,:;')


# ---------------------------------------------------------------------------
# Price parsing
# ---------------------------------------------------------------------------

# Matches the numeric part of Chilean price strings.
_PRICE_RE = re.compile(r'[\d.,]+')


def parse_price(text) -> float | None:
    """
    Extract a numeric price from a raw price string.
    Returns a float or None if unparseable.

    Handles both Chilean and mixed store formats:
      "$69.990"      -> 69990.0   (dot = thousands separator)
      "$69.990,50"   -> 69990.5   (dot = thousands, comma = decimal)
      "$49,000"      -> 49000.0   (comma = thousands separator, 3-digit group)
      "69,990"       -> 69990.0   (comma = thousands separator, 3-digit group)
    """
    if not isinstance(text, str) or not text.strip():
        return None

    m = _PRICE_RE.search(text)
    if not m:
        return None

    raw = m.group()

    has_dot   = '.' in raw
    has_comma = ',' in raw

    if has_dot and has_comma:
        # Both separators present.
        if raw.rfind('.') > raw.rfind(','):
            # Dot comes last → decimal dot, comma is thousands: "1,234.56"
            raw = raw.replace(',', '')
        else:
            # Comma comes last → decimal comma, dot is thousands: "1.234,56"
            raw = raw.replace('.', '').replace(',', '.')
    elif has_comma and not has_dot:
        # Comma only. If the part after the comma is exactly 3 digits → thousands separator.
        # e.g. "49,000" or "9,990" → thousands. "9,5" → decimal.
        after_comma = raw.rsplit(',', 1)[-1]
        if len(after_comma) == 3:
            raw = raw.replace(',', '')
        else:
            raw = raw.replace(',', '.')
    elif has_dot and not has_comma:
        # Dot only. If the part after the dot is exactly 3 digits → thousands separator.
        # e.g. "9.990" → 9990. "9.5" → 9.5.
        after_dot = raw.rsplit('.', 1)[-1]
        if len(after_dot) == 3:
            raw = raw.replace('.', '')
        # else: leave as-is (decimal dot)

    try:
        return float(raw)
    except ValueError:
        return None

"""
utils.py
--------
Shared helpers for normalization, price parsing, discount calculation,
sorting, and terminal pagination.
"""

import re
import math
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


def normalize(text: str) -> str:
    """
    Return a cleaned, lowercase, accent-free, punctuation-free version of a
    title for fuzzy matching. Original title is NOT modified.

    Pipeline:
      1. Lowercase
      2. Strip language tags  ("en español", "en inglés", etc.)
      3. Strip edition markers ("edición deluxe", "2da edición", etc.)
      4. Remove accents        (é→e, ñ→n, ü→u, etc.)
      5. Replace punctuation   with space (!, :, -, (, ), /, etc.)
      6. Collapse whitespace
    """
    if not isinstance(text, str):
        return ''

    text = text.lower()
    text = _LANG_TAG.sub(' ', text)
    text = _EDITION_TAG.sub(' ', text)

    # NFKD decomposition separates base letters from combining marks (accents).
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))

    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    return text


# ---------------------------------------------------------------------------
# Price parsing
# ---------------------------------------------------------------------------

# Matches the numeric part of Chilean price strings.
_PRICE_RE = re.compile(r'[\d.,]+')


def parse_price(text) -> float | None:
    """
    Extract a numeric price from a raw price string.
    Returns a float or None if unparseable.

    Chilean format uses dot as thousands separator:
      "$69.990"    -> 69990.0
      "$69.990,50" -> 69990.5
      "69,990"     -> 69990.0
    """
    if not isinstance(text, str) or not text.strip():
        return None

    m = _PRICE_RE.search(text)
    if not m:
        return None

    raw = m.group()

    # If the last separator is a comma and it appears after any dot -> decimal comma format.
    if ',' in raw and raw.rfind(',') > raw.rfind('.'):
        raw = raw.replace('.', '').replace(',', '.')
    else:
        # Dots are thousands separators; strip both dots and commas.
        raw = raw.replace('.', '').replace(',', '')

    try:
        return float(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Discount calculation
# ---------------------------------------------------------------------------

def calc_discount_pct(original_str, current_str) -> float | None:
    """
    Calculate percentage discount between original and sale price.
    Returns a rounded float (e.g. 41.4) or None if either value is
    unparseable or the result is not a valid positive discount.
    """
    original = parse_price(original_str)
    current  = parse_price(current_str)

    if original is None or current is None:
        return None
    if original <= 0 or current <= 0:
        return None
    if current >= original:
        return None

    return round((1 - current / original) * 100, 1)


def format_discount(original_str, current_str) -> str:
    """
    Return a display string like "-41%" or "-" when there is no discount.
    """
    pct = calc_discount_pct(original_str, current_str)
    return f"-{pct:.0f}%" if pct is not None else '-'


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

SORT_OPTIONS = ('discount', 'price', 'store')


def sort_table(df, by: str):
    """
    Sort a product DataFrame by one of: 'discount', 'price', 'store'.

    discount -> highest discount first; no-discount rows go to the bottom.
    price    -> lowest effective price first (sale price preferred, else original).
    store    -> alphabetical by store name.

    Returns a new sorted DataFrame; does not modify the input.
    """
    df = df.copy()

    if by == 'discount':
        df['_sort'] = df.apply(
            lambda r: calc_discount_pct(r.get('original_price'), r.get('current_price')) or -1,
            axis=1,
        )
        return df.sort_values('_sort', ascending=False).drop(columns='_sort')

    if by == 'price':
        # Prefer sale price for sorting; fall back to original if no sale.
        df['_sort'] = df.apply(
            lambda r: (
                parse_price(r.get('current_price'))
                or parse_price(r.get('original_price'))
                or math.inf
            ),
            axis=1,
        )
        return df.sort_values('_sort', ascending=True).drop(columns='_sort')

    if by == 'store':
        return df.sort_values('store', ascending=True)

    raise ValueError(f"Unknown sort key '{by}'. Valid options: {SORT_OPTIONS}")


# ---------------------------------------------------------------------------
# Terminal pagination
# ---------------------------------------------------------------------------

def paginate(lines: list, page_size: int = 20) -> None:
    """
    Print a list of strings with a simple press-Enter pager.
    If output fits within page_size lines, prints without pausing.
    Ctrl+C exits cleanly at any page break.
    """
    total = len(lines)
    for i, line in enumerate(lines):
        print(line)
        if (i + 1) % page_size == 0 and (i + 1) < total:
            try:
                input(f"  -- {i + 1}/{total} líneas · Enter para continuar, Ctrl+C para salir --")
            except (KeyboardInterrupt, EOFError):
                print()
                return

"""
utils.py
--------
Title normalization for fuzzy matching.

normalize() is applied to both the search query and all CSV titles before
comparison. Original titles are preserved in the DataFrame for display.
"""

import re
import unicodedata


# Language tags that stores append to titles.
# Matches patterns like: "en español", "en inglés", "en ingles",
# "(en español)", "español", "ingles", "english", "castellano".
_LANG_TAG = re.compile(
    r'[\(\[]?\b(en\s+)?(espa[nñ]ol|ingl[eé]s|ingles|english|castellano)\b[\)\]]?',
    re.IGNORECASE,
)

# Edition / version markers that differ between stores but refer to the same game.
# e.g. "edición deluxe", "edicion kickstarter", "2da edicion"
_EDITION_TAG = re.compile(
    r'\b\d+[aª]?\s*(edici[oó]n|edition)\b|\b(edici[oó]n|edition)\b',
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    """
    Return a cleaned, lowercase, accent-free, punctuation-free version of a
    title suitable for fuzzy matching. Does NOT modify the original title.

    Steps:
      1. Lowercase
      2. Strip language tags  ("en español", "en inglés", etc.)
      3. Strip edition markers ("edición deluxe", "2da edición", etc.)
      4. Remove accents       (é → e, ñ → n, etc.)
      5. Remove punctuation   (!, :, -, (, ), etc.) — replaced with space
      6. Collapse whitespace
    """
    if not isinstance(text, str):
        return ''

    text = text.lower()
    text = _LANG_TAG.sub(' ', text)
    text = _EDITION_TAG.sub(' ', text)

    # Decompose characters and drop combining marks (accents).
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))

    # Replace any non-alphanumeric character with a space.
    text = re.sub(r'[^\w\s]', ' ', text)

    # Collapse runs of whitespace.
    text = re.sub(r'\s+', ' ', text).strip()

    return text

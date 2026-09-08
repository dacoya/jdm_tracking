"""
Game search: FTS candidate generation + fuzzy ranking.

Two stages, deliberately separated:

  1. SQLite FTS5 decides what is *plausible* -- cheap, indexed, and it replaces
     the old full scan that ran rapidfuzz over every unique title on every
     keystroke.
  2. rapidfuzz decides what is *relevant*, using the same blended score the
     previous implementation tuned, plus a kind penalty so sleeves and boosters
     stop outranking the game they are named after.

Pure: takes a connection, returns list[dict]. Nothing here prints.
"""
from rapidfuzz import fuzz, process

try:
    from . import repo
    from .classify import KIND_GAME, kind_rank
    from .utils import normalize
except ImportError:
    import repo
    from classify import KIND_GAME, kind_rank
    from utils import normalize

# Below this blended relevance a candidate is noise, not a weak match.
RELEVANCE_FLOOR = 55.0

# When FTS yields fewer than this many usable hits, fall back to a fuzzy scan.
# FTS matches prefixes, so it cannot bridge a misspelling: "pandemc" is not a
# prefix of "pandemic" and returns nothing at all without this.
FALLBACK_THRESHOLD = 5
FALLBACK_CUTOFF = 80

# Rank penalty per step away from a plain game (expansion < tcg < puzzle <
# accessory). Large enough to sink an accessory below a real game of equal
# textual relevance, small enough that an exact-title accessory still surfaces
# when it is genuinely what was asked for.
KIND_PENALTY = 8.0


def _relevance(norm_query: str, norm: str) -> float:
    """
    Blended relevance (0-100) of a normalized title against the query.

    token_sort_ratio breaks the "everything matches 100%" tie for short queries
    ("catan" beats "catan big box" and "dobble catan"); partial_ratio keeps
    typo and substring tolerance ("terraformin" -> "terraforming mars").
    """
    return (
        0.30 * fuzz.token_set_ratio(norm_query, norm)
        + 0.40 * fuzz.token_sort_ratio(norm_query, norm)
        + 0.30 * fuzz.partial_ratio(norm_query, norm)
    )


def _boost(norm_query: str, norm: str) -> float:
    """Ordering bonus that surfaces the base/exact title ahead of variants."""
    if norm == norm_query:
        return 100.0
    if norm.startswith(norm_query + " "):
        return 12.0
    if norm_query in norm.split():
        return 6.0
    return 0.0


def _fuzzy_candidates(conn, norm_query: str, limit: int = 60,
                      include_stale: bool = False) -> list[dict]:
    """
    Typo-tolerant candidates via a full fuzzy scan of game norms.

    WRatio casts the wide, typo-tolerant net the old implementation relied on;
    the blended score in `search` still does the actual ranking.
    """
    pairs = repo.game_norms(conn)
    if not pairs:
        return []

    matches = process.extract(
        norm_query,
        {gid: norm for gid, norm in pairs},
        scorer=fuzz.WRatio,
        limit=limit,
        score_cutoff=FALLBACK_CUTOFF,
    )
    return repo.games_by_ids(conn, [gid for _, _, gid in matches],
                             include_stale=include_stale)


def _merge(primary: list[dict], extra: list[dict]) -> list[dict]:
    """Union two candidate lists, keeping the first occurrence of each game."""
    seen = {c["game_id"] for c in primary}
    return primary + [c for c in extra if c["game_id"] not in seen]


def search(conn, query: str, limit: int = 30, kinds=None,
           include_accessories: bool = False,
           include_stale: bool = False) -> list[dict]:
    """
    Ranked games matching `query`.

    Each result carries enough to decide without a second lookup: cheapest
    price, how many stores stock it, whether any has it in stock, and its kind.

    `kinds` restricts to an explicit set. Otherwise accessories are hidden
    unless `include_accessories` is set -- searching "catan" should return the
    game, not forty sleeve listings that mention it.
    """
    norm_query = normalize(query)
    if not norm_query:
        return []

    candidates = repo.candidate_games(conn, query, include_stale=include_stale)
    if len(candidates) < FALLBACK_THRESHOLD:
        candidates = _merge(
            candidates, _fuzzy_candidates(conn, norm_query, include_stale=include_stale))
    if not candidates:
        return []

    if kinds:
        wanted = set(kinds)
        candidates = [c for c in candidates if c.get("kind") in wanted]
    elif not include_accessories:
        candidates = [c for c in candidates if c.get("kind") != "accessory"]

    scored = []
    for c in candidates:
        norm = c["norm"] or ""
        relevance = _relevance(norm_query, norm)
        if relevance < RELEVANCE_FLOOR:
            continue
        penalty = KIND_PENALTY * kind_rank(c.get("kind") or KIND_GAME)
        scored.append({
            **c,
            "score": round(relevance, 1),
            "_rank": relevance + _boost(norm_query, norm) - penalty,
        })

    # Popularity then brevity break ties: a game in 20 stores is more likely the
    # one being asked for than a same-scoring obscure variant.
    scored.sort(
        key=lambda r: (r["_rank"], r.get("n_stores") or 0, -len(r.get("title") or "")),
        reverse=True,
    )
    return [{k: v for k, v in r.items() if k != "_rank"} for r in scored[:limit]]


def best_match(conn, query: str, **kwargs) -> dict | None:
    """Top-ranked game for a query, or None."""
    hits = search(conn, query, limit=1, **kwargs)
    return hits[0] if hits else None

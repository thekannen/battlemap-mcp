"""Ranked matching over asset paths, for callers whose words are not the filenames.

A brief says "double door", "round table", "flower bush"; the library says
`door_double_01`, `round_table_02`, `bush_flower_03`. A contiguous substring
test misses all three, and the caller gets an empty result with no hint that a
perfectly good asset is sitting there under a different word order.

What this can and cannot do is worth being precise about, because the gap is
easy to oversell:

- it fixes word ORDER and separators ("double door" -> door_double_01)
- it tolerates TYPOS ("tavren" -> tavern)
- it does NOT do synonyms. "mug" will not find `tankard`, and "tableware" will
  not find `food_bread_01`. Nothing here understands what a word means, so a
  caller that draws a blank should search a broader term or list the category.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

MATCH_MODES = ("substring", "tokens", "fuzzy")
DEFAULT_MIN_SCORE = 0.55


@dataclass(frozen=True)
class AssetMatch:
    """One asset path with the score that kept it and the terms that hit."""

    path: str
    score: float
    matched: tuple[str, ...]


def _stem(path: str) -> str:
    """The filename without directories or extension, lowercased."""
    tail = path.rsplit("/", 1)[-1]
    return tail.rsplit(".", 1)[0].lower()


def _words(text: str) -> list[str]:
    """Split on the separators asset names actually use, not just whitespace."""
    cleaned = "".join(character if character.isalnum() else " " for character in text.lower())
    return [word for word in cleaned.split() if word]


def _haystack(path: str) -> str:
    """A normalized form of the whole path, so directory words count too.

    `res://textures/objects/furniture/tables/round_table_01.png` carries
    "furniture" and "tables" in its directories; a caller searching "furniture
    table" means exactly that, and dropping the directories would lose it.
    """
    return " ".join(_words(path.replace("res://", "")))


def _similarity(query: str, candidate: str) -> float:
    return SequenceMatcher(None, query, candidate).ratio()


def score_path(path: str, query: str, mode: str) -> AssetMatch | None:
    """Score one path, or None when it does not qualify under this mode."""
    terms = _words(query)
    if not terms:
        return AssetMatch(path, 1.0, ())
    haystack = _haystack(path)
    stem = _stem(path)
    stem_words = _words(stem)

    if mode == "substring":
        return AssetMatch(path, 1.0, (query.lower(),)) if query.lower() in path.lower() else None

    if mode == "tokens":
        # Every term must appear somewhere in the path, in any order. Rank by
        # how closely the stem resembles the query so the most on-the-nose
        # filename comes first rather than an arbitrary directory hit.
        hits = tuple(term for term in terms if term in haystack)
        if len(hits) != len(terms):
            return None
        return AssetMatch(path, _similarity(" ".join(terms), " ".join(stem_words)), hits)

    # fuzzy: best resemblance to the stem or the whole path, plus credit for any
    # term that lands exactly. Without the exact-term credit, a long path can
    # out-score a short precise one purely by having more characters to align.
    hits = tuple(term for term in terms if term in haystack)
    best = max(
        _similarity(" ".join(terms), " ".join(stem_words)),
        _similarity(" ".join(terms), haystack),
    )
    if hits:
        best = max(best, len(hits) / len(terms))
    return AssetMatch(path, best, hits)


def rank_assets(
    paths: list[str],
    query: str,
    *,
    mode: str = "substring",
    min_score: float = DEFAULT_MIN_SCORE,
) -> list[AssetMatch]:
    """Return qualifying assets, best first.

    Ties break on the shorter path, so `door_01` precedes
    `door_01_decorated_variant` when both score the same.
    """
    if mode not in MATCH_MODES:
        raise ValueError(f"mode must be one of {MATCH_MODES}, got {mode!r}")
    floor = 0.0 if mode != "fuzzy" else min_score
    matches = []
    for path in paths:
        match = score_path(path, query, mode)
        if match is not None and match.score >= floor:
            matches.append(match)
    matches.sort(key=lambda m: (-m.score, len(m.path), m.path))
    return matches

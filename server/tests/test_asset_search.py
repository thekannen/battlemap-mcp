"""Ranked asset matching. Pure string work — never touches the socket."""

import pytest

from battlemap_mcp.asset_search import rank_assets, score_path

# Real paths from a stock library, so the cases are the ones callers actually hit.
LIBRARY = [
    "res://textures/objects/furniture/tables/round_table_01.png",
    "res://textures/objects/furniture/tables/round_table_02.png",
    "res://textures/objects/furniture/tables/bar_table.png",
    "res://textures/objects/furniture/chairs/bar_chair.png",
    "res://textures/objects/furniture/chairs/bench_03.png",
    "res://textures/objects/furniture/storage/merchant_shelf_01.png",
    "res://textures/objects/supplies/barrels/barrel_01.png",
    "res://textures/objects/vegetation/shrubs/bush_flower_03.png",
    "res://textures/portals/door_01.png",
    "res://textures/portals/window_02.png",
    "res://textures/tilesets/simple/tileset_wood_damaged.png",
]


def paths(matches):
    return [m.path for m in matches]


def test_substring_is_unchanged_and_stays_the_default():
    """The existing behaviour has to survive, or every current caller shifts."""
    got = rank_assets(LIBRARY, "round_table", mode="substring")
    assert paths(got) == [
        "res://textures/objects/furniture/tables/round_table_01.png",
        "res://textures/objects/furniture/tables/round_table_02.png",
    ]
    # a contiguous-substring miss stays a miss in this mode
    assert rank_assets(LIBRARY, "table round", mode="substring") == []


def test_tokens_mode_ignores_word_order():
    """ "table round" is how a brief says it; the filename says round_table."""
    got = paths(rank_assets(LIBRARY, "table round", mode="tokens"))
    assert "res://textures/objects/furniture/tables/round_table_01.png" in got
    assert "res://textures/objects/furniture/chairs/bar_chair.png" not in got


def test_tokens_mode_requires_every_term():
    """A partial hit is a miss — otherwise one common word drags in the library."""
    assert rank_assets(LIBRARY, "round barrel", mode="tokens") == []


def test_tokens_mode_can_match_on_directory_words():
    """Directories carry real vocabulary: .../furniture/tables/... ."""
    got = paths(rank_assets(LIBRARY, "furniture storage", mode="tokens"))
    assert got == ["res://textures/objects/furniture/storage/merchant_shelf_01.png"]


def test_fuzzy_tolerates_a_typo():
    """A transposed letter should not cost the caller a whole search."""
    got = paths(rank_assets(LIBRARY, "barrle", mode="fuzzy", min_score=0.5))
    assert "res://textures/objects/supplies/barrels/barrel_01.png" in got


def test_fuzzy_ranks_the_closest_name_first():
    got = paths(rank_assets(LIBRARY, "bar table", mode="fuzzy", min_score=0.4))
    assert got[0] == "res://textures/objects/furniture/tables/bar_table.png"


def test_ties_prefer_the_shorter_path():
    """door_01 should beat a longer decorated variant at equal score."""
    library = [
        "res://textures/portals/door_01_decorated_variant.png",
        "res://textures/portals/door_01.png",
    ]
    assert paths(rank_assets(library, "door_01", mode="substring"))[0] == (
        "res://textures/portals/door_01.png"
    )


def test_it_does_not_pretend_to_understand_synonyms():
    """The honest boundary: this is string matching, not meaning.

    "mug" finding a tankard, or "tableware" finding bread, would need a notion
    of what the words mean. Nothing here has one, so a caller drawing a blank
    should widen the term rather than assume the asset is absent — and this
    test exists so nobody later mistakes the feature for semantic search.
    """
    for term in ("mug", "tableware", "seating"):
        assert rank_assets(LIBRARY, term, mode="fuzzy", min_score=0.75) == []


def test_empty_query_returns_everything_unfiltered():
    assert len(rank_assets(LIBRARY, "", mode="tokens")) == len(LIBRARY)


def test_unknown_mode_is_refused():
    with pytest.raises(ValueError, match="mode must be one of"):
        rank_assets(LIBRARY, "door", mode="semantic")


def test_score_path_reports_which_terms_hit():
    match = score_path(
        "res://textures/objects/furniture/tables/round_table_01.png",
        "round table",
        "tokens",
    )
    assert match is not None
    assert set(match.matched) == {"round", "table"}

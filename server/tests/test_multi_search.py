"""Several asset searches in one call, without multiplying the engine's work.

The saving for the model is a round trip per term. The risk is the opposite:
ranked modes survey the WHOLE category, and doing that once per term would make
a convenience for the model an expensive operation for the editor, which runs
it on the thread that draws the map.
"""

from __future__ import annotations

import pytest

from battlemap_mcp import server
from battlemap_mcp.errors import ValidationError

CATALOGUE = [
    "res://textures/objects/furniture/round_table_01.png",
    "res://textures/objects/furniture/table_long_02.png",
    "res://textures/objects/furniture/chair_01.png",
    "res://textures/objects/containers/barrel_01.png",
]


@pytest.fixture
def bridge(monkeypatch):
    sent: list[dict] = []

    def request(command, **params):
        sent.append({"cmd": command, **params})
        if params.get("only"):
            return {"colorable": [params["only"][0]], "colorable_scanned": True}
        search = params.get("search", "")
        hits = [path for path in CATALOGUE if search in path]
        return {
            "assets": hits if search else CATALOGUE,
            "matched": len(hits),
            "returned": len(hits),
            "total": len(CATALOGUE),
            "total_unfiltered": len(CATALOGUE) + 5,
            "hidden_unusable": 5,
            "colorable": [],
            "colorable_scanned": True,
        }

    monkeypatch.setattr(server.bridge, "request", request)
    return sent


def test_each_term_keeps_its_own_results(bridge):
    result = server.list_assets(searches=["table", "barrel"])

    assert list(result["results"]) == ["table", "barrel"]
    assert result["results"]["barrel"]["assets"] == [
        "res://textures/objects/containers/barrel_01.png"
    ]
    assert len(result["results"]["table"]["assets"]) == 2


def test_a_term_that_finds_nothing_says_so_rather_than_disappearing(bridge):
    result = server.list_assets(searches=["table", "sarcophagus"])

    assert result["results"]["sarcophagus"]["assets"] == []
    assert "sarcophagus" in result["note"]


def test_ranked_modes_never_pull_the_whole_category(bridge):
    """The category is the thing that does not fit: a 141,197-asset transfer is
    what broke ranked search. Each term filters in the bridge instead."""
    server.list_assets(searches=["table", "chair", "barrel"], match_mode="tokens")

    lookups = [call for call in bridge if not call.get("only")]
    assert len(lookups) == 3, f"{len(lookups)} lookups for 3 terms"
    for call in lookups:
        assert call.get("terms"), "a ranked lookup must filter by terms"
        assert call["limit"] <= server.RANK_CANDIDATE_LIMIT


def test_ranked_modes_scan_colour_masks_once_for_every_winner(bridge):
    result = server.list_assets(searches=["table", "chair"], match_mode="tokens")

    detail = [call for call in bridge if call.get("only")]
    assert len(detail) == 1
    assert len(detail[0]["only"]) == len(set(detail[0]["only"])), "an asset was scanned twice"
    # The fake marks the first path of the scan colourable; it must land on the
    # term that actually returned it.
    colourable = {term: found["colorable"] for term, found in result["results"].items()}
    assert sum(len(paths) for paths in colourable.values()) == 1


def test_repeated_and_blank_terms_are_dropped(bridge):
    result = server.list_assets(searches=["table", "TABLE", " ", "table "])
    assert result["terms"] == ["table"]


def test_too_many_terms_are_refused(bridge):
    with pytest.raises(ValidationError, match="past the 8"):
        server.list_assets(searches=[f"term{i}" for i in range(9)])
    assert bridge == []


def test_search_and_searches_together_are_refused(bridge):
    with pytest.raises(ValidationError, match="not both"):
        server.list_assets(search="table", searches=["chair"])
    assert bridge == []


def test_the_total_returned_is_bounded_and_the_cap_is_reported(bridge):
    result = server.list_assets(searches=["table", "chair", "barrel", "door"], limit=500)

    assert result["per_term_limit"] == server.MAX_MULTI_RESULTS // 4
    assert all(call.get("limit") == result["per_term_limit"] for call in bridge)


def test_a_generous_limit_cannot_compound_across_terms(bridge):
    """Measured in a live run: four terms at limit=40 returned 160 paths in one
    25,700-character block. Terms share the budget so that cannot recur."""
    result = server.list_assets(searches=["stall", "market", "awning", "canopy", "tent"], limit=60)

    assert result["per_term_limit"] <= server.MAX_MULTI_RESULTS // 5
    assert server.MAX_MULTI_RESULTS <= 80


def test_a_single_search_is_unchanged(bridge):
    """The multi-term path must not alter the shape a one-term call returns."""
    result = server.list_assets(category="Objects", search="table")

    assert "results" not in result
    assert result["assets"] == [
        "res://textures/objects/furniture/round_table_01.png",
        "res://textures/objects/furniture/table_long_02.png",
    ]

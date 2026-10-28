"""build_room leaves out the parts of its boundary an existing wall already covers.

Two rooms side by side used to get two walls on the shared edge. A door placed
there mounts on one of them, so in a Universal VTT export the other wall still
crosses the doorway and the door never opens.
"""

from __future__ import annotations

import pytest

from battlemap_mcp import server
from battlemap_mcp.errors import ValidationError
from battlemap_mcp.shared_walls import segments_of, split_boundary

A = [[0, 0], [512, 0], [512, 512], [0, 512]]
B = [[512, 0], [1024, 0], [1024, 512], [512, 512]]


def loop(points: list[list[float]], wall_id: int = 7) -> dict:
    return {"id": wall_id, "loop": True, "points": points}


def unordered(segment) -> tuple:
    return tuple(sorted(tuple(p) for p in segment))


# --- geometry ---------------------------------------------------------------


def test_a_room_touching_no_wall_stays_one_loop():
    runs, shared = split_boundary(
        B, segments_of([{"loop": False, "points": [[2000, 0], [3000, 0]]}])
    )
    assert runs == [B]
    assert shared == []


def test_the_edge_two_rooms_share_is_left_out():
    runs, shared = split_boundary(B, segments_of([loop(A)]))
    assert [unordered(s) for s in shared] == [((512, 0), (512, 512))]
    assert runs == [[[512, 0], [1024, 0], [1024, 512], [512, 512]]]


def test_a_partly_shared_edge_keeps_its_uncovered_part():
    tall = [[512, 0], [1024, 0], [1024, 1024], [512, 1024]]
    runs, shared = split_boundary(tall, segments_of([loop(A)]))
    assert [unordered(s) for s in shared] == [((512, 0), (512, 512))]
    assert runs == [[[512, 0], [1024, 0], [1024, 1024], [512, 1024], [512, 512]]]


def test_a_shared_edge_in_the_middle_joins_the_runs_around_the_corner():
    left = [[-512, 0], [0, 0], [0, 512], [-512, 512]]
    runs, shared = split_boundary(left, segments_of([loop(A)]))
    assert [unordered(s) for s in shared] == [((0, 0), (0, 512))]
    assert runs == [[[0, 512], [-512, 512], [-512, 0], [0, 0]]]


def test_a_wall_within_a_woxel_counts_as_shared():
    _, shared = split_boundary(
        B, segments_of([{"loop": False, "points": [[512.5, -1], [512.5, 600]]}])
    )
    assert len(shared) == 1


def test_a_parallel_wall_two_woxels_away_is_not_shared():
    _, shared = split_boundary(B, segments_of([{"loop": False, "points": [[510, 0], [510, 512]]}]))
    assert shared == []


def test_a_loop_contributes_its_closing_edge():
    segments = segments_of(
        [loop([[0, 0], [1, 0], [1, 1]]), {"loop": False, "points": [[5, 5], [6, 6]]}]
    )
    assert segments == [((0, 0), (1, 0)), ((1, 0), (1, 1)), ((1, 1), (0, 0)), ((5, 5), (6, 6))]


# --- build_room -------------------------------------------------------------


@pytest.fixture
def bridge(monkeypatch):
    walls: list[dict] = []
    sent: list[tuple[str, dict]] = []

    def request(command, **params):
        sent.append((command, params))
        if command == "list_elements":
            page = walls[params["offset"] : params["offset"] + params["limit"]]
            return {"elements": page, "total": len(walls)}
        if command == "build_room":
            if "wall_runs" in params:
                return {"wall_ids": list(range(100, 100 + len(params["wall_runs"]))), "points": []}
            return {"wall_id": 1, "points": []}
        return {}

    monkeypatch.setattr(server.bridge, "request", request)
    return walls, sent


def built(sent) -> dict:
    [params] = [p for command, p in sent if command == "build_room"]
    return params


def test_build_room_sends_only_the_uncovered_runs(bridge):
    walls, sent = bridge
    walls.append(loop(A))
    result = server.build_room(rect=[512, 0, 512, 512], floor="none")
    assert built(sent)["wall_runs"] == [
        [[512.0, 0.0], [1024.0, 0.0], [1024.0, 512.0], [512.0, 512.0]]
    ]
    assert result["wall_ids"] == [100]
    assert [unordered(s) for s in result["shared_edges"]] == [((512, 0), (512, 512))]


def test_build_room_with_no_neighbour_sends_no_runs(bridge):
    _, sent = bridge
    result = server.build_room(rect=[0, 0, 512, 512], floor="none")
    assert "wall_runs" not in built(sent)
    assert result["wall_id"] == 1
    assert "shared_edges" not in result


def test_shared_walls_keep_draws_the_full_loop_without_reading_walls(bridge):
    walls, sent = bridge
    walls.append(loop(A))
    server.build_room(rect=[512, 0, 512, 512], floor="none", shared_walls="keep")
    assert "wall_runs" not in built(sent)
    assert [command for command, _ in sent] == ["build_room"]


def test_build_room_rejects_an_unknown_shared_walls_mode(bridge):
    _, sent = bridge
    with pytest.raises(ValidationError, match="shared_walls"):
        server.build_room(rect=[0, 0, 512, 512], floor="none", shared_walls="merge")
    assert sent == []


def test_build_room_splits_a_points_boundary_too(bridge):
    walls, sent = bridge
    walls.append(loop(A))
    server.build_room(points=B, floor="none")
    assert len(built(sent)["wall_runs"]) == 1


# regression: a boundary already walled all round (the same room built twice,
# or a floor laid inside existing walls) sent wall_runs=[], which the bridge
# refused as "must be a non-empty list", so the floor was never built either.
def test_a_fully_walled_boundary_draws_no_wall_and_still_builds_the_floor(bridge):
    walls, sent = bridge
    walls.append(loop(A))
    result = server.build_room(rect=[0, 0, 512, 512], floor_asset="res://floor.png")
    params = built(sent)
    assert params["wall_runs"] == []
    assert params["floor_asset"] == "res://floor.png"
    assert result["wall_ids"] == []
    assert len(result["shared_edges"]) == 4


def test_a_wall_of_another_type_is_not_shared(bridge):
    walls, sent = bridge
    walls.append({**loop(A), "wall_type": 2})
    result = server.build_room(rect=[512, 0, 512, 512], floor="none")
    assert "wall_runs" not in built(sent)
    assert "shared_edges" not in result


def test_a_wall_of_the_same_type_is_shared(bridge):
    walls, sent = bridge
    walls.append({**loop(A), "wall_type": 1})
    server.build_room(rect=[512, 0, 512, 512], floor="none", wall_type=1)
    assert len(built(sent)["wall_runs"]) == 1


def test_a_wall_of_another_asset_is_not_shared_when_the_asset_is_named(bridge):
    walls, sent = bridge
    walls.append({**loop(A), "wall_type": 0, "asset": "res://walls/stone.png"})
    server.build_room(rect=[512, 0, 512, 512], floor="none", wall_asset="res://walls/wood.png")
    assert "wall_runs" not in built(sent)


def test_a_wall_of_the_named_asset_is_shared(bridge):
    walls, sent = bridge
    walls.append({**loop(A), "wall_type": 0, "asset": "res://walls/wood.png"})
    server.build_room(rect=[512, 0, 512, 512], floor="none", wall_asset="res://walls/wood.png")
    assert len(built(sent)["wall_runs"]) == 1


def test_walls_past_the_read_limit_are_reported(bridge, monkeypatch):
    walls, _ = bridge
    walls.append(loop(A))
    monkeypatch.setattr(
        server,
        "_read_all",
        lambda kind, **_: (
            list(walls),
            {"kind": kind, "total": 9000, "read": 1, "complete": False},
        ),
    )
    result = server.build_room(rect=[512, 0, 512, 512], floor="none")
    assert result["walls_considered"] == {"total": 9000, "read": 1, "complete": False}
    assert "8999" in result["note"]


def test_a_complete_wall_read_adds_no_note(bridge):
    walls, _ = bridge
    walls.append(loop(A))
    result = server.build_room(rect=[512, 0, 512, 512], floor="none")
    assert "note" not in result
    assert "walls_considered" not in result

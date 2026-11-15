import pytest

from battlemap_mcp import server
from battlemap_mcp.errors import ValidationError


def _capture(monkeypatch):
    calls = []
    monkeypatch.setattr(
        server.bridge, "request", lambda cmd, **kw: calls.append((cmd, kw)) or {"updated": 1}
    )
    return calls


def test_declare_sends_only_what_was_given(monkeypatch):
    calls = _capture(monkeypatch)
    server.set_animated_door([7], enabled=True, hinge="b", animation="slide")
    cmd, params = calls[0]
    assert cmd == "set_animated_door"
    assert params == {"ids": [7], "enabled": True, "hinge": "b", "animation": "slide"}


def test_every_setting_passes_through(monkeypatch):
    calls = _capture(monkeypatch)
    server.set_animated_door(
        [1, 2],
        swing="left",
        axis="height",
        door_type="secret",
        state="locked",
        double_door=True,
        extension=0,
        hinge_offset_a=12.5,
        hinge_offset_b=0,
    )
    assert calls[0][1] == {
        "ids": [1, 2],
        "swing": "left",
        "axis": "height",
        "door_type": "secret",
        "state": "locked",
        "double_door": True,
        "extension": 0,
        "hinge_offset_a": 12.5,
        "hinge_offset_b": 0,
    }


def test_removing_a_door(monkeypatch):
    calls = _capture(monkeypatch)
    server.set_animated_door([3], enabled=False)
    assert calls[0][1] == {"ids": [3], "enabled": False}


@pytest.mark.parametrize(
    "kw",
    [
        {"ids": []},
        {"ids": list(range(101)), "enabled": True},
        {"ids": [-1], "enabled": True},
        {"ids": [True], "enabled": True},
        {"ids": [1]},
        {"ids": [1], "enabled": False, "hinge": "a"},
        {"ids": [1], "hinge": "left"},
        {"ids": [1], "door_type": "gate"},
        {"ids": [1], "animation": "spin"},
        {"ids": [1], "state": "ajar"},
        {"ids": [1], "extension": 181},
        {"ids": [1], "extension": True},
        {"ids": [1], "hinge_offset_a": float("nan")},
        {"ids": [1], "hinge_offset_b": -1},
    ],
)
def test_bad_input_never_reaches_the_bridge(monkeypatch, kw):
    monkeypatch.setattr(server.bridge, "request", lambda *a, **k: pytest.fail("bridge called"))
    with pytest.raises(ValidationError):
        server.set_animated_door(**kw)

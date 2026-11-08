import pytest

from battlemap_mcp import server
from battlemap_mcp.errors import ValidationError


def test_request_carries_only_what_was_given(monkeypatch):
    calls = []
    monkeypatch.setattr(
        server.bridge, "request", lambda cmd, **kw: calls.append((cmd, kw)) or {"updated": 1}
    )
    server.set_soft_shadow([4], opacity=0.6, offset=[30, 40])
    cmd, params = calls[0]
    assert cmd == "set_soft_shadow"
    assert params == {"ids": [4], "enabled": True, "opacity": 0.6, "offset": [30, 40]}


def test_settings_and_colour_pass_through(monkeypatch):
    calls = []
    monkeypatch.setattr(
        server.bridge, "request", lambda cmd, **kw: calls.append((cmd, kw)) or {"updated": 2}
    )
    server.set_soft_shadow([1, 2], enabled=False, color="#223344", settings={"blur": 0.3})
    assert calls[0][1] == {
        "ids": [1, 2],
        "enabled": False,
        "color": "#223344",
        "settings": {"blur": 0.3},
    }


@pytest.mark.parametrize(
    "kw",
    [
        {"ids": []},
        {"ids": list(range(101))},
        {"ids": [-1]},
        {"ids": [True]},
        {"ids": [1], "color": "red"},
        {"ids": [1], "color": "#12345"},
        {"ids": [1], "offset": [float("nan"), 0]},
        {"ids": [1], "opacity": float("inf")},
    ],
)
def test_bad_input_never_reaches_the_bridge(monkeypatch, kw):
    monkeypatch.setattr(server.bridge, "request", lambda *a, **k: pytest.fail("bridge called"))
    with pytest.raises(ValidationError):
        server.set_soft_shadow(**kw)

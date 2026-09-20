"""Runtime behavior and validation."""

import json

import pytest

from battlemap_mcp.asset_packs import (
    build_manifest,
    manifest_entry,
    prepare_map_file,
    unknown_ids,
)

# Shaped like the pack.json Dungeondraft mounts, including a pack that ships
# colour overrides and one that does not.
INSTALLED = [
    {
        "id": "8XXbciV2",
        "name": "2MT Medieval Building",
        "version": "2.2",
        "author": "2-Minute Tabletop",
    },
    {
        "id": "FA30DDXY",
        "name": "FA_Starter_Pack_v3.0",
        "version": "3.0",
        "author": "Forgotten Adventures",
        "custom_color_overrides": {"enabled": True, "min_redness": 0.001},
    },
]


def a_map(manifest=None):
    return {
        "header": {"asset_manifest": manifest or [], "uses_default_assets": True},
        "world": {"width": 32, "height": 32, "levels": {"0": {"objects": [{"keep": "me"}]}}},
    }


def test_an_entry_carries_what_dungeondraft_writes():
    entry = manifest_entry(INSTALLED[1])
    assert entry["id"] == "FA30DDXY"
    assert entry["name"] == "FA_Starter_Pack_v3.0"
    assert entry["version"] == "3.0"
    assert entry["author"] == "Forgotten Adventures"
    assert entry["custom_color_overrides"]["enabled"] is True


def test_a_pack_without_colour_overrides_omits_the_field():
    """Maps Dungeondraft wrote omit it rather than writing an empty object."""
    assert "custom_color_overrides" not in manifest_entry(INSTALLED[0])


def test_every_installed_pack_by_default():
    assert [e["id"] for e in build_manifest(INSTALLED)] == ["8XXbciV2", "FA30DDXY"]


def test_a_chosen_subset():
    assert [e["id"] for e in build_manifest(INSTALLED, ["FA30DDXY"])] == ["FA30DDXY"]


def test_an_id_is_never_included_twice():
    """Two files of the same pack must not become two manifest entries."""
    twice = INSTALLED + [dict(INSTALLED[1], version="3.51")]
    assert [e["id"] for e in build_manifest(twice)] == ["8XXbciV2", "FA30DDXY"]


def test_asking_for_a_pack_that_is_not_installed_is_reported():
    assert unknown_ids(INSTALLED, ["FA30DDXY", "nope"]) == ["nope"]


def test_preparing_a_map_keeps_everything_but_the_manifest(tmp_path):
    source = tmp_path / "scratch.dungeondraft_map"
    source.write_text(json.dumps(a_map()), encoding="utf-8")
    out = tmp_path / "with-packs.dungeondraft_map"

    report = prepare_map_file(source, out, build_manifest(INSTALLED))

    assert report["packs_before"] == 0 and report["packs_after"] == 2
    written = json.loads(out.read_text(encoding="utf-8"))
    assert [e["id"] for e in written["header"]["asset_manifest"]] == ["8XXbciV2", "FA30DDXY"]
    # the map itself is carried across untouched
    assert written["world"] == a_map()["world"]
    assert written["header"]["uses_default_assets"] is True
    # and the source is left alone
    assert json.loads(source.read_text(encoding="utf-8"))["header"]["asset_manifest"] == []


def test_a_file_that_is_not_a_map_is_refused(tmp_path):
    source = tmp_path / "notamap.dungeondraft_map"
    source.write_text(json.dumps({"nope": True}), encoding="utf-8")
    with pytest.raises(ValueError, match="no header"):
        prepare_map_file(source, tmp_path / "out.dungeondraft_map", [])


def test_prepare_map_with_packs_refuses_to_choose_for_you(monkeypatch):
    """Omitting `packs` used to mean "every installed pack".

    That is wrong at scale, and the docstring said it was "usually what you
    want": one measured library held 12.5 GB across 14 packs, and a single pack
    carried 129,098 of the map's 141,197 objects. A map's set is fixed at
    creation, so guessing it away is not recoverable — refuse, and hand back a
    catalogue that makes the choice possible.
    """
    import pytest

    from battlemap_mcp import server
    from battlemap_mcp.errors import ValidationError

    def request(command, **params):
        assert command == "list_asset_packs", f"must not reach {command}"
        return {
            "installed": [
                {"id": "FA35OB01", "name": "FA_Objects_A_v3.51"},
                {"id": "Qz7Lm2Pa", "name": "Frozen Coast"},
            ]
        }

    monkeypatch.setattr(server.bridge, "request", request)
    with pytest.raises(ValidationError) as excinfo:
        server.prepare_map_with_packs("anything")

    message = str(excinfo.value)
    # the catalogue has to name both the id to pass back and the subject to judge
    for token in ("FA35OB01", "FA_Objects_A_v3.51", "Qz7Lm2Pa", "Frozen Coast"):
        assert token in message, token


def test_merge_manifest_keeps_packs_the_map_already_depends_on():
    """Replacing the manifest wholesale strips packs the map's objects need."""
    from battlemap_mcp.asset_packs import merge_manifest

    existing = [{"id": "packA", "name": "Pack A", "version": "1.0", "author": "x"}]
    adding = [{"id": "packB", "name": "Pack B", "version": "2.0", "author": "y"}]
    merged = merge_manifest(existing, adding)
    assert [e["id"] for e in merged] == ["packA", "packB"]


def test_merge_manifest_does_not_duplicate_a_pack_already_present():
    from battlemap_mcp.asset_packs import merge_manifest

    existing = [{"id": "packA", "name": "Pack A", "version": "1.0", "author": "x"}]
    merged = merge_manifest(existing, [{"id": "packA", "name": "Pack A", "version": "9.9"}])
    assert len(merged) == 1
    assert merged[0]["version"] == "1.0", "the map's own entry wins, not the installed copy"


def test_prepare_map_file_refuses_to_write_onto_its_source(tmp_path):
    """Runtime behavior and validation."""
    from battlemap_mcp.asset_packs import prepare_map_file

    source = tmp_path / "inn.dungeondraft_map"
    source.write_text(json.dumps({"header": {"asset_manifest": []}, "world": {"a": 1}}))
    with pytest.raises(ValueError) as excinfo:
        prepare_map_file(source, source, [{"id": "packB"}])
    assert "COPY" in str(excinfo.value)
    assert json.loads(source.read_text())["world"] == {"a": 1}, "source must be untouched"


def test_prepare_map_file_preserves_the_sources_own_packs(tmp_path):
    from battlemap_mcp.asset_packs import prepare_map_file

    source = tmp_path / "inn.dungeondraft_map"
    source.write_text(
        json.dumps({"header": {"asset_manifest": [{"id": "packA", "name": "A"}]}, "world": {}})
    )
    report = prepare_map_file(source, tmp_path / "copy.dungeondraft_map", [{"id": "packB"}])
    assert report["pack_ids"] == ["packA", "packB"]
    assert report["kept_from_source"] == ["packA"]
    assert report["added"] == ["packB"]


def test_prepare_map_file_leaves_no_temporary_behind(tmp_path):
    from battlemap_mcp.asset_packs import prepare_map_file

    source = tmp_path / "inn.dungeondraft_map"
    source.write_text(json.dumps({"header": {"asset_manifest": []}, "world": {}}))
    destination = tmp_path / "copy.dungeondraft_map"
    prepare_map_file(source, destination, [{"id": "packB"}])
    assert destination.exists()
    assert list(tmp_path.glob("*.preparing")) == []


def _saving(**fields):
    state = {"in_flight": False, "saves_seen": 0, "last_saved": "", "tracked": True}
    state.update(fields)
    return {"saving": state}


def test_wait_for_save_refuses_a_stale_save(monkeypatch):
    """Runtime behavior and validation."""
    import pytest as _pytest

    from battlemap_mcp import server
    from battlemap_mcp.errors import ValidationError

    monkeypatch.setattr(
        server.bridge,
        "request",
        lambda command, **p: _saving(
            last_result="stale", stale_path="/maps/inn.dungeondraft_map", note="serializer threw"
        ),
    )
    with _pytest.raises(ValidationError) as excinfo:
        server._wait_for_save(expected_path="/maps/inn.dungeondraft_map", saves_before=0, timeout=1)
    assert "never reported finishing" in str(excinfo.value)


def test_wait_for_save_is_not_satisfied_by_an_autosave(monkeypatch):
    """Runtime behavior and validation."""
    import pytest as _pytest

    from battlemap_mcp import server
    from battlemap_mcp.errors import ValidationError

    monkeypatch.setattr(
        server.bridge,
        "request",
        lambda command, **p: _saving(
            saves_seen=9, last_saved="user://backups/backup_1789.dungeondraft_map", is_backup=True
        ),
    )
    with _pytest.raises(ValidationError):
        server._wait_for_save(
            expected_path="/maps/inn.dungeondraft_map", saves_before=8, timeout=0.2
        )


def test_wait_for_save_refuses_an_untracked_session(monkeypatch):
    import pytest as _pytest

    from battlemap_mcp import server
    from battlemap_mcp.errors import ValidationError

    monkeypatch.setattr(
        server.bridge, "request", lambda command, **p: _saving(tracked=False, saves_seen=0)
    )
    with _pytest.raises(ValidationError) as excinfo:
        server._wait_for_save(expected_path="/maps/inn.dungeondraft_map", saves_before=0, timeout=1)
    assert "not reporting save events" in str(excinfo.value)


def test_wait_for_save_accepts_the_file_it_asked_for(monkeypatch):
    from battlemap_mcp import server

    monkeypatch.setattr(
        server.bridge,
        "request",
        lambda command, **p: _saving(saves_seen=4, last_saved="/maps/inn.dungeondraft_map"),
    )
    state = server._wait_for_save(
        expected_path="/maps/inn.dungeondraft_map", saves_before=3, timeout=1
    )
    assert state["last_saved"] == "/maps/inn.dungeondraft_map"


def test_an_unsaved_map_reports_no_path_rather_than_the_string_Null(monkeypatch):
    """Runtime behavior and validation."""
    from battlemap_mcp.server import map_file_path

    assert map_file_path({"map_file": "Null"}) == ""
    assert map_file_path({"map_file": ""}) == ""
    assert map_file_path({"map_file": "/maps/inn.dungeondraft_map"}) == "/maps/inn.dungeondraft_map"


# --- security review 2026-09-13: the copy's own filesystem safety -------------


def test_prepare_map_file_does_not_follow_a_planted_temporary_symlink(
    tmp_path, create_file_symlink_or_skip
):
    """A shared save dir lets anyone plant `<name>.preparing` in advance.

    The old code wrote that predictable name with `write_text`, which followed
    a symlink planted there and truncated its target before any rename.
    """
    from battlemap_mcp.asset_packs import prepare_map_file

    source = tmp_path / "inn.dungeondraft_map"
    source.write_text(json.dumps(a_map()))
    canary = tmp_path / "unrelated.txt"
    canary.write_text("precious")
    destination = tmp_path / "copy.dungeondraft_map"
    create_file_symlink_or_skip(tmp_path / "copy.dungeondraft_map.preparing", canary)

    prepare_map_file(source, destination, [{"id": "packB"}])

    assert canary.read_text() == "precious", "the symlink target was overwritten"
    assert not destination.is_symlink()
    assert json.loads(destination.read_text())["header"]["asset_manifest"] == [{"id": "packB"}]


def test_prepare_map_file_never_replaces_an_existing_destination(tmp_path):
    """The caller's exists() check is not atomic; the publish step must be."""
    from battlemap_mcp.asset_packs import prepare_map_file

    source = tmp_path / "inn.dungeondraft_map"
    source.write_text(json.dumps(a_map()))
    destination = tmp_path / "copy.dungeondraft_map"
    destination.write_text("appeared after the check")

    with pytest.raises(ValueError, match="already exists"):
        prepare_map_file(source, destination, [{"id": "packB"}])
    assert destination.read_text() == "appeared after the check"
    assert [p.name for p in tmp_path.iterdir() if "preparing" in p.name] == []


def test_prepare_map_file_copies_the_sources_permissions(tmp_path):
    import os
    import stat

    from battlemap_mcp.asset_packs import prepare_map_file

    if os.name == "nt":
        pytest.skip("POSIX permission bits")
    source = tmp_path / "inn.dungeondraft_map"
    source.write_text(json.dumps(a_map()))
    source.chmod(0o644)
    destination = tmp_path / "copy.dungeondraft_map"
    prepare_map_file(source, destination, [{"id": "packB"}])
    # mkstemp alone would leave 0600 and lock other users out of a shared map
    assert stat.S_IMODE(destination.stat().st_mode) == 0o644

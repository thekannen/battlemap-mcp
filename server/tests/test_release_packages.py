"""Release artifacts must contain only the intended, matching payload."""

import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def release_module():
    path = ROOT / "tools/release.py"
    assert path.is_file(), "release builder is required"
    spec = importlib.util.spec_from_file_location("release_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def checkout(tmp_path):
    for name in (
        "server/pyproject.toml",
        "server/battlemap_mcp/__init__.py",
        ".claude-plugin/plugin.json",
        "LICENSE",
    ):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    shutil.copytree(ROOT / "mod", tmp_path / "mod")
    return tmp_path


def test_version_bump_and_tag_validation(checkout):
    release = release_module()
    release.set_version(checkout, "1.2.3")
    assert release.check_versions(checkout, "v1.2.3") == "1.2.3"
    with pytest.raises(ValueError, match="tag"):
        release.check_versions(checkout, "v1.2.4")
    manifest = checkout / ".claude-plugin/plugin.json"
    data = json.loads(manifest.read_text())
    data["version"] = "1.0.0"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="version"):
        release.check_versions(checkout)


def test_mod_archive_has_exact_payload_bytes(checkout, tmp_path):
    release = release_module()
    archive = release.build_mod(checkout, tmp_path / "out", "0.2.0")
    with zipfile.ZipFile(archive) as zipped:
        assert set(zipped.namelist()) == {
            "battlemap-mcp-bridge/mcp_bridge.ddmod",
            "battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd",
            "battlemap-mcp-bridge/LICENSE",
        }
        for name in release.MOD_FILES:
            assert (
                zipped.read("battlemap-mcp-bridge/" + name)
                == (checkout / "mod/battlemap-mcp-bridge" / name).read_bytes()
            )


def test_unexpected_mod_file_rejected(checkout, tmp_path):
    release = release_module()
    (checkout / "mod/battlemap-mcp-bridge/private.log").write_text("secret")
    with pytest.raises(ValueError, match="Unexpected"):
        release.build_mod(checkout, tmp_path / "out", "0.2.0")


def test_symlink_payload_rejected(checkout, tmp_path):
    release = release_module()
    script = checkout / "mod/battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd"
    script.unlink()
    try:
        script.symlink_to(checkout / "LICENSE")
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("symlink creation not permitted")
        raise
    with pytest.raises(ValueError, match="[Ss]ymlink"):
        release.build_mod(checkout, tmp_path / "out", "0.2.0")


def test_required_manifest_missing_rejected(checkout):
    release = release_module()
    (checkout / "mod/battlemap-mcp-bridge/mcp_bridge.ddmod").unlink()
    with pytest.raises((FileNotFoundError, ValueError)):
        release.check_versions(checkout)


def test_prerelease_not_silently_normalized(checkout):
    release = release_module()
    with pytest.raises(ValueError, match="version"):
        release.set_version(checkout, "1.2.3-alpha")


def test_unexpected_skills_rejected(tmp_path):
    release = release_module()
    (tmp_path / "secrets.txt").write_text("private")
    with pytest.raises(ValueError, match="Unexpected"):
        release.validate_tree(tmp_path, release.SKILL_FILES)


def test_companion_archive_rejects_escaping_link(tmp_path):
    release = release_module()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    try:
        (bundle / "escape").symlink_to(tmp_path)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("symlink creation not permitted")
        raise
    with pytest.raises(ValueError, match="escape"):
        release.validate_companion_links(bundle)

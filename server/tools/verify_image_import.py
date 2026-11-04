"""Live embedded-image acceptance on an explicitly named disposable map.

Run --help first. Saves/reopens the scratch map and writes a VTT export.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from battlemap_mcp import server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch-name", required=True)
    parser.add_argument("--png", required=True, type=Path)
    parser.add_argument("--export", required=True, type=Path)
    args = parser.parse_args()
    status = server.bridge.request("get_status")
    path = status.get("map_file", "")
    if not path or args.scratch_name != Path(path).stem or "scratch" not in path.lower():
        parser.error("open the explicitly named, saved scratch map first")
    if args.export.exists():
        parser.error("export must be a new file")
    before = status["counts"]["objects"]
    x, y = status["map_center"]
    server.checkpoint("image-import-acceptance")
    placed = server.import_image(str(args.png.resolve()), x, y, 512, snap="none")
    node = placed["id"]
    assert placed["embedded"]
    server.move_element(node, x + 64, y, snap="none")
    server.modify_object(node, rotation=30, layer=200)
    server.undo()
    server.redo()
    server.rollback_checkpoint("image-import-acceptance")
    assert server.bridge.request("get_status")["counts"]["objects"] == before
    placed = server.import_image(str(args.png.resolve()), x, y, 512, snap="none")
    server.save_map()
    server.open_map(path)
    assert server.get_element(placed["id"])["asset"].startswith("embedded://")
    server.export_dd2vtt(str(args.export.resolve()), ppi=100)
    print("PASS: import, move, rotate, undo/redo, checkpoint rollback, save/reopen, VTT export")


if __name__ == "__main__":
    main()

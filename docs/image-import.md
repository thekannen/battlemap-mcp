# PNG import and generated prop libraries

`import_image(path, x, y, width, height=None, rotation=0, sorting=0, layer=100,
block_light=False, snap="")` places a PNG using the native ObjectTool. Coordinates
and unrotated dimensions are woxels (256 per grid square), rotation is degrees,
and x/y identify the image centre. Omitted height preserves aspect ratio. Size
includes transparent margins: use the visible alpha bounds when sizing a prop.

The image is embedded, not a trace, and exports as a normal object. The returned
id works with move, modify, duplicate, delete, undo/redo and checkpoints. PNG
alpha is retained. Embedded objects do not become searchable library entries.
A SHA-256-addressed staging file prevents the native filename cache from reusing
old pixels after a source file changes. Native map saves contain the image;
the original PNG and staging file are not required when reopening a saved map.
Staged PNGs are retained for native cache reuse and are not automatically pruned.
Import undo removes the object; the native embedded-texture cache may remain.

For a reusable, tagged library:

1. Call `create_image_pack(path, name, images, pack_id="", author="")` with a new
   absolute `.dungeondraft_pack` output file in the configured asset directory.
   Each image has an absolute PNG path, a library name, and descriptive tags.
   Pick a project/map-related pack name. A generated eight-character id is the
   default; specify one only when deliberately managing that pack's identity.
2. Call `refresh_asset_packs()` to mount newly written archives without restarting.
3. Save the map, then call `prepare_map_with_packs(new_map_name, [pack_id])`.
   This opens a copy that includes the new pack and keeps the existing selection.
4. Find its assets with `list_assets` or `search_pack_contents(searches=[...])`
   and use `place_object` normally. Tags are native Dungeondraft library tags.

The builder creates complete packs, never edits third-party packs or overwrites
files. To extend a collection, rebuild from the complete image list to a new
filename. Use a new id to avoid a restart during a live session. Dungeondraft
caches already-loaded ids; updating the same id requires restarting before its
new textures can be trusted. New packs load on map inclusion, not on rescan.
Never move or remove a mounted pack while Dungeondraft is running, even if
the current map does not include it: the engine retains archive references.
Close the editor before cleaning up test archives.
Keep the pack installed for maps containing library objects; embedded imports
are self-contained. The reserved Colorable tag is refused because it changes
how artwork renders. PNGs are capped at 32 MiB, 8192 px per side and 16 million
pixels; packs at 100 images and 256 MiB of image bytes.

## Validation

Offline regression coverage: `tests/test_image_import.py`.
Live acceptance: `python server/tools/verify_image_import.py --help`, then pass
an explicitly named saved scratch map, a PNG, and a new export path. It changes
only that scratch map. Pack discovery additionally needs a native editor check;
index-reader tests alone do not prove the root registration manifest is present.

Maintainer documentation needing a matching update: the public tool reference
and asset-pack workflow pages at https://knownframe.com/battlemap-mcp/docs/.

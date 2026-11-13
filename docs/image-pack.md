# Generated tagged asset packs

`create_image_pack(filename, name, images, pack_id="", author="")` writes a
native `.dungeondraft_pack` of named, tagged PNG objects into Dungeondraft's
configured asset folder only (Settings > Assets, or `BATTLEMAP_MCP_ASSETS_DIR`).
`filename` is a bare new pack name in that folder; existing files are never
overwritten. Publication opens the destination with `O_CREAT|O_EXCL`, so it
works on exFAT, FAT32, and network shares that do not support hard links.

Each image needs an absolute PNG path, a library name, and descriptive tags.
PNG alpha is preserved. Limits match embedded import: 32 MiB per PNG, 8192 px
per side, 16 million pixels; packs at most 100 images and 256 MiB of image
bytes. The reserved Colorable tag is refused.

## Workflow

1. Call `create_image_pack` with a project-related pack name and its images.
2. In Dungeondraft, rescan packs from the Assets window, or restart the editor.
   This companion does **not** call `Assets.UpdateTree` / `refresh_asset_packs`.
3. Save the map, then `prepare_map_with_packs(new_map_name, [pack_id])`.
4. Find assets with `list_assets` or `search_pack_contents` and `place_object`.

`search_pack_contents` can already see the new archive on disk before a rescan.
`list_asset_packs` and `prepare_map_with_packs` need the editor to have mounted
it. Prefer a new pack id during a live session; Dungeondraft caches loaded ids.
Never move or remove a mounted pack while the editor is running.

Embedded `import_image` objects stay self-contained in the map and do not join
the library. Use a pack when you need searchable, reusable library entries.

## Validation

Offline coverage: `server/tests/test_image_import.py`.

Maintainer documentation needing a matching update: the public tool reference
and asset-pack workflow pages at https://knownframe.com/battlemap-mcp/docs/.

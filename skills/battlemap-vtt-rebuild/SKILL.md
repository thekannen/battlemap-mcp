---
name: battlemap-vtt-rebuild
description: Use when rebuilding a Dungeondraft map from a Universal VTT export (.dd2vtt), a rendered image of a map with its walls, doors and lights, when the original .dungeondraft_map is missing.
---

# Rebuild a map from a Universal VTT export

A `.dd2vtt` holds a rendered image of the map plus its walls, doors and
windows, lights and ambient light. It does not record which assets, terrain,
paths or layers drew that image. `import_dd2vtt` rebuilds everything the file
does record, exactly. Everything else is reconstructed by looking: the image
becomes a trace under the map, and you rebuild the art on top of it.

**The goal is a faithful copy, not a map in the same spirit.** A plain "rebuild
my map from this file" means the result should hold up side by side with the
image at full size. Something that "looks close" in a shrunken view is not
done. Measure, identify and compare as this skill describes, without waiting
to be asked.

If the user still has the original `.dungeondraft_map`, open that instead. A
rebuild only approximates the art. Run `inspect_map_file` on it first: it
names packs the map uses that are not installed, whose art would be missing.

## 1. Preflight and packs first

Call `ping` and `get_status`. Then read the export with
`import_dd2vtt(path)`. Without `confirm` it changes nothing and reports the
region's size in `tiles`, what it would create and how many sight blockers it
found.

**Choose asset packs before importing.** A map's packs are fixed when it is
created, so a rebuild that later needs a pack starts again in a copy. Look at
the trace image, or ask the user what the map was built with. Check
Dungeondraft's own library first (`list_assets`, `preview_assets`): much
published art is built from it, and if it matches, keep the map you have and
include no packs. Otherwise run `search_pack_contents` for the distinctive
pieces you can see (a well, a fallen log, a cliff edge), and `preview_assets`
to compare candidates with the image; a pack the map lacks can still be
previewed. Then make the working map with `prepare_map_with_packs` and only
the packs the art needs.

Build on a new map. Doors mount on the nearest wall, so existing walls would
capture them.

**Decide the wall tint before importing.** Walls take their tint when drawn,
and with no `wall_color` the import uses Dungeondraft's default, a dark grey,
which turns light walls such as sandstone dark. Look at the walls in the image
and pass `wall_asset` and `wall_color` to match. Changing either afterwards
means redrawing every wall and re-adding its doors.

## 2. Import the structure, then audit it

Show the user the preview, then call
`import_dd2vtt(path, confirm=true, wall_asset=..., wall_color=...)`, adding
`resize=true` if the map is not the export's size. Walls, doors and windows,
lights and ambient light are now exact. A region export lands at the map's
origin with everything outside the region left out.

The export has no door/window field: a VTT treats `closed: true` as an
openable door and `false` as a window, so the import uses `portal_asset` for
closed portals and `window_asset` for open ones, keeping `closed` as written.
A source map that had them reversed comes in reversed.

**Audit the import before any art.** Each of these is cheap now and costly
once the art is on top:

- **Walls:** asset and tint against the image (section 3 shows how to look
  at full size).
- **Doors and windows:** compare each portal with the trace. Replace a wrong
  one by deleting it and calling `add_portal` with the right asset and no
  `closed`, then run `validate_floorplan`: its `vtt_reversed_portals` lists
  any door still open or window still closed.
- **Terrain blending:** soft, feathered ground patches in the image need
  smooth blending (`set_terrain_blending(enabled=true)`); textured blending
  draws them as hard-edged blobs. It applies to the whole level, so set it
  before painting.

`checkpoint` and save before the art pass: `rollback_checkpoint("import_dd2vtt")`
undoes the import itself, not what you build on it.

## 3. Measure at full size, never from a shrunken view

Every position, size and colour comes from the image at full resolution. A
whole-map view or a downscaled image hides the errors that matter: in one
rebuild, a crop shown at 91% made every street object about 10% too small and
shifted it sideways, unnoticed until the side-by-side.

**Capture your reference views first.** Before placing any art, set the trace
to full opacity (`set_trace_image(opacity=1)`) and take
`screenshot(rect=[x, y, w, h])` of each region, a few tiles across at most, at
the zoom you will build at. Leave out `max_px`, so each comes back at full
size. Keep the list of rects: the same rects, later, are your comparison
shots. Restore your working opacity afterwards.

**Read positions from the grid, not from pixels.** While the editor shows
its grid (`get_map_style` reports `grid_visible`), every screenshot carries
it, 256 woxels per tile, and the rect says where the view starts. So a lamp
halfway across the third column from the rect's left edge sits at
`x + 2.5 × 256`. Grid lines stay correct however the client scales the image
you see; pixel counts do not. If the grid is hidden, `set_grid(visible=true)`
shows it. If you can read the image
file itself at its native size (the `.dd2vtt`'s image, or a capture's saved
file), crop it with a labelled pixel grid and convert:
`woxels = pixels × 256 / pixels-per-grid`.

**Check the scale of what you look at.** Before trusting a measurement, check
that one grid square in the image is the same size as one on your map. If
it is not, either the image is being shown scaled, or the trace's scale is
wrong.

## 4. Rebuild the art over the trace

Work from the ground up. The export's image is your reference for taste, so
instead of the [build loop](../_shared/build-loop.md)'s region-at-a-time
dressing, you can work in whole-map passes, one kind of thing per pass,
checking each against the reference views.

1. **Ground.** Match the terrain mix you see with `fill_region` and
   `paint_terrain`. Textured ground, such as gravel, pebbles, rocky soil or
   leaf litter, is a terrain slot, not hundreds of small objects. Fill rates
   add up and a blend reads like a threshold, not a slider: raise a slot in
   small steps and look after each. A flat-coloured area with no shoreline,
   ripples or depth gradient is usually a material (`paint_material`: ice,
   mud, lava, a stone floor), not water. Real water shows a lighter shallow
   edge. **Simple Tiles laid with the tile brush cannot be repainted:** no
   tool paints that tile layer. Pattern shapes (`place_pattern`) are the
   nearest stand-in, and draw the texture at about 0.8× the brush's scale.
   Say so in your report when the image used the tile brush.
2. **Paths and edges.** Cliffs and walls of rock are often two paths stacked:
   a dark face path over a lighter lip path that shows along its edge. Draw
   both, the lip on the lower layer, when the image shows a two-tone edge.
   Without a matching pair, a single cliff path plus a shadow path offset
   toward the low side is the closest stand-in; say so in your report.
3. **Identify each asset by looking, not by its name.** Shortlist candidates
   with `list_assets` or `search_pack_contents`, then put them side by side
   on one `preview_assets` sheet and match shape, outline and colour against
   your reference view before placing any. Names mislead: `egypt_table_01`
   sounds like a counter piece but is a round table with chairs; the counter
   in that map was `bar_table`, the market stalls `tent_02` and the umbrella
   `tent_04`. A second sheet costs less than a wrong asset repeated across
   the map.
4. **Size each object from its drawn size.** Measure the object's width or
   length in the reference view (in woxels, from the grid). `list_assets`
   gives each asset's `drawn` size at scale 1, so
   `scale = measured woxels ÷ drawn woxels`. Check one with `get_element`'s
   `opaque_bounds` before placing the rest.
   **Outdoors, one scale number for the whole map** is common, often well
   above 1, and it is the NUMBER that repeats, not the size: variants of one
   asset differ in native size (one pine is four times another's pixels), and
   the original placed them all at about the same scale. Once a few measured
   variants agree, use that number for every variant rather than fitting each
   canopy separately, which splits one large tree into a cluster of small
   ones. **Interiors do not work that way:** in one shop, props ranged from
   0.3 to 1.35. Measure each kind of object there.
5. **Sight blockers.** `import_dd2vtt` returns `blockers`: each outline's
   `center`, `rotation`, `length` and `width` in woxels; `rotation` is the
   long axis's angle from +x, 0-180. Each one is a boulder, pillar or similar
   solid object. Place one on each with `place_objects` at that position,
   turned so the asset's own long side follows that axis (add 90 for art that
   is taller than it is wide), scaled so its `opaque_bounds` covers the
   outline, with `block_light: true`. These are the objects whose positions
   the export records exactly, so match them first.
6. **Everything else.** Furniture, trees and scatter, each identified and
   sized as above. Use `scatter_objects` for incidental detail rather than
   placing it piece by piece, then check its density against the reference.
7. **Colours, by number.** Tints are where "close" quietly fails: pattern
   and rug tints chosen by eye came out 10-20% too saturated. Pick a point on
   each surface (floor, walls, ground, each rug), then
   `export_map(ppi=<the export's pixels-per-grid>, grid=false)` and
   `sample_colors(points, dd2vtt=path)`: it reads the source image and your
   export at the same map points and gives `diff_rgb` (yours minus the
   source). Adjust one tint at a time and export again until `max_diff` is a
   few levels. Keep each point well inside one surface; on an edge you are
   averaging two.
8. **Layers.** Things that sit under a cliff or bridge go on low layers
   (-400 or so). Snow, canopy and overhangs go high. Check a doubtful object
   with the trace hidden.

## 5. Verify against the source: a gate, not a glance

The trace includes the original's baked lighting, so judge colour and light
without it. After each pass, and before you say you are done:

- Hide the trace (`set_trace_image(opacity=0)`) and take the same
  `screenshot(rect=...)` as each reference view, at full size. Compare each
  pair region by region: position, size, asset, colour, density.
- Also `export_map` at the export's pixels-per-grid (or a fraction of it) and
  compare it with the source image for the whole-map read. Exports leave the
  trace out.
- If a map built from the same source exists (an earlier version, a sibling
  region), `inspect_map_file(your_map, compare_to=that_map)` compares terrain
  shares, materials, paths and object scales without opening it.
- Name the differences that matter at the table: a wrong material, a missing
  blocker, an object at the wrong size or place, a tint visibly off. Fix at
  most three at a time, then compare again, as the
  [visual review](../battlemap-visual-review/SKILL.md) describes.

**Do not report the rebuild as done until every region's side-by-side holds
up at full size.** If a region cannot be brought there, it goes in your report
with the reason (section below), not into a summary that calls the map
finished.

Finish with `set_trace_image(clear=true)` before the final `save_map`. The
trace path saves with the map and is broken on anyone else's machine.

## What to tell the user

Say what came back exactly (walls, doors, lights) and what was rebuilt by eye
(the art), with the packs you used. **List everything you could not match and
why:** an asset no installed pack has, a tile-brush floor drawn as a pattern,
a surface whose colour you could not bring within a few levels. Never
quietly substitute something close.

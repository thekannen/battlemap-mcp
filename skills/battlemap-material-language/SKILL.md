---
name: battlemap-material-language
description: Use when a Dungeondraft brief needs cohesive materials, repeated visual motifs, or controlled detail instead of an asset collage.
---

# Dungeondraft material language

A map reads as one place when a small set of materials repeats with purpose. A
material vocabulary is a set of relationships, not a quota and not a ban on
variation.

## Keep the vocabulary small and working hard

Reuse selected assets where they serve the same visual role. A coherent material
language gives recurring assets several purposeful appearances; a long tail of
one-off assets can make a place feel assembled from a catalogue.

Before adding a new asset, check whether one already on the map can do the job.
If the count of distinct assets is climbing while placements stay flat, you are
building a collage.

Apply the same restraint to surfaces. Choose wall and floor materials that read
as one system, then use terrain slots — which blend rather than compete — to
add controlled variety where appropriate.

## Choose families, then search

Write these into the style bible before placing anything, then use `list_assets`
for each. Use only paths the tool returns; refine the search rather than
assuming an installed pack.

| Role | Job |
| --- | --- |
| Structural family | The shell, terrain mass, walls or floor field that frames the map. |
| Supporting family | The repeated midscale texture that gives ordinary zones their use. |
| Accent family | A high-contrast motif reserved for the focal event and thresholds. |

Name the focal event and each threshold *before* choosing the accent family, or
the accent spreads everywhere and stops being an accent.

**Look at the candidates before committing.** Filenames are not descriptions —
a bench can be stone, a "table" can be a U-shaped counter — and a family chosen
by name is a family you may have to strip out and replace after the first
render. Pass the shortlist to `preview_assets` and read the contact sheet.

This is worth doing here and nowhere else: a map commits to a handful of
families and repeats each many times, so a few sheets cover the decisions that
matter, while auditioning every prop would cost more than it saves.

Two things to read carefully on the sheet. Anything on a blue-grey ground is
colourable, and what you are seeing is its unpainted red mask rather than its
real colour — it becomes whatever `color` you pass, and flat red if you pass
none. And an asset on a plain ground still tells you nothing about how it sits
against your floor under your light; the sheet catches the gross mismatch, the
map render settles the rest.

## Look at a material; do not read its name

An asset name is a label someone typed, not a description of how the thing
renders. `terrain_dirt` sounds like the surface of a country road and renders
almost black — chosen by name for one, it read across the bottom of a map as a
band of shadow, and the mistake survived a whole revision round because the
name kept saying it was right.

`preview_assets` builds a contact sheet of candidates as one image. Use it
before committing a material or a family, and especially before committing the
one the brief's own wording points at, because that is the one that gets
adopted without looking. Two things it shows that no name does:

- **value.** A material has to hold its contrast against what surrounds it. The
  same earth tone that reads as a road against pale stone disappears against
  dark grass.
- **whether the asset is what you think.** Lit and unlit variants of the same
  fixture sit next to each other in a listing under nearly identical names, and
  colourable assets show as flat red masks rather than the colour you imagined.

## Break a large surface with material, not with props

A wide uniform floor or ground plane reads as unfinished, and the wrong repair
is to scatter objects over it — that buries circulation and leaves the surface
as flat as it was. Repair the surface itself:

- rotate the material's orientation so it stops agreeing with the grid, or run
  a second region of the same material at a different orientation
- define the space with a border or trim region of a contrasting material along
  its edges, which also makes a large room feel intentional
- lay a sub-region — a walkway, an inlay, a worn patch — with `place_pattern`
  where use would have worn or changed the surface

Each of these changes the plane rather than hiding it, and none of them competes
with the objects that carry the scene.

## Let the floor support a distinction, not create one

A change of floor material should confirm a boundary that already exists
physically — a wall, a threshold, a step, a railing, a counter. Where a hard
material change is the only thing dividing two areas, the map reads as a
coloured diagram rather than a building.

If the boundary is real, make its physical feature visible. If the two areas are
genuinely one open room, drop the hard change and separate them with a rug,
furniture, a shift in light, or a run of posts instead.

## Place with jitter, not on a grid

Repetition is what lets a small vocabulary work; jitter is what stops repetition
reading as tiling. Vary scale on most placements rather than leaving assets at
their default size, and let rotation sit off the quarter turns — furniture
squared perfectly to the walls reads as unused, while a few degrees of angle
reads as something people move around. Mirroring is a weak variation and rarely
worth reaching for.

## Check the first instance before repeating it

Scale is not normalised across assets: the same `1.0` can be a sliver of a tile
on one and several tiles on another. Benches placed at 0.9 read as pebbles
beside their own table, and the fix was 1.9 — applied to eight of them after
the fact.

A contact sheet cannot catch this. It shows the art, not the size against your
room, and a tint judged on a plain ground shifts once your own lighting is on
it.

So place the first instance of a family, frame it with the furniture it belongs
to, and look. Confirm it reads at the size you meant and that any `modulate`
still holds under the map's ambient. Only then repeat it. Checking costs one
screenshot; not checking costs re-placing every instance.

## Know the footprint before you position it

Asset sizes are not normalised and cannot be estimated by eye. A bar counter
was guessed at half a tile, then three tiles; it is nearly **five**. Placing a
second one beside it produced near-total overlap rather than a longer bar.

`fit_elements` with a single id returns that element's real bounds. Use it on
the first instance of anything large — a hearth, a counter, a bed — before
deciding where it goes, and position from the measured edge rather than from
the centre and a guess.

Two things that measurement then tells you:

- **One piece may already be the whole fixture.** A counter that is five tiles
  wide is the entire bar, service enclosure included. Repeating a fixture is
  not how you make a longer one; it is how you make a mangled one.
- **The bounds ignore rotation.** They describe the unrotated box, so a rotated
  asset reports a footprint with its width and height the wrong way round. Swap
  them yourself for anything you have turned.

### Measure the space it has to sit in, too

Knowing an asset's footprint only answers half the question. The other half is
the gap it is going in, and the two have to be compared before anything is
placed. Four oaks went around a building on a map whose exterior band was three
tiles wide; the tree measured 5.7 tiles across, so every one of them covered the
rooms it was supposed to frame.

So read the space in the same units: an exterior band is `map_size_woxels` minus
the building's extent, a room is the gap between its walls, an alcove is the gap
between its neighbours. If the asset does not fit, scale it down or pick a
smaller one — do not place it and hope the overlap reads as depth.

## Let walls sit down in value

To create depth, consider tinting walls below the texture's full value. Choose
warmth to suit the scene and verify that the wall still supports the intended
focus.

## Verify cohesion

Call `get_composition_snapshot`, then inspect a whole-map `export_map` and a
focused `screenshot`. The snapshot locates where each kind has spread; it does
not judge beauty. In the render, ask whether the structural family frames the
scene, the supporting family explains its zones, and the accent family still
points at the focal event.

If a new family competes with the focal event, remove it or `undo` it before
adding another detail. Hand the result to
[composition audit](../battlemap-composition-audit/SKILL.md) for the
two-scale decision.

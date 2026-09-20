---
name: battlemap-composition-audit
description: Use when a nearly built Dungeondraft map needs a whole-map composition check before final polish, especially when hierarchy, routes, focus, or density may be unclear.
---

# Dungeondraft composition audit

Judge the map that exists, at two scales, before changing it. More decoration is
not a repair.

## Use quiet space deliberately

Make quiet ground an intentional part of the composition. Let decorated pockets
contrast with counterspace when that helps a focal event, route, or encounter
area read clearly.

Evenly spread decoration can obscure hierarchy. When a room or region reads as
underdressed, first check whether existing detail should be concentrated or
quiet ground restored before adding more.

## Scale detail with zones, not canvas size

A larger canvas does not automatically need proportionally more decoration.
Extend counterspace and, where the brief supports it, add a zone with its own
purpose rather than scaling every existing cluster up with the canvas.

Avoid making every area equally busy; give each added zone a distinct visual and
play purpose.

## Counts are not coverage

Element counts cover objects, walls, lights, paths, portals, roofs and texts.
They do **not** cover floors, tiles, terrain, water or caves — those are layers,
not elements. A map reporting every count at zero can still be carpeted in
leftover tiling, so read `layers` in `get_status` before concluding that a
canvas is blank or that a region is bare.

## Capture the evidence

1. Call `get_composition_snapshot`, then `fit_elements` and `export_map` for the
   whole-map read. Compare per-kind occupied cells and bounds against the
   render: use it to notice uneven coverage or a missing structural layer. It
   is a factual inventory, not a score and not a target distribution. Check
   focal event, zone hierarchy, coverage, route, barriers, openings and light
   hierarchy together.
2. Frame the primary interaction with `set_camera` and take an encounter-scale
   `screenshot`. Check token movement, cover, entrances, hazards and local
   material transitions.
3. Record an audit card: dominant zone, supporting zones, quiet space, route
   state, focal cue, density contrast, and the single most visible defect at
   each scale. Describe observed locations, not an abstract score.

## Choose the repair scale

| Evidence | Repair |
| --- | --- |
| Whole-map hierarchy or coverage is unclear | Change a macro mass, route edge or zone emphasis before adding accents. |
| Decoration reads as evenly spread | Take detail *out* of counterspace rather than adding emphasis elsewhere. |
| A surface reads as flat or monotonous | Repair the surface's material or orientation, not the objects standing on it. |
| Encounter-scale use is unclear | Repair circulation, interaction markers, cover or a local depth transition. |
| Both views support the brief | Stop. Do not decorate merely to make the map busier. |

Make at most three repairs. Each names its location, the observed defect and the
intended tool action. Use `undo` when a repair weakens route, focus or
playability.

## Two checks before you finish

Both are cheap, and both fail loudly instead of inviting taste.

**Imagine every floor is the same material.** Re-read the whole-map export as if
every surface used one material. Can you still tell where each functional area
begins and ends? If the plan only holds together because of contrasting floor
textures, the architecture and furniture are not doing the work — add the wall,
threshold, level change or furniture that should have carried the distinction.

**Describe each area without labels.** From the render alone, say what every
major space is for. If you catch yourself hedging — "probably a kitchen", "this
appears to be storage" — that space's semantics are too weak. Strengthen its
anchor and its supporting objects before finishing.

## Verify the result

Recreate the same view after each repair and capture a `screenshot`; recapture
the whole-map `export_map` after a macro change. Finish only when both scales
support the brief and what remains is a user-controlled preference.

Hand the map to [visual review](../battlemap-visual-review/SKILL.md) for its
final, bounded repair pass.

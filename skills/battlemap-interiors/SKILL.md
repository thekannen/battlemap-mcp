---
name: battlemap-interiors
description: Use when furnishing a Dungeondraft room, tavern, dungeon chamber, shrine, workshop, or other interior scene.
---

# Dungeondraft interiors

An interior reads as a place when its room purpose explains its circulation,
focal point and furniture cluster. Build that hierarchy before incidental props.
Follow the shared [build loop](../_shared/build-loop.md) so the room receives
macro, cluster and accent reviews rather than a single late polish pass.

## Establish the room

Set a [material language](../battlemap-material-language/SKILL.md) before
selecting floors, walls, furniture, and lights so rooms share a visual system
without making every room equally accented.

1. State the room purpose and the action it supports: dining, defense, ritual,
   rest, storage, trade or passage.
2. Map circulation from each doorway to the focal point. Keep token-scale
   movement clear and reserve intentional open floor where the encounter needs it.
3. Use `list_assets` for architecture, furniture and props that support that
   purpose. Place large architecture and the focal furniture cluster before
   secondary dressing.
4. Add use-wear and an edge treatment where floor, wall, rug, shelf, shadow or
   debris meets. These transitions create depth without obscuring the route.
   Give each variation a visible cause: concentrate wear along circulation,
   spills or tools near their use, and weathering at exposed edges. Keep these
   marks irregular and subordinate to play space rather than distributing the
   same treatment across the entire room.
5. Give anything that rests on something else its layer *as you place it*.
   Pass `layer` to `place_object` or `scatter_objects` — a layer VALUE, a
   multiple of 100. Build upward: the surface on one layer, what stands on it a
   layer above. A pattern floor placed through this bridge takes an ABSOLUTE
   layer, -100 by default — below objects, which default to 100 — so an object
   on the default layer already sits above its floor. Do not carry over a
   remembered number: `place_pattern` returns the `z_index` it used and
   `get_element` reports each element's `layer`, so read both back and stack
   from what they actually say. Within a single
   layer `sorting` only reorders siblings and cannot lift a cup above its
   table. The response reports the layer the object actually landed on — read
   it back rather than assuming it took.
6. Mask wall junctions. Where walls meet at a corner or a T-junction the join
   reads as an editing seam rather than construction. A post, pillar or column
   set over the join, on a layer above the walls, turns the seam into structure
   — `get_tool_layer` reports which layers are available.

## Compose in functional clusters

Before hand-composing a common unit, check `list_prefabs`. Place one suitable
candidate with an explicit `x`/`y` centre and optional rotation. Inspect
`placement.skipped`, its reasons in `placement.unsupported`, and a screenshot
of the footprint before repeating it. Keep the returned ids together:
`move_elements` translates and optionally rotates them in one undo step.
Include a mounted door's wall in that group; the door follows it automatically
and duplicate ids move only once. Text anchors move but labels stay upright.
Use hand-composition for unique anchors or when no prefab fits. Do not promise
unattended prefab saving: the native Make Prefab action prompts the user.

Furniture placed by picking coordinates inside the room's rectangle reads as
props in a box, however much you vary the rotations. Build each zone outward
from one thing instead:

1. **Name the anchor** — the hearth, the counter, the prep bench, the shelving
   run. It is the reason the zone exists. Place it first, against the
   architecture it belongs to.
2. **Add the supporting pieces** — the seating that faces a hearth, the stools and
   casks that make a counter a bar, the sacks and crates that make shelving a
   store. Position each piece relative to the anchor, not to the room's bounds.
3. **Give the cluster its own light** and keep its approach open.
4. **Add incidental detail last**, and only where it explains the use.

A zone is finished when someone can say what happens there without being told.
If it needs a caption, the anchor is not carrying enough support.

**A building that stops at its own walls reads as a cutout.** Unless the brief
is explicitly an interior-only map, give it the ground it stands on and a few
tiles of the world outside: the approach, a yard, a neighbour's wall, the road
it faces. A tavern floating on blank canvas is the first thing a viewer
notices, before any of the furnishing inside it. The
[environments](../battlemap-environments/SKILL.md) skill covers siting a
building.

**Give the walls depth.** A thin shadow path run along the inside of each
wall, and under a gallery or a bar's overhang, lifts a room off the page; find
one with `list_assets(category='Paths', search='shadow')`. Keep it narrow and
continuous rather than a strip of dark paint.

**Leave fixtures square and vary everything else.** A bed, a shelf run or a
counter belongs squared to its wall. Chairs, stools, tableware, sacks and
crates do not: give each a slightly different scale (about 0.85-1.15) and a few
degrees of turn. A room at exactly 1.0 and quarter turns reads as a showroom
rather than a place in use. Set the variation in the placing call, not in a
repair pass afterwards.

## Use the walls

Real interiors lean on their edges. Benches sit against walls, shelving and
cabinets line them, tables gather near windows, storage backs onto service
walls. Furniture that is all freestanding in the middle of the floor reads as
dropped in, and it eats the circulation while leaving the edges dead.

Keep enough central furniture to make the space usable, but treat a room with
nothing against its walls as unfinished.

## Check the wall before you place against it

A wall is rarely empty. It carries windows, doors, and whatever fixture went in
before this one, and none of that is visible from the object you are holding.
Three placement failures in one build shared exactly this cause: a hearth
pushed clean through an exterior wall, a counter overlapped with its own
neighbour, and a window buried behind a chimney breast.

So before committing anything large to a wall, list what is already on that
wall — `list_elements` for portals and objects — and pick a clear stretch. Then
run `validate_placements`, which reports objects crossing a wall and objects
standing in a doorway or across a window. It will not complain about a tankard
resting on a table: objects overlapping each other is how stacking works, and
only structural intrusion is a defect.

It measures the real, rotated footprint. Do not try to do this check yourself
from `fit_elements` bounds — those ignore rotation, so a hearth turned -90
degrees reports a 714-wide box for a 350-wide footprint and every rotated
object on the map reads as a defect.

## Make the fixture work for whoever uses it

Furniture that could not be operated reads as scenery. A bar needs a side the
server stands on and a way in behind it. A hearth that is the room's focal
point needs visible fire, or it is a cold stone recess that happens to be large.

**A directional fixture has a facing, and rotation 0 is not neutral.** A wall
torch is drawn as a bracket with the flame projecting to one side, because it
mounts on a wall and throws light into the room. Unrotated on a south wall that
projection points outward: the sconce hangs through the wall and lights the
street instead of the hall it was placed to light. The same is true of anything
with a front — a bar's serving side, a stove's mouth, a bed's head, a cart's
bed. Decide which way the fixture faces from what it serves, then set the
rotation to match; a fixture facing the wrong way is a defect that no footprint
check can see, because the geometry is fine.

**Dungeondraft draws a fixture facing DOWN at rotation 0.** Checked across the
wall-furniture families at rotation 0: a hearth's mouth, a throne's seat, a
desk's drawers and a wall torch's flame all point to the bottom of the sprite,
with the back at the top. So a piece whose back belongs against a wall takes its
rotation from the wall it stands on:

| The wall its back is against | rotation |
| --- | --- |
| North (wall above it) | 0 |
| East | 90 |
| South | 180 |
| West | 270 |

Left unrotated on a south wall, a bookshelf therefore has its back to the room
and its books to the wall — which is how a tavern ended up with every shelf
facing the partition it stood against. Being flush matters as much as facing:
seat the back edge ON the wall line, half the asset's depth away from it, or the
piece reads as drifting into the room.

`preview_assets` renders every candidate at rotation 0, so what sits at the
bottom of the cell is what will face the room when you place it unrotated.

The asset's **silhouette** tells you where it was drawn to go. A hearth with a
semicircular mouth was made for a curved nook and will leave an awkward crescent
of floor against a straight wall; a rectangular one sits flush. Either choose
the shape that suits the architecture you have, or build the architecture the
shape wants — but do not force a fixture into a wall it was never drawn for.

## Light and review

Use the [lighting hierarchy](../battlemap-lighting-hierarchy/SKILL.md) with
`add_light` to reveal the focal point, guide circulation and let secondary
areas fall quieter rather than making every area equally bright. Treat
incidental scatter as background texture, never as the room’s main story.
Treat doors, barriers and lights as one route system: each should confirm how
a player enters, moves through and reads the room.

Create a shell checkpoint, then a dressing checkpoint with `save_map`. Capture
a `screenshot` at player view, then run the
[composition audit](../battlemap-composition-audit/SKILL.md) before final
review; correct only visible issues in circulation, focus, depth or playability.

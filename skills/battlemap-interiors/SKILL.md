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

   What stands on a surface also stays INSIDE it: the surface's layer plus
   100, a scale chosen against the surface's measured footprint, and every
   edge within the surface's edge. A book pile wider than its table, a board
   over the table's lip, a candle off the corner of a desk and a tap past the
   end of its tub all read as careless at token zoom. Table-top things stand
   on tables; a table candelabra on the floor is a misplacement, not a choice.
   `validate_placements` lists what reaches past its surface under
   `surface_overflow`.
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

**Every piece has an anchor of its own, and its purpose says where.** A bed's
head goes to a wall; a desk faces into the room with its chair in front of it;
a mirror stands by the dressing table; an instrument sits beside a seat in a
corner; a sink goes on a wall clear of the doors. A lute in the middle of a
corridor, a dress form mid-floor, or a bed on a rug in the centre of the room
with its headboard against nothing reads as dropped. A piece you cannot give
an anchor is a candidate for removal, not for the middle of the floor.

**Seating around a table is a set, not a scatter.** Measure the table with
`get_element` on its id (`bounds`, after its turn and scale), then derive the chairs from its edges: evenly spaced
along each long side, the head chairs centred on the ends, one scale for the
whole set, and one place setting in front of each chair. Chairs placed at
"about" the edge come out uneven in spacing and in size, and a long table
shows it at once. Keep the variation small here: a degree or two of turn, not
a different size per chair.

**A lived-in room is furnished in layers.** Write each room's layers into the
plan and check each is present before calling the room done:

1. the anchor furniture
2. secondary seating, side tables and storage
3. surface dressing: cups, candles, books, tools at their work
4. wall dressing: portraits, shelves, mirrors, hangings

How deep each layer goes follows the room's emphasis and the household: a
wealthy home's rooms with only the first layer read as empty, while a servant's
room or a storeroom stops sooner on purpose.

## Some fixtures are kits

Some packs draw one piece of furniture as several assets meant to be stacked,
and a part placed alone reads as broken: bedding with no bed under it looks
like a comforter on the floor, a hearth slab with no chimney breast is a pale
block off the wall, a curtain without its rod renders as a squiggle. When a
folder or file name says Blankets, Base, Chimney, Frame, Ring, Brace, Cloth,
Rod or Fill, search for its siblings with `list_assets` before placing it, and
place the kit together, each part a layer above the one it rests on.

| Part on its own | Needs |
| --- | --- |
| Bed blankets or bedding | the bed frame of the same size underneath |
| Fireplace base (the hearth slab) | the chimney piece (breast and mantel) above it, and a fire in it |
| Globe sphere or ring | the brace or stand it turns in |
| Window frame | the sill or glass piece, or it renders as an empty frame |
| Curtain cloth | the rod it hangs from, on the wall |
| Door frame | it has no leaves; the door itself is an `add_portal` |

Look at the first assembled kit in a screenshot before repeating it, and check
that the parts line up and face the same way. `validate_placements` lists a
part placed without its sibling under `lone_kit_parts`.

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
repair pass afterwards. Vary the variant as well: where a family offers A1, A2
and B1, use several. A row of identical candles or bushes reads as stamped
however differently each is turned.

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
facing the partition it stood against. A bench works the same way: its
backrest is at the top of the sprite, so against a north wall it takes 0, and
180 turns it to face the wall.

**This is the usual drawing, not a law, so check each family once.** Place
the first instance of every wall-facing family, frame it, and look at which
way it faces before placing the rest. Known exceptions:

| Family | At rotation 0 | So |
| --- | --- | --- |
| Rectangular fireplace base and chimney pieces in some painterly packs | drawn side-on | a quarter turn off the table above: on a north wall, 90 rather than 0 |

Add to this list as you find others; a wrong facing passes every footprint
check.

**Hug the wall; do not approach it.** Being flush matters as much as facing.
Compute the position from the wall's own coordinate, not from "near the
wall": the wall line plus or minus half the asset's depth along the wall's
normal, with the depth from `texture_size` times scale. Portraits, rails,
benches, banners and lanterns half a tile out read as floating. Then read
`adrift_fixtures` in `validate_placements`, which reports wall fixtures —
torches, hangings, curtains, chimneys, windows and `Wall_` pieces — standing
off every wall.

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

---
name: battlemap-environments
description: Use when building an outdoor Dungeondraft scene such as a forest, shoreline, trail, ruin exterior, or open encounter map.
---

# Dungeondraft environments

**Scale vegetation from its texture size before you scatter it.** Asset
footprints vary enormously and nothing warns you. A tree texture may be a few
hundred pixels or several thousand, and at 256 woxels per tile that is the
difference between a shrub two tiles wide and a canopy nine tiles wide — wider
than a small building. Scattered at whatever scale looks reasonable, the large
ones stop reading as trees in a forest and become a lid over the map; their
shadows fall as broad dark bands that get mistaken for terrain, and bare trunks
stick out from under them with no crown in sight.

Never assume a family shares a size, and never carry a number over from another
map: read `texture_size` from `list_assets` or `get_element` for the assets you
actually chose, decide how many TILES the thing should occupy, and set the
scale from that:

    scale = desired_tiles * 256 / texture_px

Say the intended canopy size in tiles when you plan a treeline. A tree larger
than the building beside it is a composition error, not a detail.

Make the land readable before making it busy. Terrain layering, a dominant
silhouette and a clear route should survive a whole-map view before incidental
detail is added. Follow the shared [build loop](../_shared/build-loop.md) so
macro masses, clusters and accents each receive a visual checkpoint.

## Compose the ground

Set a [material language](../battlemap-material-language/SKILL.md) before
choosing terrain, water, vegetation, or landmark assets so the scene has a
deliberate field, supporting texture, and focal contrast.

Set a [lighting hierarchy](../battlemap-lighting-hierarchy/SKILL.md) before
adding sources so weather, route choices, and the landmark use darkness and
contrast deliberately.

1. Use `list_assets` to find only the terrain, water, vegetation and landmark
   families that fit the style bible.
2. Establish terrain layering with broad ground regions first. Treat water and
   terrain transitions as compositional edges, not as decorative afterthoughts.
   At a water or material boundary, make a transition band rather than tracing
   the outline exactly: use `paint_terrain` in a supporting terrain slot with
   uneven, overlapping soft strokes, vary its width, then interrupt parts of it
   with the base terrain. Use `get_terrain` on each side of the boundary and a
   screenshot to confirm deliberate material variation without obscuring the
   intended water edge.
3. Place the largest silhouette next: a treeline mass, rock formation, ruin,
   cliff or water body that frames the focal event.
4. Shape each route to lead to, through or around the focal event. Keep token
   movement and sight lines legible; use negative space as intentional breathing
   room rather than filling every surface.

## A building has a site, not a margin

When the map contains a structure, the outside is not the space left over once
the walls are up. It is where the building *is*, and treating it as a border to
decorate is what makes a finished interior sit in a void — every count correct,
every asset placed, and nothing around it that explains why anything is there.

Before dressing the exterior, answer three things and build the answers:

1. **How do people reach it?** A road, a track, a river landing, a mountain
   path. It should enter at one map edge and leave at another, so the building
   sits *on* a route rather than at the end of one that exists only for it.
2. **Where do they arrive?** Find the exterior doors and read what they are
   for. The main entrance wants an approach and somewhere to stand — a
   forecourt, a porch, a yard. That is also where arrival-related props belong:
   a trough where riders stop, a sign facing the road.
3. **Where does the work happen?** Most buildings have a public side and a
   working one. A service door wants a yard, and the yard wants the things its
   work needs — a well, a cart, fuel, stores — connected back to the route.

Then let the ground record the use. Bare earth where feet and wheels go, worn
grass at the edges of it, unbroken ground where nobody walks. Ground that shows
where people move does more for believability than any amount of scattered
detail, and it is what makes the difference between a building on a map and a
building in a place.

Work the exterior before the interior when you can: the site decides where the
doors matter, and a door that turns out to face nothing is expensive to move
once the rooms behind it are furnished.

## Blend ground edges, and know which edge can never blend

A path laid as a floor PATTERN cannot blend into anything. A pattern sits above
the terrain, so its border stays a dead straight cut however much you paint
beside it — measured, by painting soft grass strokes across a pattern path's
edge and seeing none of it arrive. Keep patterns for floors under a roof, and
make outdoor ground — paths, yards, tracks — out of TERRAIN, which does blend.

Then there is the trap that makes blending look impossible. Slot 0 is the base
and is NOT paintable: `paint_terrain(slot=0)` is accepted and changes nothing.
So if `fill_terrain` put grass in slot 0, you cannot paint grass back over a
path's edge. Assign grass to a paintable slot as well (slot 2, say), and paint
THAT along the edge — a soft brush, `rate` around 0.8, strokes of uneven length
and depth. The result is grass reaching into the path in an irregular line,
which is what a real verge looks like.

`path_blender_01` to `04`, in the Paths category, exist for exactly this: drawn
along a seam they feather one material into the next. Use one where two grounds
meet and the join still reads as a line someone drew.

## Caves are carved, not built

A cave is not a room with rocky walls. `dig_cave` takes a POLYLINE and a radius
and opens the rock along it, so you shape a cave the way water would: a passage
that wanders, chambers where it widens, dead ends that go nowhere. A cave drawn
as a rectangle reads as a basement.

- **Dig the route first, then widen.** One stroke along the whole path at a
  small radius, then second passes with a larger radius where you want a
  chamber. Digging chamber-by-chamber leaves them connected by nothing.
- **A single point is a chamber.** `points` with one pair digs one circular
  space — that is the documented behaviour and the way to place a rotunda or a
  pocket off a passage.
- **Set the rock's colours with the dig**, not after: `ground_color` and
  `wall_color` on the same call, plus `texture` for the cave floor. They decide
  whether it reads as limestone, basalt or packed earth.
- **Connect it to the outside deliberately.** A cave mouth is where the carved
  rock meets open ground, and it only reads as an entrance if the ground
  outside leads to it — a path, worn terrain, or a widening of the passage as
  it reaches daylight. After digging the route, use `set_cave_entrance` at its
  border to blast a circular opening through the rocky edge. The mask removes
  border art without carving floor; set its `open` argument to false to
  restore the edge. `get_cave` reports floor and entrance cell counts and the
  actual ground/wall colours. Confirm the floor count stays unchanged, then
  frame the mouth in a screenshot to verify a usable approach. A mask away
  from an existing cave border may produce no visible opening.
- **`dig=False` fills rock back in.** That is how to take back an over-wide
  chamber; there is no delete for carved rock. The parameter is `dig`, not
  `erase` — an unknown argument is dropped silently at the tool boundary, so
  naming the wrong one digs MORE rock rather than failing.

Check it with an `export_map`: a cave's shape is the thing being judged, and
element counts say nothing about it at all. Blend the approach with terrain
and sparse material detail after the route and entrance read clearly. Cave
undo retains both bitmaps; select the original level before undoing, and do
not try to restore cave history across a map resize.

## A crossing is one span, and water has to read as water

A bridge is a single continuous span, or deliberately overlapping segments. Two
placed end to end leave a visible seam down the middle at map zoom, and a
reviewer reads that as one bridge that failed rather than two that met.

Check the span against the water, not against the gap you imagined: place it,
then look. A crossing that stops short of either bank is worse than no bridge,
because it says the map was never examined.

And confirm the water READS as water in a render. Under a dark ambient, a
water body can come back as a grey-green band indistinguishable from shadowed
ground — one map's central river was mistaken for a tree's shadow by the person
reviewing it, and the bridge appeared to cross nothing. `get_status` reporting
`layers.water: true` only means water exists somewhere; it says nothing about
whether a viewer can tell.

## Nothing grows on a map by itself

An exterior can pass every structural check and still look like mown municipal
lawn, because being correct and being alive are different problems. Every
installation carries far more ground cover than a build usually reaches for —
grasses, fallen leaves and branches, roots, shrubs, vines, ferns, flowers,
mushrooms, thorns. Find out what THIS map can use rather than assuming: search
`list_assets` for each family in turn. What exists depends on the Dungeondraft
version and on which packs the map includes, so a list memorised from another
map will be wrong somewhere.

- **Plants grow where feet and wheels do not.** Against walls, in corners, along
  fences, at the foot of anything that stands still, and at the edges of paths —
  not scattered evenly across open ground.
- **Wear goes where they do.** Bare earth at a door, a gate, a trough, a
  well; grass thinning to dirt where a track is actually walked.
- **Clusters, not confetti.** Three clusters of five read as growth; fifteen
  singles spread evenly read as a texture someone applied.
- **Give the ground evidence of a life.** A woodpile, a barrow, crates by a
  door, washing, a cart with its shafts down. One or two of these say more about
  who lives here than another dozen shrubs.

A quiet zone is sparse, not sterile: it still gets tufts and litter, just fewer,
smaller, and further apart.

## Detail by zone

Cluster foliage, debris and cover according to the zone’s purpose. Contrast
quiet approaches with active encounter areas and use controlled asymmetry so
the composition reads as natural without becoming visually noisy. Preserve real
walls, portals and lights wherever the requested map needs VTT behavior.
Make barriers, openings and lights reinforce the intended route and focal
hierarchy instead of treating them as isolated decoration.

Group vegetation and debris into clusters of a few, with varied scale and some
ground texture beneath them. Isolated shrubs at regular intervals read as
stamped however few there are — and a large `min_gap` in `scatter_objects`
produces exactly that, because it enforces even spacing. To make a region
sparse, place *fewer clusters* rather than the same count spread evenly: keep
`min_gap` small inside a cluster and leave real ground between clusters.

Capture a `screenshot` at encounter scale and use `export_map` for the
whole-map check. Run the
[composition audit](../battlemap-composition-audit/SKILL.md) before final
review. Repair only a visible defect in hierarchy, routes, water edges or
coverage; then capture again before finishing.

# Build loop

Finish the map a region at a time. Sweeping the whole map once for structure,
again for clusters and again for accents spreads attention across everything and
finishes nothing — each pass leaves every region partly done, and the detail
that makes a room feel built is what gets lost. Build the foundation globally,
then complete one region at a time and do not come back to it.

## 1. Preflight and plan

Call `ping`, then `get_status`; stop and explain a failed preflight.

**Check which asset packs this map includes.** Call `list_asset_packs`. Packs
are scoped per MAP, not per installation: the map carries the list, and it is
fixed when the map is created. A map created without them sees only the stock
library no matter how many packs are installed, so `list_assets` looks complete
while most of what the user has is invisible. The difference can be two orders
of magnitude, and nothing about the response says so — compare
`get_status.asset_packs.included` against `installed`.

If `installed_but_not_in_this_map` is non-empty, say so BEFORE you build. A map
cannot gain packs after the fact; `prepare_map_with_packs` writes a fresh copy
that includes the ones you choose, and switching later means rebuilding
everything already placed.

**Choose packs by subject; do not take all of them.** `prepare_map_with_packs`
requires an explicit list, because including everything is not free. Packs vary
enormously in size: one large pack can hold more assets than every other pack
combined, and gigabytes of it may have nothing to do with the map you were
asked for. Each entry from `list_asset_packs` reports `name`, `version` and
`author` — pick the ones whose subject matches the brief, a forest pack for a
forest, a furniture pack for an interior, and say which you chose and why.

**An asset from a pack this map lacks is refused, not silently lost.**
`list_assets` offers only what the map can actually keep and reports
`hidden_unusable` beside it; reach for one anyway and the bridge refuses and
names the pack. `preview_assets` is deliberately exempt, so a pack's contents
can still be looked at while deciding whether to include it.

**Ask before you build, in one round.** A brief that leaves a real design
decision open does not get better by guessing: the map gets built, shown, and
built again. Before planning, look for decisions that change WHAT you make
rather than how you decorate it — the setting and era, what the map is for
(battle map, exploration, illustration), its size and scale, the time of day and
its light, the focal event, whether a structure is a building, a ruin or a
cavern.

**Say which way you went.** State either the questions you are asking or, in
one line, that the brief settles everything and why. A session given a brief
written to need two or three questions asked none and went straight to
building (#86) — a rule that is never visibly exercised is indistinguishable
from a rule that is not there, both to the user and to the next review.

Put those to the user directly, as one round of at most five questions with
concrete options, and then build. Scale it to the brief: a detailed brief needs
none, and manufacturing questions to look thorough wastes a turn; a one-line
brief ("make me a tavern") usually needs four or five. Ask only what you cannot
decide — never which table asset to use, and never anything the style bible
exists for you to settle. Do not drip-feed more questions mid-build; this round
is what prevents that.

**Choose the tools before you choose the assets.** Dungeondraft has several
systems that produce a similar-looking result by different means, and picking
by appearance alone leads to a map assembled from whatever was discovered
first. Decide each of these explicitly, and say which you chose:

1. **Structure** — `generate_dungeon` for a dungeon, `dig_cave` for a cavern,
   `build_room` for a walled building, or open terrain with no structure at all.
   Decide the map size, how many levels, and whether roofs are part of the
   deliverable, now rather than later. **Size the map to the scene**: a small
   building in the middle of a mostly empty canvas reads as unfinished at play
   scale. Either plan surroundings out to the edges, or set the size first —
   `set_map_size` (8 to 128 tiles a side) keeps the top-left origin and does
   not move what is placed, so shrinking it afterwards cuts into a centred build.
2. **Surfaces** — a terrain slot for ground that must BLEND, `place_pattern`
   for a tiled floor, `draw_path`/`paint_path` for a trail, fence line or
   shadow strip, `add_water` for actual water. Plan the line work too: a
   shadow path along the inside of walls and under overhangs, and an ink line
   where an edge needs definition — a dais, a cliff lip, a pit. Find them with
   `list_assets(category='Paths', search='shadow')` and `search='line'`; a map
   with no line work reads flat. Name the tool, not just the
   look: they are different systems and cannot be converted into one another
   afterwards.
3. **Repeated units** — check `list_prefabs` before hand-composing anything
   that recurs (a table setting, a stall, a workstation). Place one, inspect
   what it actually produced, then reuse it. Hand-compose the unique anchors.
4. **Architecture finish** — where posts, where portals, which layers. See
   phase 3.
5. **Delivery** — labels, grid, and whether the user wants a player-facing
   version, a GM version, or a VTT export. Ask in phase 1 if the brief is
   silent and it would change what you build.

Fold every answer into the style bible before placing anything. Complete
the [style bible](style-bible.md), set the
[material language](../battlemap-material-language/SKILL.md) and
[lighting hierarchy](../battlemap-lighting-hierarchy/SKILL.md), then use
`list_assets` for each asset family. Place nothing until the plan is coherent.

## 2. Lay the foundation

Get a whole layout down in as few operations as possible.

- For a dungeon or cavern, let `generate_dungeon` (or `dig_cave` along a path)
  produce the layout instead of hand-placing walls. Set the numeric dials with
  `generator_options` first, and pass `floor`/`wall` to `generate_dungeon`
  itself — enabling the generator discards pickers set beforehand.
- Otherwise build the shell directly: `fill_terrain` for the ground field, then
  `build_room` for each structure.
- Set the ambient condition now with `set_ambient_light`. Every region you judge
  from here is judged under it, so choosing it late invalidates the screenshots
  you already accepted.

Checkpoint with `save_map` and read the whole map with `export_map`.

**A second floor is a plan, not an afterthought.** If the brief needs one,
decide before building: `add_level` creates it, and every level shares the map's
COORDINATES, so a staircase at (x, y) downstairs must be at (x, y) upstairs or
the two floors do not line up. Walls, terrain and objects all belong to one
level.

- `set_level(id)` takes an ID from `list_levels`, not a position — those are
  different numbers and the engine stores positions.
- Build and verify one level at a time. `get_status` and every validator
  describe the CURRENT level only, so a clean report says nothing about the
  other floor.
- Undo is per-level: a terrain undo restores the level it was taken from, and a
  cave undo refuses outright when a different level is selected, so switch back
  before undoing.
- Decide what you deliver. A two-floor building usually wants a render per
  level, and a roof hides the top floor in any render that includes it.

**A roof is a ridge line and a width, not an outline.** `add_roof` takes the
line the ridge runs along, and the roof spreads `width` either side of it — so a
building 8 tiles deep wants a ridge down its middle and a width that reaches
its walls, not a rectangle around it. Set `sunlight` with a single `sun_angle`
for every roof on the map: two buildings lit from different directions read as
a mistake before anyone can say why.

## 3. Correct the foundation

Fix what generation got wrong and finish the structure: wall runs, floor and
terrain regions, then doors and windows with `add_portal`. Decide each portal's
VTT behaviour as you place it.

This is the last phase that changes the shell. Later phases dress the map; they
do not rebuild it.

**Prefer one continuous polyline for a wall run.** Existing open runs can be
joined with `merge_walls(ids=[survivor, absorbed])` when they share an endpoint
and have matching styles. Straight runs and corners work for automatic and
manual walls. The first wall ID survives; doors/windows keep their IDs and
positions, and one undo restores both walls and their original attachments.
Inspect the returned IDs before further edits.

T-junctions, loops, cave walls, overlaps, crossings and mismatched materials
are outside this operation's envelope. Inspect those junctions visually. Use a
post (`pillar_wood`, `pillar_stone`) only where a visible seam needs covering
and the post makes architectural sense; place it above the walls. Do not add
posts automatically to every junction or corner.

**Objects only draw over a wall from layer 700 up.** Measured, one post per
layer against the same wall: 600 and below vanish underneath it, 700, 800 and
900 sit on top. The default object layer is 100, so a cap placed without a
`layer` is swallowed by the very wall it was meant to finish — which is what
happened to a tavern's corner posts. Anything meant to read as sitting on or
over a wall — posts, beams, a sign, a bracket — needs `layer=700` or higher.

**A door's opening is `radius`; its art is a fixed size. Match the two.** Draw
the wall unbroken and call `add_portal` on it — the portal cuts its own gap, 2 x
`radius` wide. But the door art never grows beyond its natural size, one tile
for the vanilla doors; it only shrinks to fit a smaller opening. Measured with
`door_01`: at `radius=128` the leaf fills its 256-woxel opening and touches both
wall ends, while at 192, 256 and 384 the leaf stays about 250 woxels and only
the hole grows, leaving gaps of 67, 128 and 259 woxels on EACH side. A tavern's
entrance asked for `radius=256` and its doors floated in half a tile of empty
wall on either hand.

So `radius=128` for an ordinary door, and **a double door is two portals, not a
wider one**: place two with their centres exactly 2 x `radius` apart (256 for
`radius=128`), and the leaves meet in the middle with both outer ends against
the wall. Any closer and Dungeondraft relocates one of them; the join then
renders as overlapping rubble.

**And never leave a gap in the wall for a door to sit in.** Measured: with a
400-woxel gap the portal snapped 200 woxels sideways onto the end of a wall run;
with a 640-woxel gap it fell back to freestanding — `kind: "portal"` rather than
`"wall_portal"` — and hung in the opening touching neither side. Both replies
otherwise read as success, and a portal placed too near another is moved the
same silent way. Read `kind` and `snap_distance` on every portal you place.

**A roof hides the room it covers — check under it before you call a building
done.** `add_roof` takes a RIDGE line and a width, not the building's outline,
so the roof it produces can easily be larger than the walls beneath it. One map
finished with a roof overhanging its inn on two sides, hiding the wall line,
and a second roof covering a furnished coach house completely; the reviewer's
first two words for it were "buildings overlap", though no wall overlapped
anything.

Compare them rather than eyeballing: `get_element` on a roof returns its
`points`, `width` and `roof_type`, and on a wall its `points`. If the roof
reaches past the wall it belongs to, fix the ridge or the width. Then capture
the interior with the roof in place — the map is delivered with it, and a room
nobody can see is not furnished.

**A battlemap is played from inside, so decide what the roof leaves visible.**
A roof that covers a furnished room makes the export useless for play: the
party stands in a space nobody can see. Either keep roofs to overhangs,
awnings and porches that frame the interior without hiding it, or deliver two
exports — one with roofs for the establishing view, one without for play — and
say which is which when you hand them over.

**Then prove the structure before you furnish anything.** Call
`validate_floorplan`. It is read-only, and it answers what element counts
cannot: whether every room can actually be reached, whether each door opens
onto something, and whether there is a way in from outside. A sealed room and
a well-connected one have identical counts, and the difference surfaces only
in a render — by which point the furniture is already in and repairing the
shell means moving all of it twice.

Treat a non-empty `sealed_regions`, `portals_not_in_a_wall` or
`portals_to_nowhere` as a stop: fix the shell and re-run until `ok` is true.
Read `exterior_openings` with judgement — it cannot tell a door from a window,
so a building listed there may still have no way in.

Checkpoint with `save_map` and capture a whole-map `screenshot` before
continuing. Checkpoints are not ceremony: the bridge's undo stack is capped at
40 operations and evicts the oldest first, so once a build passes that depth a
saved file is the only way back to a known state.

**A checkpoint is a save you confirmed, not a save you asked for.** After
`save_map`, poll `get_status` until `saving.in_flight` is false, then confirm
ALL THREE of:

- `saving.saves_seen` rose
- `saving.is_backup` is **false**
- `get_status.map_file` names a real file

A rising counter alone is not proof. Dungeondraft autosaves on its own, into
`user://backups/...`, and an autosave satisfies both `in_flight: false` and a
higher `saves_seen` without writing the file you asked for. One build watched
that counter reach 17, reported "16 confirmed writes" to the user, and had
never saved the map at all: `map_file` was still unset and ninety-one objects
existed only in memory (#81).

**Save with an explicit `filename` the first time.** A map that has never been
saved has no path to save over. If `map_file` is still empty late in a build,
stop and say so rather than continuing to report checkpoints.

If `save_map` reports that Dungeondraft did not start
a save, or an edit comes back carrying a `save_warning`, stop building and tell
the user. One build ran for twenty minutes past a save that had crashed inside
Dungeondraft, into a map that could no longer be written, and the finished
tavern existed only in memory. Work after an unconfirmed checkpoint is at risk;
work after a wedged one cannot be kept.

## 4. Assign region emphasis and purpose

List the regions — each exterior zone and each interior room — and give every
one **a purpose and a level** before crafting any of them. The purpose is what
happens there: dining, service, storage, sleeping, passage. A region whose
purpose you cannot name will not read as anything once it is furnished.

| Level | Meaning |
| --- | --- |
| Hero | Carries the focal event. Deepest detail; usually one region, rarely two. |
| Supporting | Explains its use and feeds the route. Moderate detail. |
| Quiet | Reads as space. Finished when it is sparse, not when it is full. |

Emphasis is about **visual prominence**, which is not the same as object
count. A storeroom is quiet because it is uniform, unlit and low-contrast;
it can still be densely packed, and a ceremonially half-empty storeroom is its
own kind of wrong. Reach for uniformity, low light and low contrast to make a
region recede, before reaching for fewer objects.

Most regions are not hero. Without this budget, crafting each room carefully in
turn produces a uniformly busy map with no hierarchy — the same defect the
[composition audit](../battlemap-composition-audit/SKILL.md) exists to catch,
reached from the opposite direction. A quiet region is *finished when it is
sparse*; leaving it bare is the plan, not neglect.

## 5. Draw the circulation

**A path has ends, and they are what make it read as part of the world.**
`draw_path` takes `fade_in`, `fade_out`, `grow` and `shrink`. A trail that
stops at a hard rectangular cut announces itself as a drawn object; one that
fades into undergrowth, or narrows as it climbs away, reads as terrain. Set
them per path — the PathTool's own settings do not reach this call.

Choose the system before the asset: a terrain slot for ground that must BLEND
into its neighbours, a textured Path for a trail, fence line, kerb or shadow
strip, a pattern for a tiled floor. They look similar in a plan and behave
nothing alike.

Before furnishing anything, decide how the map is moved through, and write it
down as a route from each entrance to the focal region and on to the secondary
ones. Every region with a purpose must connect to it.

Keep the main routes one to two tiles clear, and check them against the portals
already placed — a route that does not pass through a door is not a route.
Furniture may narrow a route deliberately, but a route discovered *after* the
furniture is a route the furniture chose.

## 6. Exterior regions, one at a time

**Cover the whole map with ground first.** One `fill_terrain` with the base
material, before a single exterior object is placed. Terrain painted afterwards
gets painted *around* what is already there — grass under the trees and nowhere
else — and that reads exactly as what it is: objects floating on a void. It is
one call, and it is far cheaper than noticing later.

Use `fill_region` for a shape with an edge — a road, a yard, a bed — and
`paint_terrain` only for soft blending between materials. `paint_terrain` is a
circular brush with a falloff, so using it to cover an area leaves a trail of
discs that read as stains rather than ground.

Work the ground and outdoor zones with the
[environments](../battlemap-environments/SKILL.md) skill, region by region.
For each: frame it with `set_camera` (or `fit_elements`), build it to its
assigned level, capture a framed `screenshot`, repair only what that view shows,
then `save_map` and move on.

## 7. Interior rooms, one at a time

**Look for a prefab before hand-composing anything that repeats.** Call
`list_prefabs`. A table setting, a market stall, a smithy, a campsite — if one
exists, placing it is both faster and more coherent than assembling it from
parts, because its parts were composed together. Place ONE first, read what
`place_prefab` reports it created, and look at it: a prefab may bring elements
this bridge cannot transform, and the response names what it skipped. If it
suits, reuse it and vary rotation and position rather than rebuilding it.

Hand-composition is for the unique anchors — the thing the room is about — and
for cases where no prefab fits. It is not the default.

Work each room with the [interiors](../battlemap-interiors/SKILL.md) skill in
the same rhythm — frame, build to the assigned level, verify, checkpoint, move
on. Finish a room before starting the next; a room you keep returning to is
taking budget from one that has had none.

**An object that carries its meaning through its neighbours needs them in the
same pass.** A bar counter with no stools, no bottles and no back shelf reads
at map zoom as a plank lying on the floor — which is exactly how a reviewer
described one (#87). A forge without tools, a market stall without goods, an
altar without candles all fail the same way: the asset is right and the thing
is not legible. Place the supporting props with the anchor, not in a later
pass, and look at the cluster in a screenshot before moving on.

`preview_assets` tells you what an asset looks like while you are CHOOSING.
Nothing tells you how it reads once placed except looking at it in context.

**Vary what you place.** Fixtures that belong squared to a wall stay square;
give everything else a slightly different scale (about 0.85-1.15) and a few
degrees off the quarter turns, in the call that places it. A `place_objects`
batch that comes back rigid carries an `arrangement_note` saying so; adjust
that batch with `modify_object` before the next batch, not in a later pass.
`validate_scene` reports the share for the whole map under `arrangement`.

**Then prove the furniture before you light it.** Call `validate_placements`.
Phase 3 proved the shell was sound; this proves the furniture respects it —
objects crossing a wall, or standing in a doorway or across a window. Those
look correct in every element count and in the response to the call that placed
them, and they are only obvious in a render, where it is tempting to judge by
eye and call it fixed without measuring.

It says nothing about a dressed surface — a tankard on a table is correct —
but read its `stacked` and `adrift_fixtures` lists, which are advice rather
than failures. `stacked` is two large objects in one place on one layer, which
is what "assets thrown on without care" looks like from the outside.
`adrift_fixtures` is a torch, tapestry or hearth standing away from the wall
it should be mounted on. Both are matched roughly, so look before you move
anything.

Treat a finding as evidence, not a verdict — read the reported `bounds` and
decide. A hearth set into a thick wall is a deliberate choice this will report;
an armchair halfway through the same wall is not. A non-empty `unmeasurable`
means those objects were not checked at all, which is not the same as clean.

## 8. Light the map

Place sources with `add_light` against the ambient set in phase 2, following the
lighting hierarchy. Lighting is deliberately global: it is what ties separately
built regions into one scene.

## 9. Cohesion review

Run `validate_scene` first. It answers two things a render can raise but not
diagnose: whether any open ground was left unpainted, and whether every light
has something emitting it. Both are invisible to element counts — terrain has
no count at all, and a light with no source is a perfectly valid light. Read
its `explained` list as well as `unexplained`: it names the asset it credited
for each light, so a wrong match shows up too.

**Quote what the validators returned; never summarise them as "clean".** A
verdict is `ok: true` or it is not. One build told the user that connectivity,
placement and lighting "were all checked with the map's validation tools and
came back clean" while `validate_scene` was returning `ok: false` with a light
nothing could be emitting (#82). An `ok: false` from any validator blocks
calling the map finished: fix the finding, or state it plainly as a known
defect in the summary. If you judge a finding to be a false positive — the
light matcher works on asset NAMES and can be wrong — say that you judged it
and why, rather than dropping it from the report.

Read `complete` and `coverage` too. A validator that could not read the whole
map says so, and an incomplete verdict is not a clean one.

Then capture a whole-map `export_map` and check that regions built apart still read
as one place — consistent materials, an unbroken route, and emphasis where the
plan put it. Run the composition audit, then
[visual review](../battlemap-visual-review/SKILL.md). Make at most three
targeted repairs, capture again, and finish with a final checkpoint. If you
loaded a trace image, call `set_trace_image(clear=true)` before that save: the
trace saves with the map, as an absolute path nobody else's machine has.

## 10. Deliver it

A finished map is not the same as a delivered one. Decide, and say what you
chose:

- **Labels.** `add_text` for room names, a sign, a caption. A GM map usually
  wants them; a player-facing one usually does not. Keep labels purposeful
  and clear of routes. Export the player version before adding secret or GM
  labels, and inspect both files for legibility and accidental spoilers.
- **Grid.** Whether a grid shows, and in which style, is part of how the map
  will be used at the table. `get_map_style` reads the actual world textures;
  `set_map_style(grid_style="dotted")` chooses `dashes`, `dotted`,
  `narrow_line`, or `thick_line`. Choose a pattern that stays readable over
  the floor at play scale. This changes the pattern, not visibility or export
  inclusion: inspect the actual delivered image before promising a grid.
- **Wear.** `set_map_style(building_wear="grime")` offers `none`, `dust`,
  `grime`, `noise`, and `scratched`. These are textures, not intensity levels.
  Wear affects the whole map across levels: use it when the brief calls for
  age or neglect, and keep `none` when clean architecture fits. Compare a
  framed screenshot before and after; undo it if it obscures useful detail.
  Both style fields can change in one undoable call. Read back with
  `get_map_style`, then verify the rendered effect rather than trusting a menu.
- **Which outputs.** `export_map` renders the whole map without UI. A GM
  version and a player version are different files, not one file with a
  caveat.
- **VTT.** Universal VTT export cannot be driven from here — it only runs from
  Dungeondraft's own export window. If the user wants one, say so plainly and
  hand it over rather than appearing to have produced it.

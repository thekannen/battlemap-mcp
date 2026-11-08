# Changelog

What changed in each release, written for the people using it. Versions cover
the companion, the Dungeondraft mod and the map-making skills together; the
wire protocol between them is versioned separately and is currently 25.

## 1.4.2 — 2026-11-08

No more console windows flashing on Windows, your own images on the map,
and support for Moulk's Soft Shadows and Sketch Tool. The first two are
@arhidavid's work, from two pull requests: thank you, David.

**No more console windows flashing on Windows.** Every time a map opened,
Windows briefly showed a console window and could pull focus away from
Dungeondraft. That now happens only once, when Dungeondraft starts; later
map opens in the same session show nothing.

**Put your own images on the map.** Your assistant can place a PNG from
your computer, such as a hand-drawn token, a sign or a handout, as an
object you can move, turn and resize like any other. The image is stored
inside the map file, so it is still there if you move or delete the
original.

**Soft shadows your assistant can set.** With Moulk's Soft Shadows mod
installed, your assistant can add, adjust or remove soft shadows on
objects, walls and paths, and undo the change. Objects it copies keep
their shadows, where before the copies came out without them.

**Sketch notes stay out of exports.** With Moulk's Sketch Tool installed,
the notes you sketch over a map used to appear in images your assistant
exported. They are now hidden for the export and back on screen
afterwards, as with Dungeondraft's own Export window.

**Redo survives looking and saving.** Undoing a step, then taking a
screenshot or saving, used to throw away the step you could have redone.
Moving the view and saving now leave redo alone.

**Long sessions use less memory.** Elements kept for undo were left in
memory each time a different map was opened. They are now freed with the
map they belonged to.

## 1.4.1 — 2026-10-30

Rooms built side by side share one wall, so their doors open in your VTT,
and a few smaller fixes. Most of this release is @bularzik's work, from
five pull requests: thank you, Dan.

**Doors between rooms open in your VTT.** Two rooms built next to each
other used to get two walls on the edge they share. A door mounts on one of
them, so in Foundry or Roll20 the other still blocked the doorway. Now the
second room uses the wall that is already there and draws only its free
sides, so the door opens. A room drawn inside walls that already surround
it gets just its floor. Only a wall of the same kind is shared, so a cave
wall is never borrowed for a stone room.

**Tiled floors drawn as colour masks come out brown, not white.** Simple
Tiles such as damaged wood, diamonds and the ornate tile are drawn as red
masks meant to be tinted. Placed without a colour they rendered white; they
now get the same neutral brown as other plain floors. Floors with colours
of their own are left as they are.

**Line up a traced sketch with the grid.** Your assistant can now put a
reference image exactly where it should sit, so a hand-drawn plan's squares
match the map's. Asking twice puts it in the same place, and the position
is saved with the map.

**Hide the grid in the editor.** Your assistant can show or hide the grid,
for example to take a clean screenshot. It works the View menu's own Grid
checkbox, so the menu always matches what you see. It isn't saved: the grid
is back when you reopen the map.

**A colour suggestion for unpainted objects.** When an object is placed
without a colour and shows as a flat red shape, your assistant is now told
Dungeondraft's own default colour as a fallback, while still choosing one
that suits the object.

**Moving an old bridge copy out of Program Files explains itself.** If a
copy sits in a folder only an administrator can change, the installer now
says so before touching anything, instead of failing part-way with an
error that read like a bug.

**The Battlemap MCP Bridge panel's note is accurate.** It said your assistant could
not change any of the panel's settings, but it can switch Verbose log for
troubleshooting. The note now says which settings are yours alone.

## 1.4.0 — 2026-10-20

Furnish a room in one step, keep scattered art off walls, place lights with
their lamps and crop a map from any side. Many of these ideas come from
@immortalBan's fork, rebuilt here with their blessing: thank you, Ivan.

**Furnish a room in one step: shelves along a wall, chairs around a table,
books on a desk.** Ask for a row of shelves
and your assistant backs them flush against the wall, fronts into the room,
leaving doors and corners clear. Ask for seats and they ring the table, each
facing it, a touch irregular so the table doesn't look stamped out. Ask to
dress a desk and the items land on top of it, inside its edges, without
piling on each other. Everything is fitted to what the art actually covers,
so pack furniture no longer stands a hand's width off its wall. Each
arrangement is a single undo, and your assistant can preview it before
placing anything. Where two rooms share a wall, it says which of the two it
used.

**Asset listings say how big each asset is, and how much of it is drawn.** Your assistant now sees each asset's size
and the part its art actually covers before placing it. Art from asset packs
often fills under half of its image, so this is what lets beds, rugs,
shadows and spacing be fitted to the drawing instead of to empty space,
without placing a test copy first.

**Scattered trees and clutter stay off walls and out of paths.** `scatter_objects` takes `wall_margin` and
`avoid_rects`, measured from the part of each asset that is actually drawn,
so a tree's crown no longer lands over a wall or across a doorway. On a
128-tile map with 3,000 wall segments, a 500-object scatter takes under
half a second.

**Lights go in with their lamps, and can be adjusted afterwards.** A lantern, brazier or candle can be placed with
its light in one step, a whole lighting pass is one undo, and a light's
colour, brightness, range and shadows can be changed after it is placed.
Those changes are saved with the map.

**Asset previews can show true relative sizes.** A preview sheet can draw every asset at one scale, so a stool shows
small beside a table, and the assistant gets each asset's size alongside
the picture.

**Asset searches can stay inside one pack.** Name a pack this map includes, by its id or its name, and the search
looks only there. Naming a pack the map does not include is refused with
the packs you can choose from, rather than coming back empty.

**A search that finds nothing tries words that mean the same thing.** Asking for a rug when the library calls it a
carpet now finds the carpet, and says that is what it searched. Only true
equivalents are tried (rug and carpet, armour and armor, bookshelf and
bookcase): a desk never turns into a table, so a missing piece still shows up
as missing.

**Screenshots can aim themselves.** Your
assistant can name an area of the map, or a point and how many tiles across
to show, and take the screenshot in one step instead of moving the camera
first.

**The map-making skills check for every named piece before building.** If your brief names something the library does
not have, you hear about it up front with options, instead of finding a
lookalike in its place.

**Ask which version you are running.** The connection check now names the
version of the companion and of the Dungeondraft mod it is talking to, and
says plainly when the two differ and which one to update.

**Updating the mod tidies away old copies, if you agree.** When the
installer finds another copy of the bridge in your mods folder, such as an
older install under a different folder name or a fork that uses the same
mod id, it shows where each would go and, once you agree, moves each one to
a backup outside the mods folder, so Dungeondraft loads only one. Nothing is
deleted. From the command line, `install --move-other-copies` does the same.

**Crop a map from any side.** Ask your assistant to make a 20x20 map a
15x15 and it proposes which part to keep, shows you what would be removed,
and on your go-ahead keeps a copy of the file, crops it with Dungeondraft's
own resize and moves everything to fit. Anything left wholly outside is
removed in one step you can undo. Walls and paths that cross the new edge
are kept as they are, and your assistant mentions them. Dungeondraft's own
trim from the top or left loses terrain paint near the far edges and leaves
cave borders behind their floor; a crop by your assistant repairs both,
with or without the Unofficial Patch.

**Material patches inside rooms stay visible.** Your assistant now knows
that materials painted on the lowest layers sit underneath floors, so on a
room's floor it paints them on a layer that shows, in Dungeondraft and in
your exports.

**Light colours read back exactly as Dungeondraft saves them.** A light,
water or text colour could read one step off the map file (`e6b3` where the
map says `e6b2`), and a Universal VTT export carried the difference.

## 1.3.1 — 2026-10-20

Objects that block light now reach your VTT, and the user guide has moved to
knownframe.com.

**Light-blocking objects export to your VTT.** 1.3.0 said a Universal VTT
export outlines every object that blocks light. It didn't: every one was
left out, so in Foundry or Roll20 boulders, crates and pillars blocked
nothing. Each one now arrives as a box outline, as 1.3.0 described. Thanks to
immortalBan, who found it, traced the cause and proposed the fix (#9).

**The user guide lives at knownframe.com.** Installation, troubleshooting and
the tool reference are now at https://knownframe.com/battlemap-mcp/docs/.
The install notes in each download, the Claude desktop extension and the
Claude Code plugin link there.

## 1.3.0 — 2026-10-11

Export and rebuild Universal VTT files, check a map before you open it, and
get doors and windows that behave in your VTT.

**Export for your VTT from the chat.** Ask your assistant for a Universal VTT
(`.dd2vtt`) file and it writes one beside your map, ready for Foundry, Roll20
or Arkenforge: the image, walls, doors and windows, lights and ambient light.
Its walls, doors and lights match Dungeondraft's own export of the same map.
Objects that block light are outlined as boxes, a little coarser than
Dungeondraft's own outlines.

**Rebuild a map from a Universal VTT export.** Hand your assistant a
`.dd2vtt` file and it rebuilds the map's walls, doors and windows, lights and
ambient light on the open map, and lays the export's image underneath as a
trace to follow. The walls come back whole, with each door mounted in its
wall, and a region export is cropped to its region. It shows you the plan
first and changes nothing until you agree, and one request undoes the whole
import. It doesn't pick art: it tells your assistant where each
sight-blocking object stood, and its size, so it can place something that
matches.

**Doors and windows work right in your VTT.** A Universal VTT export can't
say "door" or "window"; VTTs go by whether a portal blocks light. Your
assistant was marking windows as light-blocking and doors as not, so in a VTT
every door acted as a window and every window as a door. It now sets this
from the asset: doors block light (an openable door in the VTT), windows don't.
The structure check names any door or window that would swap roles, and
rebuilding from an export puts windows back as windows.

**Check a map before you open it.** Your assistant can read a
`.dungeondraft_map` without opening it: which asset packs it needs and
whether you have them, what it is built from (terrain, materials, paths,
the most used objects and their sizes), and doors or windows that would swap
roles in a VTT. Handy for maps you download or are sent, and for comparing
two versions of a map.

**Material patches land where you paint them.** Ice, mud and other material
patches all ended up in the map's top-left corner, wherever they were
painted, and undo skipped them. They now go where your assistant paints
them, and each stroke can be undone.

**Light range means what Dungeondraft says.** A light's range used to be
half the number Dungeondraft's Light tool, your saved map and a VTT export
show, so "range 6, like in Dungeondraft" made a light half that size. Your
assistant now sets and reads range in Dungeondraft's own units.

**OpenCode connects in one step.** With OpenCode 2, Connect OpenCode now
registers the companion itself, as Connect Claude Code does, instead of
printing an entry to paste. It still leaves an existing entry that runs
another program alone. OpenCode 1 gets the entry to paste, as before.

**The bridge is found under any folder name.** The installation check, and
installing or updating the bridge, used to look only for the mod's usual
folder name. A bridge unpacked under any other name was reported missing, and
a second copy in the same folder went unnoticed. They now recognise the mod
itself, whatever its folder is called, and warn when two copies would load.

**Trace images no longer pile up.** Images your assistant lays under a map
to trace over (including an import's) are now cleaned up like screenshots:
the newest three are kept, and clearing captures removes all but the newest.
A map whose trace image is gone still opens, just without its trace.

## 1.2.0 — 2026-10-06

Install it from Claude, let your assistant search inside every asset pack you
own, and export maps without the grid.

**Install from Claude.** Claude Desktop users can install a single
`.mcpb` file as an extension; until now, Desktop chat had no way in. In Claude
Code, the plugin now brings the map tools as well as the map-making skills.
Update the plugin with `/plugin`, or the extension by opening the new
version's `.mcpb`. The Dungeondraft mod is still installed separately: ask
your assistant to install the bridge, then restart Dungeondraft. If a bridge
is already there, it keeps a backup of the old one. The companion download
and its Connect files still work as before; use one way, not both, or your
assistant sees every tool twice.

**Connects on the first try.** The first launch after installing or updating
could fail to connect in Claude Code, because the companion was still
starting when Claude Code moved on to a fallback the companion then turned
down. It now connects on a slow first launch too.

**Search inside your asset packs.** Your assistant can look inside every
installed asset pack, including the ones the open map doesn't use, and see
which packs actually have a well, a pergola or hay bales before choosing
which to add to the map. It reads only each pack's list of files and tags,
never the art. Packs whose authors ask third-party tools not to read them are
named but left unsearched.

**Preview a pack before adding it.** Asset previews now work for packs the
map doesn't include yet, so your assistant can show you candidates before
adding a pack. Placing from such a pack is still refused until it is added,
because Dungeondraft would drop it on reopening.

**Export without the grid.** Exports can leave the grid out, the usual choice
for sharing a map or using it in a VTT that draws its own. Your grid in
Dungeondraft is put back afterwards.

**Fit things to the art, not the canvas.** Your assistant can now see how
much of an object's image is actually drawn. Much pack art fills only half its
canvas, so soil beds, rugs and shadows fitted to it now sit under the plant
or furniture instead of off to one side.

**More checks on furnished rooms.** The placement check also points out
dressing that hangs off the table or counter it stands on, one part of a
multi-piece fixture placed without the rest (bedding without its bed frame, a
hearth without its chimney), and more wall fixtures standing away from a
wall. The scene check counts how many assets come from each pack, so a map
that mixes art styles is easy to spot.

**Better map-making guidance.** The skills now cover keeping a map to one art
style, placing multi-part fixtures whole, furniture that faces the room and
sits against its wall, dressing that stays on its surface, a building's
street and planting, weathered ground and small water, lighting where people
live and darkness where they don't, and reviewing each room up close before
moving on.

**OpenCode setup.** A new Connect OpenCode file installs the skills and shows
the one entry to paste into OpenCode's settings. OpenCode has no command for
adding a server, and the Connect file never edits your settings itself.

**Update notices name the files.** When a new version is out, your assistant
gives you direct links to the right companion for your computer, the mod and
the checksums, or, for a plugin or extension, tells you how to update through
Claude.

**Windows downloads keep their good standing.** The Windows companion is now
a small launcher, `battlemap-mcp.exe`, kept the same from release to release,
with the rest of the program beside it in `battlemap-mcp.pkg`. This way,
antivirus trust earned by the launcher can carry over to new versions
instead of starting again each time. Keep the `.pkg` next to the `.exe`.

## 1.1.1 — 2026-10-01

Fixes for colours, terrain, the map checks and a few unhelpful error messages.

**All eight terrain slots paint.** Terrain slots 5 to 8 (numbered 4 to 7 by
your assistant) accepted paint but showed nothing, even after the map was
reopened. They now paint, blend with the other slots, save and undo like the
first four. Your assistant gives a slot a texture before painting it.

**Floor tiles keep their own colours.** A tiled floor placed without a colour
was always tinted brown, which turned green marble almost black and sandstone
orange. Tiles with colours of their own now show them; plain grey tiles still
get the neutral brown.

**Fewer false "this will be red" warnings.** Many Forgotten Adventures assets
were called colourable and said to render flat red, while a colour had no
visible effect on them. Your assistant now uses Dungeondraft's own rule for
which parts take a colour, including each asset pack's own settings. It
warns about flat red only when most of an asset is colourable, and mentions
smaller red parts separately.

**Quieter map checks.** Paintings, wall lanterns, curtains and similar
fixtures hung on a wall are listed as wall-mounted instead of as objects
crossing the wall. Lights on candelabras, and on anything from a pack's light
sources folder, count as having a source.

**Clearer messages.** When something unexpected goes wrong in a tool, such as
a screenshot or an export, you're told what failed instead of getting an
empty error. When the companion and the Dungeondraft mod don't share a
connection key, typically because an older or development copy of the mod is
installed, the error and the connection check say so and point to the newer
key, instead of asking you to start Dungeondraft. Window and door frames that
draw almost nothing on their own come with a note to add the matching window
or door. An asset whose image fails to load is no longer called "not an
object".

## 1.1.0 — 2026-09-25

Your assistant now works with two popular Dungeondraft mods, the Custom Snap
Mod and Moulk's Unofficial Patch, and Dungeondraft gains a settings panel where
you can pause it, undo its last step and choose how it places things.

**Custom Snap Mod support.** If you use the Custom Snap Mod, your assistant
can now see your grid, square or hex with its spacing and offset, and place
objects, rooms, walls, doors, paths, lights and prefabs on it, where your own
cursor would snap. Moves and copies travel in whole grid steps.
It reads your snap settings and never changes them. Without the mod,
nothing changes.

**Unofficial Patch support.** If you use Moulk's Unofficial Patch, your
assistant now notices and works with it: it can resize maps up to 200 tiles,
place things on the patch's Above Lights layer, and keep its camera, text and
wall changes from being undone by the patch. On a level where you've turned on
the patch's 24 terrain slots, it won't paint terrain, so it can't spoil what
you painted. Objects you've shaped with the patch's Free Transform keep their
shape when your assistant turns, scales or copies them, and groups you made
stay grouped when it moves a member. Your assistant can also tell when one of
the patch's popups is open, and keeps working while it is. Without the patch,
the one change is that an object layer Dungeondraft doesn't have, such as 150,
is now refused instead of being saved on a layer that doesn't exist.

**A real settings panel in Dungeondraft.** Settings > Battlemap MCP Bridge now shows
whether your assistant is connected and what it last did, and gives you
controls:
- **Pause AI edits** stops your assistant changing the map without closing
  anything; it can still look, and tells you it's paused.
- **Undo the assistant's last step.**
- **Check for updates**, **Snap to my grid** by default, and how many
  screenshots and exports to keep.

Your assistant can read these but can't change them. The panel also has a
proper icon instead of a blue square.

**Undo a whole request.** Your assistant marks where each request starts and
can undo all of it in one step, instead of one edit at a time. It won't undo
anything another assistant or chat did, and it tells you if something can't
be undone.

**A failed save says so.** If Dungeondraft starts saving a map and never
finishes, your assistant now learns at once that the file wasn't written and
can save again, instead of waiting a minute to be told the save might still be
running.

**Tidier in the background.** Each chat's companion now closes when that
chat ends, even in the middle of a task, instead of lingering.

## 1.0.3 — 2026-09-24

Fixes for resizing maps, water, JPG exports and the placement checks.

**Resized maps open again.** Resizing a map left its terrain, cave and floor
layers at the old size. The saved file then froze Dungeondraft when it was
reopened. Resizing now uses Dungeondraft's own Change Map Size, so everything
resizes together and painted ground past the old edge survives a reopen. Maps
can be 8 to 128 tiles a side, the limits of that resize.

**Water keeps its colour.** Styling water made it vanish until the map was
reopened. The chosen colours were also lost on reopen, which brought back
Dungeondraft's default teal. Water now stays visible, keeps its colours when
saved, and new water on a level takes the colours already used there.

**JPG and WebP exports match the editor.** They were saved at a quality of
zero, which made blocky ground and wrong colours. They now render at quality
90, and your assistant can choose another quality.

**Large batches don't go through the conversation.** Your assistant can put
up to 1,000 object placements in a file and place them in one step, which one
undo reverses. Before, it had to type every placement into the chat.

**Fewer false alarms from the placement check.** Posts and beams set over wall
corners, as the building guidance recommends, no longer count as crossing a
wall. Wall torches beside a door are no longer reported as far from the wall.

**Clearer messages.** When Dungeondraft is running but busy, for example still
loading or waiting on a dialog, you're told that instead of being asked whether
it's running. A trace image path that's too long for Windows is copied
somewhere shorter. The help no longer says trace images aren't saved with the
map, because they are. A Windows path given to a companion running under WSL
is refused with the `/mnt/c/...` form of the same file.

**Trace images show up.** A trace image loaded on a new map was saved with it
but never appeared in the editor. It now shows when it loads and hides when it
is cleared. Exports still leave it out.

## 1.0.2 — 2026-09-23

Cleaner Windows downloads, and a way to hear about the next version.

**Fewer antivirus warnings on Windows.** A couple of antivirus engines flagged
the Windows companion as suspicious because of the generic launcher that many
Python apps share, including malicious ones. The Windows companion is now built
with its own launcher and carries its name, version and icon, and every release
is scanned on VirusTotal before it is published.

**You'll hear about new versions.** The companion cannot update itself, so it
now checks GitHub at most once a day for a newer release. When there is one,
Check connection says so and your assistant passes the download link on. The
check sends nothing about you or your maps; the privacy page explains it and
how to turn it off.

## 1.0.1 — 2026-09-23

Fixes for installing on Windows.

**Check connection trusts a correct install.** On Windows, Check connection
reported a correctly installed mod as needing attention, because the companion
and the mod download stored the same bridge files with different line endings.
Both downloads now carry identical files, and the check no longer counts line
endings as a difference.

**Connect explains an existing Claude Code connection.** When Claude Code
already has a `battlemap` connection from an earlier install, Connect now
shows the command that connection runs, says whether that file still exists,
and gives the one command that removes it. Previously it only guessed that an
old entry might be in the way.

**Connect says which skills it kept.** Skills from an earlier install that
differ from this version are left in place, in case they hold your own edits.
Connect used to report them as installed anyway; it now names the skills it
kept and shows the command that updates them, backing up your copies first.

## 1.0.0 — 2026-09-22

The first public release.

**Intel Macs get a companion.** Alongside the Apple Silicon download there is
now a signed `macos-x64` companion for Intel Macs.

**The bridge keeps its settings with the rest of its files.** The save
directory you choose is now stored in the companion's own folder instead of
Dungeondraft's, so settings from an earlier installation are not picked up. If
you had chosen a save directory, choose it again.

**Re-enable the mod once after updating.** The mod's internal id changed, so
Dungeondraft treats this version as a new mod. Remove the old bridge folder,
add the new one, and tick **Battlemap MCP Bridge** in the Mods menu again.

## 0.2.3 — 2026-09-22

**Saving keeps working when its folder disappears.** The save directory is
remembered between sessions, so one set inside a temporary folder used to take
saving down with it weeks later, with nothing to explain why. Saves now fall
back to Dungeondraft's own map directory, and both the save reply and
`get_save_directory` say that is what happened.

**Your assistant checks its own work more closely.** The placement check now
also reports large objects dropped on top of each other and wall fixtures —
torches, tapestries, hearths — standing away from any wall. Both are advice
rather than errors, because a spit over a campfire looks the same to geometry
as a crate inside a crate.

**Screenshots point at something.** The assistant is told to aim the camera
before capturing, instead of photographing wherever the view was left.

**Map-making skills:** roofs either stay as overhangs or the map is delivered
with a roofless export people can actually play on; an asset is used for the
job its category was drawn for; a building gets the ground and surroundings it
stands in; furniture varies in size and angle instead of sitting on a grid; and
planning skills now hand off to the skill that does the placing.

## 0.2.2 — 2026-09-21

**Your assistant knows the map is shared.** You, Dungeondraft itself, or a
second AI app can change the map between turns, so it checks again before
telling you what is on it rather than answering from memory.

**Coordinates are explained**, including that they start at the top-left and
run downward, so "the corner at y=390" is the top of the map.

**Asking to see the map** now gets you the saved image's file path, because the
picture the assistant receives is not shown to you directly.

Tool-specific advice moved onto the tools themselves, so the guidance loaded at
the start of every conversation is shorter and more of it applies everywhere.

## 0.2.1 — 2026-09-21

**See what your assistant sees.** Screenshot and export results now include
the saved image's location, so the assistant can hand it to you.

**Opening a map is more reliable.** For a moment during a load, Dungeondraft
can report the new map's name alongside the previous map's contents; opening
now waits for the new map to be genuinely ready.

**Asset searches** report their limit where the assistant can see it, instead
of silently failing when too many search terms were passed.

## 0.2.0 — 2026-09-20

First packaged release: a signed and notarized macOS companion, the
Dungeondraft mod, and the Python package, with connect helpers for Claude Code
and Codex, and the map-making skills.

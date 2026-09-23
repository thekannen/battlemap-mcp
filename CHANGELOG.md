# Changelog

What changed in each release, written for the people using it. Versions cover
the companion, the Dungeondraft mod and the map-making skills together; the
wire protocol between them is versioned separately and is currently 25.

## 1.0.2 — 2026-09-23

Cleaner Windows downloads, and a way to hear about the next version.

**Fewer antivirus warnings on Windows.** A couple of antivirus engines flagged
the Windows companion as suspicious because of the generic launcher that many
Python apps share, including malicious ones. The Windows companion is now built
with its own launcher and carries its name and version, and every release is
scanned on VirusTotal before it is published.

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

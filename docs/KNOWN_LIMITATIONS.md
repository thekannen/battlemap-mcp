# Known limitations

## Platform limits

Windows, macOS, and Linux are supported targets, each with a limit:

- **Windows:** the companion is unsigned. SmartScreen and similar warnings are expected on first run. Check downloads against the release's `SHA256SUMS`; do not turn off Windows security. Run Dungeondraft normally, not as administrator: an elevated session cannot create the bridge's private token, so the bridge does not start. The companion is a small launcher, `battlemap-mcp.exe`, with the program in `battlemap-mcp.pkg`; keep both, and `_internal`, in one folder.
- **macOS:** the companion is signed with an Apple Developer ID and notarized by Apple. macOS confirms the notarization with Apple over the internet the first time the companion runs, so a first launch while offline can be blocked. The Intel companion has been checked only under Rosetta on Apple Silicon, not on an Intel Mac.
- **Linux:** validated on Ubuntu 24.04 under WSL2 only, with Dungeondraft 1.2.0.1. Native Linux desktops and other distributions have not been tested.

## Editing constraints

- The bridge needs a running editor with a map open. Modal dialogs can suspend responses.
- Save and export operations temporarily block edits. A timeout does not prove a command did nothing; inspect state before repeating a mutation.
- Bridge undo history is separate from the editor's undo history, bounded, and not available for every generic tool action. Terrain/cave snapshots have a tighter history budget. Save copies of important maps.
- Object custom color is chosen at placement and cannot be changed afterwards. Nonempty `modulate` values are refused, because that tint does not survive saving and reopening; use baked `color` at placement for compatible assets.
- Pattern IDs are returned by placement but patterns cannot be enumerated by `list_elements`; retain their IDs.
- Asset packs must be included in the map to survive reopening. Installed packs alone are insufficient, and a map's packs are chosen when it is created; `prepare_map_with_packs` writes a copy that keeps them and adds chosen packs. `search_pack_contents` and `preview_assets` can look inside packs the map lacks, but placing from one is refused until it is included, and a pack Dungeondraft has not loaded cannot be included. Without packs the built-in library of 1,792 assets limits results, most visibly in town and market scenes.
- Pack search matches file names, paths and the pack's tags, not meaning: "mug" will not find a tankard. Packs whose authors opt out of third-party reading are listed but not searched or previewed.
- Wall merging supports compatible open runs joined at one endpoint. Loops, branches, crossings, overlaps, cave walls, and style mismatches are rejected.
- Export dimensions must not exceed 16384 pixels on either side. Exports may take time; poll their operation status.
- Visual quality depends on the brief, assets, model, and review. Automated composition facts are not an aesthetic judgment.

## Installing from Claude

- Use one way to connect: the companion download, the Claude desktop extension, or the Claude Code plugin. Two at once give your assistant every tool twice.
- The extension and the plugin take no environment-variable settings; use the MCP Bridge panel in Dungeondraft (for example to turn off the update check).
- The Claude desktop extension has been tested on Windows. On macOS, the plugin's copy of the same bundle has been tested in Claude Code; a Claude desktop install on macOS has not yet been.
- The extension does not include the map-making skills; the plugin and the companion download do.

## Security boundary

The bridge listens on localhost and authenticates message integrity. It does not encrypt traffic or protect against administrators or malicious software running as the same OS user. Your MCP client and model provider may receive map descriptions, paths, and captures; see [privacy](PRIVACY.md).

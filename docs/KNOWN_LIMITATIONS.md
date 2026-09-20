# Known limitations

## Candidate acceptance

This is a private candidate under the battlemap-mcp name, not an approved public release. Final hosted build, clean installation, upgrade/removal, client/model, and live editor acceptance remain pending for the renamed artifacts. Windows signing and Apple Developer ID signing/notarization are not implemented by the candidate workflow. Do not bypass operating-system security warnings to install a candidate.

Windows, macOS, and Linux are supported targets. Earlier Linux editor checks ran on Ubuntu 24.04 under WSL2 with Dungeondraft 1.2.0.1. That history does not establish acceptance of these new packages, every Linux distribution, or every native desktop environment. Each advertised package and environment needs its own recorded result.

## Editing constraints

- The bridge needs a running editor with a map open. Modal dialogs can suspend responses.
- Save and export operations temporarily block edits. A timeout does not prove a command did nothing; inspect state before repeating a mutation.
- Bridge undo history is separate from the editor's undo history, bounded, and not available for every generic tool action. Terrain/cave snapshots have a tighter history budget. Save copies of important maps.
- Object custom color is chosen at placement. Later multiplicative tint changes are a separate operation.
- Pattern IDs are returned by placement but patterns cannot be enumerated by `list_elements`; retain their IDs.
- Asset packs must be included in the map to survive reopening. Installed packs alone are insufficient.
- Wall merging supports compatible open runs joined at one endpoint. Loops, branches, crossings, overlaps, cave walls, and style mismatches are rejected.
- Export dimensions must not exceed 16384 pixels on either side. Exports may take time; poll their operation status.
- Visual quality depends on the brief, assets, model, and review. Automated composition facts are not an aesthetic judgment.

## Security boundary

The bridge listens on localhost and authenticates message integrity. It does not encrypt traffic or protect against administrators or malicious software running as the same OS user. Your MCP client and model provider may receive map descriptions, paths, and captures; see [privacy](PRIVACY.md).

- **Object tint persistence:** nonempty `modulate` values are refused because this tint does not survive saving and reopening. Use baked `color` at placement for compatible assets.

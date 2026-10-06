# Technical reference

battlemap-mcp connects an MCP client to a running local Dungeondraft map. The client starts the Python companion over standard input/output; the companion sends authenticated requests to the bridge mod over localhost TCP. The bridge acts on the open map and returns structured results. See the [wire protocol](PROTOCOL.md).

## Requirements and setup

Dungeondraft 1.2.0.1 and a compatible MCP client must run on the same computer. Install the mod, plus one way to run the companion: the companion download with its Connect file (Codex, Claude Code, OpenCode), the Claude desktop extension (`battlemap-mcp-<version>.mcpb`), or the Claude Code plugin, which installs the same bundle. Use only one, or the client sees every tool twice. Then enable Battlemap MCP Bridge, restart Dungeondraft, and open a map. The bridge is unavailable on the start screen. See [package installation](install-packages.md) or [source installation](developer-installation.md).

The MCP server name is `battlemap`; client tool prefixes may include that name. The Python import package is `battlemap_mcp` and the launcher is `battlemap-mcp`. For the companion download, use its Connect and Check connection launchers for routine setup; Connect OpenCode prints the `opencode.json` entry and never edits that file. Client registration starts the installed companion directly, without downloading a runtime on each launch. The extension and the plugin run the companion bundled in the `.mcpb` and update through Claude; `install_dungeondraft_bridge` installs or updates the mod from a conversation, backing up a bridge it replaces. On Windows the companion is `battlemap-mcp.exe`, a fixed launcher, with the program in `battlemap-mcp.pkg` beside it. The companion answers a client's `server/discover` probe with method-not-found, so every connection uses the `initialize` handshake.

## Working with maps

Check `ping` and `get_status` before editing. Coordinates use world pixels, with 256 per tile. Asset discovery is scoped to assets the map can retain; inspect included packs before choosing content. Keep IDs returned by creation commands for subsequent edits. Review screenshots or a whole-map export as part of visual work. `search_pack_contents` searches inside every installed pack, including ones the map lacks, from the pack files themselves; `preview_assets` can show those, but placing from them is refused until `prepare_map_with_packs` includes the pack. `get_element` reports an object's `bounds` and `opaque_bounds`, the area its art actually covers.

Tools cover asset and pack-contents search, objects, rooms, walls, portals, paths, roofs, lights, text, terrain, caves, levels, selection, snapping, validation, undo and checkpoints, saving, and image export (with or without the grid). Tool schemas supplied during MCP discovery define parameters and defaults.

Exports are asynchronous operations: poll `get_operation` until completed or failed. Wait for saves and exports to finish before editing. Screenshot and export names are bare filenames, not paths; their results report the output path.

## Local state

Integration-owned state lives under `battlemap-mcp` in the platform's local application state directory: LocalAppData on Windows, Application Support on macOS, and XDG_STATE_HOME (or `.local/state`) on Linux. This holds the authentication token, the port discovery file, the bridge's settings (the save directory), the Dungeondraft panel's settings in `mcp_bridge_settings.json` (update check, placement snapping, capture retention), the update check's cache, and saved captures in `mcp_output`. The bridge restricts this directory to your account; it never changes permissions on Dungeondraft's folders.

Environment variables, for the companion download (the extension and the plugin take none; use the panel):

- `BATTLEMAP_MCP_TOKEN_FILE` overrides the token lookup and `BATTLEMAP_MCP_PORT` the port discovery. An override must match the intended bridge session.
- `BATTLEMAP_MCP_CAPTURE_DIR` selects the capture directory and `BATTLEMAP_MCP_CAPTURE_RETENTION` how many captures are kept.
- `BATTLEMAP_MCP_ASSETS_DIR` names the asset pack folder when Dungeondraft's `config.ini` does not.
- `BATTLEMAP_MCP_UPDATE_CHECK=0` turns off the daily check for a newer release, as does the panel's **Check for updates**.
- `BATTLEMAP_MCP_PARENT_WATCHDOG=0` stops the companion exiting when the client that started it is gone.
- `BATTLEMAP_MCP_TIMING_FILE` appends one line of timings per tool call, without arguments or results.

A variable that is set overrides the panel. Never include token contents in logs or reports. See [privacy](PRIVACY.md) for capture handling and what the AI client can receive.

## Development and package status

Use [contributor checks](../CONTRIBUTING.md) and [package build instructions](releases.md). The [limitations](KNOWN_LIMITATIONS.md) describe current constraints and what has been tested. Offline checks and companion startup do not substitute for testing the exact packages with a live editor.

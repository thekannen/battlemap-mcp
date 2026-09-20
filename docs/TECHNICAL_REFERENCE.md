# Technical reference

battlemap-mcp connects an MCP client to a running local Dungeondraft map. The client starts the Python companion over standard input/output; the companion sends authenticated requests to the bridge mod over localhost TCP. The bridge acts on the open map and returns structured results. See the [wire protocol](PROTOCOL.md).

## Requirements and setup

Dungeondraft 1.2.0.1 and a compatible MCP client must run on the same computer. Install matching companion and mod packages, enable Battlemap MCP Bridge, restart Dungeondraft, and open a map. The bridge is unavailable on the start screen. See [package installation](install-packages.md) or [source installation](developer-installation.md).

The MCP server name is `battlemap`; client tool prefixes may include that name. The Python import package is `battlemap_mcp` and the launcher is `battlemap-mcp`. Use the companion's Connect and Check connection launchers for routine setup. Client registration starts the installed companion directly, without downloading a runtime on each launch.

## Working with maps

Check `ping` and `get_status` before editing. Coordinates use world pixels, with 256 per tile. Asset discovery is scoped to assets the map can retain; inspect included packs before choosing content. Keep IDs returned by creation commands for subsequent edits. Review screenshots or a whole-map export as part of visual work.

Tools cover asset search, objects, rooms, walls, portals, paths, roofs, lights, text, terrain, caves, levels, selection, undo, saving, and image export. Tool schemas supplied during MCP discovery define parameters and defaults.

Exports are asynchronous operations: poll `get_operation` until completed or failed. Wait for saves and exports to finish before editing. Screenshot and export names are bare filenames, not paths; their results report the output path.

## Local state

Integration-owned state lives under `battlemap-mcp` in the platform's local application state directory: LocalAppData on Windows, Application Support on macOS, and XDG_STATE_HOME (or `.local/state`) on Linux. This includes token and port discovery files. The old integration's state is not automatically reused.

`BATTLEMAP_MCP_TOKEN_FILE` overrides the companion's token lookup, and `BATTLEMAP_MCP_CAPTURE_DIR` selects its capture directory. An override must match the intended bridge session. Never include token contents in logs or reports. See [privacy](PRIVACY.md) for capture handling and what the AI client can receive.

## Development and package status

Use [contributor checks](../CONTRIBUTING.md) and [package build instructions](releases.md). The [limitations](KNOWN_LIMITATIONS.md) distinguish existing functionality from final candidate acceptance. Offline checks and companion startup do not substitute for testing the exact packages with a live editor.

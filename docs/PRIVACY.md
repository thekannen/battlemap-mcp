# Privacy and local data

This document describes the integration's local connection, stored files, and capture controls. Your AI client's and model provider's data policies apply separately.

## What your AI client can receive

The Dungeondraft mod and companion communicate over a localhost socket on your computer. Tool responses can include map information, asset names, local file paths, screenshots, and exported images. Your chosen MCP client can pass those responses to its model provider. A local bridge does not mean the entire AI conversation stays on your computer.

Check your client's and provider's settings before using sensitive maps. Screenshots and exports can reveal GM notes, secret rooms, and other content you would not want players or others to see.

## Files stored on your computer

The integration uses its own state directory:

| Platform | Default location |
| --- | --- |
| Windows | `%LOCALAPPDATA%/battlemap-mcp` (fallback: `%USERPROFILE%/AppData/Local/battlemap-mcp`) |
| macOS | `~/Library/Application Support/battlemap-mcp` |
| Linux | `$XDG_STATE_HOME/battlemap-mcp`, defaulting to `~/.local/state/battlemap-mcp` |

This directory contains the authentication token (`mcp_bridge_token`), discovered port (`mcp_bridge_port`), and generated captures in `mcp_output`. The bridge protects its own state directory and token; it does not change permissions on Dungeondraft's folders. Do not share the token when reporting a problem.

`BATTLEMAP_MCP_CAPTURE_DIR` can independently override the capture directory in both processes. `BATTLEMAP_MCP_TOKEN_FILE` overrides the client's token lookup; it does not move captures.

## Capture retention and deletion

Screenshots, whole-map exports, and asset previews are image copies written to the capture directory. The server keeps the newest **20 generated captures** by default and prunes older ones after each successful capture.

You can control these local copies:

- Ask your assistant to use the `clear_captures` MCP tool to remove generated captures on demand.
- Set `BATTLEMAP_MCP_CAPTURE_RETENTION` to a non-negative number before starting the companion to choose a different limit. Setting it to `0` removes each generated capture after the server has read it.

Both cleanup paths remove only the filenames the server generates: `screenshot-<hex>.png`, `export-<hex>.<format>`, and `asset_preview.png`. They leave other files and directories in `mcp_output` untouched.

Deleting local captures does not delete copies already included in your AI client's conversation or retained by its provider. Manage those copies through that service's own controls.

## State-directory migration

The battlemap-mcp candidate uses the new integration-owned directory above.
It does not copy or silently reuse state from installations under a previous
integration name or from Dungeondraft's user-data folder. Capture files left in
older directories remain there until you choose to remove them.

Update both mod and companion together, remove the previous bridge from active
mods folders, and fully restart the editor before reconnecting. Re-register the
client under the `battlemap` name and remove an obsolete registration separately
so two integrations do not compete for the same editor.

An explicit `BATTLEMAP_MCP_TOKEN_FILE` override must point to the token the bridge
actually writes. Do not copy authentication tokens between installations. Setup
does not change or repair Dungeondraft folder permissions.

## Further details

- [Installation and removal](install-packages.md#update-or-remove)
- [Technical configuration](TECHNICAL_REFERENCE.md)
- [Authentication protocol](PROTOCOL.md)
- [Licensing and asset ownership](LEGAL.md)

# Privacy

battlemap-mcp does not collect your data. It has no accounts, telemetry, analytics, or update checks, and it makes no internet connections of its own. The Dungeondraft mod and the companion talk only to each other, over a local connection on your computer.

## What your AI client receives

When your assistant uses a tool, the result goes to your AI client (Codex, Claude Code, or another MCP client). Depending on the tool, results can include:

- what is on the open map: elements, their positions, and text labels;
- asset names and asset file paths;
- file paths on your computer, such as where a map or image was saved. These include your user folder's name, which is often your username;
- screenshots and exported images of the map.

Your AI client sends these to its model provider as part of the conversation, and that provider's privacy policy governs them. Check your client's and provider's settings before working on sensitive maps. Screenshots and exports can reveal GM notes, secret rooms, and other content you would not want players to see.

## Images saved on your computer

Screenshots, exports, and asset previews are also saved locally so you can open them. The companion keeps the newest 20 and deletes older ones automatically. Ask your assistant to use `clear_captures` to remove them sooner, or set `BATTLEMAP_MCP_CAPTURE_RETENTION` to choose how many are kept (`0` keeps none). Deleting local copies does not remove images already sent in a conversation; manage those with your AI client and provider.

## Further details

- [Technical configuration](TECHNICAL_REFERENCE.md): where the companion keeps its files, and configuration overrides.
- [Authentication protocol](PROTOCOL.md): how the mod and companion authenticate each other without sending the token.
- [Legal and attribution](LEGAL.md): licensing and asset ownership.

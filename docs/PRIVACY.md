# Privacy

battlemap-mcp does not collect your data. It has no accounts, telemetry, or analytics. The Dungeondraft mod and the companion talk only to each other, over a local connection on your computer. The one internet connection the companion makes is the update check below, and you can turn it off.

## Update check

The companion cannot update itself, so it tells you when a newer version is published. At most once a day it asks GitHub's API (`api.github.com`) for this project's latest published release, and reads only its version number. The request identifies the product but carries nothing about you, your installation, or your maps. Like any web request, it shows GitHub your IP address, and GitHub's privacy statement covers that. Nothing is downloaded or installed.

When a newer version exists, Check connection says so, and your assistant is told to pass it on with the download link. If GitHub cannot be reached, nothing happens. To turn the check off, set the environment variable `BATTLEMAP_MCP_UPDATE_CHECK=0` for your user account, or in your AI client's settings for this server.

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

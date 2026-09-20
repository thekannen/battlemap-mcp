## Support creators first

This is a local automation layer for your own Dungeondraft map-making session. It does **not** generate original assets or art for you; it just drives what you already own in Dungeondraft.

Please support the people behind the work:

1. **Buy and support Dungeondraft** (required to use this project as intended).
2. **Support artists and the community directly** by purchasing asset packs you
   use, commissioning map pieces, and helping creators thrive.

This MCP can only drive features in your local Dungeondraft installation. It is meant to support creators, especially when you're getting started, short on time, or want an assistant for tedious setup tasks. It can help you move faster, but it can never replace human creativity, taste, and mapmaking judgment.

## Bring an AI collaborator into your Dungeondraft map.

Describe the scene you want; it can explore the assets you already own, lay out rooms and terrain, place details, and look at screenshots of the map it made before refining the result. You stay in control of the brief, the style, and the final call.

`battlemap-mcp` is a local bridge between your MCP client and the open Dungeondraft map. It offers tools for building, inspecting, and reviewing maps—without requiring a hosted bridge service.

## What you can make

Ask for a whole scene, work through an idea together, or hand off a repetitive job. These example prompts are starting points: change the setting, mood, and constraints to suit your game. For editing, open a map in Dungeondraft first and work on a copy you can experiment with.

### Build an entire map

Give the assistant a brief and let it develop the layout, terrain, furnishings, and lighting using assets available to your map.

> Turn the blank map I have open into a ruined forest shrine for an ambush. Include a broken central sanctuary, an overgrown approach, two flanking routes, and cover for both sides. Use a restrained stone-and-moss palette. Inspect the available assets first, build the scene, then review a whole-map image and refine anything that looks cluttered or hard to navigate. Leave saving to me.

### Explore ideas before building

Use the assistant as a planning partner. It can inspect the map and available assets while you decide what belongs in the scene.

> Look at my map and suggest three ways this abandoned mill could become an interesting encounter. For each, describe the story, a distinctive focal point, and how players might move through it. Suggest suitable assets I already have available. Don't change the map yet; help me choose a direction first.

### Develop one part of a map

Keep control of the overall layout while getting help with a room, an outdoor area, or a finishing pass.

> Furnish the empty room in the northeast as an alchemist's workshop. Keep the walls and doors where they are. Add a main workbench, ingredient storage, and a small reading corner, leaving clear walking space between them. Match the materials and lighting of the adjacent rooms, then show me the result.

### Clean up and review

Ask for a second look at a map you've already made, with clear boundaries around what may change.

> Review this tavern for blocked doorways, awkward furniture spacing, and clutter that makes the main route hard to read. Show me the areas you would change and explain why. Wait for my approval, then adjust only those areas, keeping the building layout and overall style intact.

### Hand off tedious tasks

Describe the placement rules once and let the assistant apply them across a larger area.

> Place matching wall lights along this corridor at roughly four-tile intervals. Skip doors and intersections, use the same warm color and brightness, and leave existing lights alone. Check the result for uneven gaps and show me a screenshot.

> Scatter small rocks and fallen branches along the forest edge, varying their rotation and spacing. Keep the path and clearing free, use only assets available to this map, and avoid a uniform repeated pattern.

The included art-direction and visual-review skills help the assistant plan and inspect its work. You decide which suggestions to use and when the map is finished. See [known limitations](docs/KNOWN_LIMITATIONS.md) for practical constraints.

## Get started

This is a private release candidate. Its renamed packages still need final installation and live acceptance testing; downloads are available only to invited testers. No public release or package-index availability is implied.

You need **Dungeondraft 1.2.0.1** and **Codex or Claude Code**, installed on the same computer. The companion download includes everything else you need.

Follow the Windows instructions below, or choose [macOS](docs/install-packages.md#macos) or [Linux](docs/install-packages.md#linux).

### 1. Download two files

Open [Releases](https://github.com/thekannen/battlemap-mcp/releases), expand **Assets**, and download these two files from the **same release**:

| Download | What it does |
| --- | --- |
| `battlemap-mcp-mod-<version>.zip` | Adds MCP Bridge to Dungeondraft. |
| `battlemap-mcp-companion-<version>-windows-x64.zip` | Connects your AI app to the mod. |

Skip the **Source code** downloads. You do not need them.

### 2. Put the mod in your mods folder

1. Right-click the **mod ZIP** and choose **Extract All**.
2. Move the extracted **battlemap-mcp-bridge** folder into your usual
   Dungeondraft mods folder. If you do not have one, open File Explorer, enter
   `%USERPROFILE%` in its address bar, and create a folder called
   **Dungeondraft Mods** there. Use that folder instead of Program Files.
3. Open Dungeondraft and click **Mods**, then **Browse**. Select your mods folder
   — the folder **containing** `battlemap-mcp-bridge`, not the bridge folder itself.
4. Tick **Battlemap MCP Bridge**, click **Accept**, then create or open a map. Wait for it
   to finish loading. The bridge does not run on the start screen.

If you are replacing an older bridge, save your map and quit Dungeondraft first. Keep only one MCP Bridge in your active mods folders. Other mods can stay where they are.

### 3. Connect your AI app

1. Right-click the **companion ZIP** and choose **Extract All**.
2. Move the whole extracted **battlemap-mcp** folder somewhere permanent.
   For example, open `%USERPROFILE%` in File Explorer, create an **Apps** folder,
   and put it there. Keep every file inside it, including **_internal**.
3. Open that folder and double-click **Connect Codex** or **Connect Claude Code**,
   depending on which app you use. These files end in `.cmd`; Windows may hide
   the extension. They connect the app and add the included map-making skills.
4. Look for **Setup complete**, then close the window. Fully quit and reopen
   your AI app so it picks up the connection.

Do not run files while they are still inside the ZIP. Do not double-click `battlemap-mcp.exe` itself; your AI app starts it when needed.

If **Connect Codex** says automatic connection is unavailable, you can finish in the app without installing another tool: open **Settings → MCP servers → Add server**, choose **STDIO**, name it `battlemap`, and paste the **Command** path shown by the Connect window. Leave arguments empty, save, and restart the connection. See [OpenAI's MCP setup instructions](https://developers.openai.com/codex/mcp/).

**Claude Code** means the Claude coding client, not the Claude chat app. See [client setup help](docs/install-packages.md#client-help) for other clients or an existing Claude Code connection.

### 4. Check the connection

With a map open in Dungeondraft, double-click **Check connection** in the companion folder. It should say **Ready: connected to MCP Bridge**.

Then start a new conversation in your AI app and ask:

> Check the Dungeondraft connection and tell me the open map's dimensions.
> Don't change anything yet.

The checker confirms the mod connection; this first prompt confirms your AI app can use it. Keep Dungeondraft and the map open while you work.

### If something does not work

| What you see | What to do |
| --- | --- |
| MCP Bridge is missing from Mods | Check that your selected mods folder directly contains `battlemap-mcp-bridge`, with `mcp_bridge.ddmod` inside. Avoid an extra folder from ZIP extraction. |
| Windows asks for administrator access | Put the files in your own user folder instead of Program Files. Select that mods folder in Dungeondraft. |
| “Not connected yet” | Enable MCP Bridge, open a map, wait for loading, and close any Dungeondraft dialogs. Run the checker again. |
| The checker reports an older/different bridge | Use both downloads from the same release, remove duplicate bridge copies, and fully quit and reopen Dungeondraft. |
| The checker is ready, but the AI app cannot see Dungeondraft | Run the matching Connect file, finish any instructions it shows, then fully quit and reopen your AI app. |
| Windows blocks the download | These builds are unsigned. Stop and report the warning to the maintainer; do not disable Windows security. |

[Update, move, or uninstall](docs/install-packages.md#update-or-remove).

## Privacy

See [Privacy and local data](docs/PRIVACY.md) for what your AI client can receive, where local files are stored, and how to manage captures.

## Go deeper

- [Technical reference](docs/TECHNICAL_REFERENCE.md): architecture, tool groups,
  configuration, manual client setup, verification, and development details.
- [Bridge protocol](docs/PROTOCOL.md): the local wire format.
- [Developer installation](docs/developer-installation.md): run from source.
- [Building releases](docs/releases.md): versioning and release packages.
- [Contributing](CONTRIBUTING.md): development workflow and checks.
- [Known limitations](docs/KNOWN_LIMITATIONS.md): editing constraints and release validation status.
- [Documentation index](docs/README.md): installation and contributor references.

## Affiliation and legal

`battlemap-mcp` is an independent, unofficial project and is **not** sponsored, operated, or endorsed by Megasploot or Tailwind Games, LLC. It does not include or redistribute Dungeondraft software, maps, or art assets. See [Legal and attribution](docs/LEGAL.md) for details.

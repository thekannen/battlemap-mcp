# battlemap-mcp

An AI collaborator for your Dungeondraft maps: a local bridge that lets Codex or Claude Code build, inspect, and refine the map you have open, using assets you already own.

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
4. Tick **Battlemap MCP Bridge** and click **Accept**. Then fully quit and reopen
   Dungeondraft: it reads mods only when it starts. Create or open a map and wait
   for it to finish loading. The bridge does not run on the start screen.

If you are replacing an older bridge, save your map and fully quit Dungeondraft first, then delete the old bridge folder before copying in the new one. This applies on every platform. Keep only one MCP Bridge in your active mods folders. Two bridge folders is an unsupported state, and the editor may load both or either one. Other mods can stay where they are.

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

With a map open in Dungeondraft, double-click **Check connection** in the companion folder. It should say **Ready: connected to Battlemap MCP Bridge**.

Then start a new conversation in your AI app and ask:

> Check the Dungeondraft connection and tell me the open map's dimensions.
> Don't change anything yet.

The checker confirms the mod connection; this first prompt confirms your AI app can use it. Keep Dungeondraft and the map open while you work.

### 5. Include your asset packs

Maps come out noticeably better when the map includes asset packs. Without them the assistant has only Dungeondraft's built-in library of 1,792 assets, and that limits what it can make. Town and market scenes show it most: stalls, signs, goods, and street clutter run out of variety quickly.

Dungeondraft includes packs **per map**, and a map's packs are fixed when the map is created. A pack you have installed is invisible to a map that does not include it, and an object placed from it would be dropped when the map reopens. There are two ways to include packs:

- **When you create a map**, choose the packs you want in Dungeondraft's new-map window.
- **For a map you already have**, open it and ask your assistant:

  > List the asset packs I have installed and which ones this map includes. Suggest the packs that suit a busy market square, then make a copy of this map that includes the ones I approve.

  The assistant saves your current map, writes a copy that includes the packs you chose, and opens that copy. Keep working in the copy.

Pick packs that suit the scene rather than all of them: including a very large library is slow, and one big pack can crowd out the rest. This project does not supply art; buy packs from the people who make them.

### Platform limits

- **Windows:** the companion is unsigned. When you first open **Connect** or **Check connection**, Windows may warn you, for example with SmartScreen's **Windows protected your PC**. If you downloaded both files from this project's [Releases](https://github.com/thekannen/battlemap-mcp/releases) page, choose **More info → Run anyway**. To confirm a download is the published one, compare `Get-FileHash <file>` in PowerShell with the release's `SHA256SUMS`. Do not turn off SmartScreen or other Windows security.
- **macOS:** the companion is signed with an Apple Developer ID and notarized by Apple. The first time it runs, macOS confirms that with Apple over the internet. If your Mac is offline at that moment, macOS can block it; connect and open it again. See [macOS install](docs/install-packages.md#macos).
- **Linux:** validated on Ubuntu 24.04 under WSL2 only. Native Linux desktops and other distributions have not been tested.

### If something does not work

| What you see | What to do |
| --- | --- |
| MCP Bridge is missing from Mods | Check that your selected mods folder directly contains `battlemap-mcp-bridge`, with `mcp_bridge.ddmod` inside. Avoid an extra folder from ZIP extraction. |
| Windows asks for administrator access | Put the files in your own user folder instead of Program Files. Select that mods folder in Dungeondraft. |
| “Not connected yet” | Enable MCP Bridge, open a map, wait for loading, and close any Dungeondraft dialogs. Run the checker again. |
| The checker reports an older/different bridge | Use both downloads from the same release, remove duplicate bridge copies, and fully quit and reopen Dungeondraft. |
| The checker is ready, but the AI app cannot see Dungeondraft | Run the matching Connect file, finish any instructions it shows, then fully quit and reopen your AI app. |
| Windows warns about the download or the Connect file | The Windows companion is unsigned, so Windows may warn about it. See [platform limits](#platform-limits). Choose **More info → Run anyway** only for files from this project's Releases page; do not disable Windows security. |
| The assistant keeps using the same few objects | The map probably includes no asset packs. See [Include your asset packs](#5-include-your-asset-packs). |
| You asked to see the map but no picture appeared | The assistant does see it, but your AI app folds images inside the tool call — expand the tool call to view it. The assistant is also given the saved file's location, so you can ask it for the file. |
| macOS blocks the companion | Not a crash. If this is the first launch, make sure the Mac is online so macOS can confirm the notarization with Apple, then open it again. From Finder a block is a "cannot be verified" dialog; from Terminal it is only `Killed: 9` and exit code 137, with no message. See [macOS install](docs/install-packages.md#macos), step 6. |

[Update, move, or uninstall](docs/install-packages.md#update-or-remove).

## Privacy

Nothing is collected: the mod and companion make no internet connections of their own. See [Privacy](docs/PRIVACY.md) for what your AI client receives and how to remove saved images.

## Go deeper

- [Technical reference](docs/TECHNICAL_REFERENCE.md): architecture, tool groups,
  configuration, manual client setup, verification, and development details.
- [Bridge protocol](docs/PROTOCOL.md): the local wire format.
- [Developer installation](docs/developer-installation.md): run from source.
- [Building releases](docs/releases.md): versioning and release packages.
- [Contributing](CONTRIBUTING.md): development workflow and checks.
- [Changelog](CHANGELOG.md): what changed in each release.
- [Known limitations](docs/KNOWN_LIMITATIONS.md): editing constraints and release validation status.
- [Documentation index](docs/README.md): installation and contributor references.

## Affiliation and legal

`battlemap-mcp` is an independent, unofficial project and is **not** sponsored, operated, or endorsed by Megasploot or Tailwind Games, LLC. It does not include or redistribute Dungeondraft software, maps, or art assets. See [Legal and attribution](docs/LEGAL.md) for details.

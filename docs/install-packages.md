# Installation details

Start with the [Windows walkthrough](../README.md#get-started). It uses the
downloadable packages, not a source checkout. This page covers other platforms,
client help, and updates.

## macOS

These are private, unsigned candidate packages. Final clean installation and
live acceptance remain pending for the renamed Windows, macOS, and Linux
artifacts. Windows signing and macOS signing/notarization are required before
public binary distribution; the current workflow does not implement them.

1. From the same [release](https://github.com/thekannen/battlemap-mcp/releases),
   download `battlemap-mcp-mod-<version>.zip` and your Mac companion:
   `macos-arm64.tar.gz` for Apple Silicon, or `macos-x64.tar.gz` for Intel.
   **Apple menu → About This Mac** shows your chip. Skip Source code archives.
2. Extract the mod ZIP. Move `battlemap-mcp-bridge` into your usual mods folder.
   If you need a new one, create **Dungeondraft Mods** in your home folder.
3. In Dungeondraft choose **Mods → Browse**, select the folder containing the
   bridge folder, tick **Battlemap MCP Bridge**, and click **Accept**. Create or open a map.
4. Extract the companion archive and move the whole `battlemap-mcp` folder
   to a permanent location in your home folder. Keep `_internal` and all other
   files with the executable.
5. Open **Connect Codex.command** or **Connect Claude Code.command**. These files
   install bundled skills and register the companion with the selected client.
   If macOS blocks a file, stop and report the warning; do not disable protections.
6. Open **Check connection.command** with a map open in Dungeondraft. Expect
   **Ready: connected to MCP Bridge**. Fully quit and reopen your AI client.

If you prefer Terminal, from the companion folder:

```sh
./battlemap-mcp setup --client codex
./battlemap-mcp doctor --live --brief
```

Use `claude-code` instead of `codex` for Claude Code.

## Linux

**Linux is a supported target.** Earlier editor checks used Dungeondraft
1.2.0.1 on Ubuntu 24.04 under WSL2. That history is not acceptance of these
renamed companion packages or every Linux distribution. Final package and
live acceptance remain pending for this candidate.

Install the purchased **Linux version of Dungeondraft**, along with your AI client,
in the same Linux environment. For WSL, use Ubuntu's Linux filesystem and run the
client inside Ubuntu too; do not reuse the Windows companion or its registration.
The earlier setup used the Linux editor, not the Windows editor through Wine.

### Download and extract

1. Open [Releases](https://github.com/thekannen/battlemap-mcp/releases) and
   download `battlemap-mcp-mod-<version>.zip` and
   `battlemap-mcp-companion-<version>-linux-x64.tar.gz` from the same release's **Assets**.
   This package is for Intel/AMD 64-bit Linux; there is no Linux ARM package.
   Skip the Source code archives. If no Linux asset is listed, that release does
   not yet have a downloadable Linux companion.
2. Extract the archive with your file manager. Move the whole extracted
   **battlemap-mcp** folder into a permanent folder you own, such as **Apps**
   in your home folder. Keep `_internal` and all other files together.
3. Open a terminal in the extracted **battlemap-mcp** folder and run:

   ```sh
   ./battlemap-mcp --version
   ```

   It should print the package version. No Python, uv, Git, `sudo`, or PATH change
   is needed. Native Linux package execution still needs acceptance testing;
   not every Linux distribution has been verified.

### Install and enable the mod

1. Extract the mod ZIP. Move its **battlemap-mcp-bridge** folder into a writable
   mods folder in your Linux home directory, such as **Dungeondraft Mods**.
   Keep an existing writable mods folder if you already use one.
2. In the Linux Dungeondraft app, choose **Mods → Browse** and select the folder
   containing **battlemap-mcp-bridge**. The default `/opt/Dungeondraft/mods`
   location may require administrator access; use your own folder instead.
3. Tick **Battlemap MCP Bridge**, click **Accept**, and create or open a map. Wait for loading
   to finish. Do not run Dungeondraft or the companion as root.

### Connect your client

With your chosen client installed, run **one** of these commands:

```sh
./battlemap-mcp setup --client codex
```

```sh
./battlemap-mcp setup --client claude-code
```

Read the displayed plan and confirm it. Setup installs the bundled skills and
registers this companion's permanent path. Restart your client afterward.
You may run both commands if you use both clients. See [client help](#client-help)
if automatic registration is unavailable.

### Check the connection

With Battlemap MCP Bridge enabled and a map open in the Linux editor, run:

```sh
./battlemap-mcp doctor --live --brief
```

Expect **Ready: connected to MCP Bridge**. Restart your AI client and ask it to
check the connection and report the open map's dimensions without changing it.
If the checker cannot connect, confirm the editor and companion are in the same
Linux environment, the correct mods folder is selected, and a map has finished
loading. The bridge's private state defaults to `~/.local/state/battlemap-mcp`;
do not point the Linux client at Windows token files.

## Client help

**Codex:** Connect uses the Codex command-line tool if available. If it is absent,
the window prints the exact executable path for manual setup. In the app, choose
**Settings → MCP servers → Add server**, use name `battlemap`, transport
**STDIO**, and paste that path into **Command**. Leave arguments empty, save, and
restart the connection. No separate runtime installation is needed. This manual
route follows [OpenAI's instructions](https://developers.openai.com/codex/mcp/).

**Claude Code:** Connect uses the `claude` command-line tool. It does not configure
the Claude chat app. Running Connect again at the same location is harmless.
If an existing user entry points to an older companion, remove that one entry
before running Connect again:

```text
claude mcp remove --scope user battlemap
```

Keep the previous companion until replacement setup succeeds. Setup does not
silently remove a different registration. If the `claude` command is missing,
finish installing Claude Code, reopen the Connect file, and try again.

**Other MCP clients:** add a local STDIO server named `battlemap`, with the
companion executable's full path as the command and no arguments. Your client
starts it for you. See [technical configuration](TECHNICAL_REFERENCE.md).

## Update or remove

**Update:** save your map and quit Dungeondraft and the AI client. Download both
packages from the same release. Move the old bridge outside all active mods
folders and replace it with the new one. Replace the **entire** companion folder;
do not mix a new executable with old `_internal` files. Keeping the same permanent
path means the existing registration still works. Run the Connect file again,
reopen Dungeondraft and a map, and run Check connection.

Connect preserves existing skills. To replace locally edited or older skills too,
open a terminal in the companion folder and run:

```powershell
.\battlemap-mcp.exe setup --force --client codex
```

On Mac or Linux use `./battlemap-mcp`; for Claude Code use `--client claude-code`.
Replaced skills are backed up outside the client's active skills folder.
`--force` applies to skills, not an existing Claude registration.

**Move:** after moving the whole companion folder, run Connect from the new
location. Use the Claude removal step above if applicable. Keep the old copy
until the new connection works.

**Roll back:** restore the mod and complete companion from the same older
release, reconnect, and restart Dungeondraft. There is no background updater.

**Remove:** quit the editor and disconnect the server. Remove the `battlemap`
entry in your AI client's MCP settings, then remove the mod and companion folders
you installed. Bundled `battlemap-*` skills and this integration's runtime
state can be removed separately; retain wanted captures. Leave other mods and
Dungeondraft's settings and permissions alone.

## Diagnostics and privacy

For detailed technical output, run the companion with `doctor --live`. It checks
both installed files and the authenticated running script. A ZIP installation
does not need an installer record. The loaded root identifies which copy is
running when there are duplicates.

The bridge stores credentials and captures in its own private runtime directory.
It does not change permissions on Dungeondraft's folders. See
[state migration](PRIVACY.md#state-directory-migration) for older installations.
For startup problems, read the current `Dungeondraft.log`; timestamped logs may
be archives of an earlier session.

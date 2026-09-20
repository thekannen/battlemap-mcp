# Developer installation from source

Contributors can use [uv](https://docs.astral.sh/uv/getting-started/installation/)
and an authorized checkout. These commands are for development, not the normal
release install. Install uv first and open a shell that can find it.

From the checkout root:

```text
uv build --wheel ./server --out-dir ./dist
uv tool install --python 3.11 --force --reinstall ./dist/battlemap_mcp-0.2.0-py3-none-any.whl
uv tool update-shell
```

Use the wheel filename actually produced. If uv cannot provision Python, resolve
its reported error first; `uv python install 3.11` explicitly installs the requested
version. Reopen your shell/application after a PATH change. The release companion
avoids these prerequisites.

With Dungeondraft closed and a writable mods folder configured, either extract
the release mod ZIP and run `battlemap-mcp setup --client codex`, or use the
combined developer installer:

```text
battlemap-mcp install --dry-run --client codex
battlemap-mcp install --client codex
```

Use `--client claude-code` for Claude Code. To replace existing bridge/skills,
add `--force` to preview and install; the installer keeps dated backups outside
active discovery folders. It checks destination access before asking for
confirmation, though permissions can still change between preview and writing.
It neither silently selects another directory nor changes Dungeondraft ACLs.

Use a persistent tool launcher, not a disposable `uvx` cache environment. For
updates, pull the intended revision, rebuild/reinstall its wheel, then replace
the matching mod before restarting Dungeondraft and reconnecting the MCP client.
Nothing automatically updates during normal startup.

See [Building and releasing packages](releases.md) for versioning and Actions.

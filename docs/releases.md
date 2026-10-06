# Building release packages

Releases are published on GitHub from a version tag. The workflow builds the Windows and Linux companions, the mod, and the wheel into a draft release. The macOS companions (Apple Silicon and Intel), and the Claude bundle that carries all four companions, are built, signed, and notarized on a Mac by the maintainer and attached to the draft before it is published. Nothing is published to a package index. Windows companions are unsigned; their launcher is pinned across releases.

## Versions and local builds

Keep Python, mod, and plugin versions aligned; `set-version` also points the plugin at that version's bundle. From the repository root:

```text
python tools/release.py check
python tools/release.py set-version 1.0.0
python tools/release.py check --tag v1.0.0
python tools/release.py build --out dist/release --companion --tag v1.0.0
```

Use the intended version consistently; the version above is an example. The builder uses an isolated build environment and requires network access for dependencies. Build each companion on its target OS/architecture. Resulting companions start without downloading a runtime.

Outputs include a universal `battlemap-mcp-mod-<version>.zip`, a Python wheel, the native `battlemap-mcp-companion-<version>-<platform>` archive, and `SHA256SUMS`. Windows uses ZIP; macOS/Linux use tar.gz to preserve executable permissions and symlinks. Keep the complete extracted companion folder together.

After extracting an archive, run:

```text
python tools/release.py smoke PATH_TO_EXTRACTED_EXECUTABLE
```

This checks version, bundled payload identity, and MCP startup/tool discovery. It does not establish live editor acceptance, signing, or reproducible binary output. Retain the dependency inventory and test the exact downloaded files.

## Hosted builds

The workflow checks the repository identity, versions, and the offline gate, then builds Windows x64 and Linux x64 companions. Each archive is extracted and smoke-tested before the assets are assembled with `SHA256SUMS`.

Manual workflow dispatch produces artifacts retained for 14 days. Pushing a matching version tag also creates a draft release. Only that draft job has repository write permission, and it does not run repository code. The draft is never published automatically, and existing releases are not overwritten.

## The Windows launcher

The Windows companion is a small launcher, `battlemap-mcp.exe`, with the Python program beside it in `battlemap-mcp.pkg`. Every release ships the **same launcher bytes**, recorded in `packaging/windows-launcher.json`, so the antivirus reputation and Microsoft clearance a launcher earns carry over from release to release instead of starting again with each new build. Only the `.pkg` changes per release.

Whenever a launcher is pinned, the Windows build downloads it, checks its SHA-256, and puts it in place of the one it just compiled; the extracted archive's smoke test checks the hash again. On a tag push the workflow also refuses to build when no launcher is pinned, so the first launcher of a generation must be published, and its pin committed, before the release that ships it is tagged.

A launcher changes only when PyInstaller is upgraded, because a launcher runs only its own PyInstaller's `.pkg` format. To publish one (for a generation already set in `packaging/windows-launcher.json`, start at step 2):

1. For a new generation, raise `pyinstaller` in `packaging/build-requirements.txt`, and in `packaging/windows-launcher.json` set the same `pyinstaller`, raise `generation`, and clear `sha256` and `url` to `null`.
2. Run the release workflow manually. Download the `windows-launcher-candidate` artifact, which holds the launcher and its `SHA256`.
3. Scan it with VirusTotal. If Microsoft flags it, submit it to Microsoft as a false positive and wait for the clearance.
4. Publish it as a prerelease, so the update check never reports it:

   ```text
   gh release create windows-launcher-N battlemap-mcp.exe --prerelease --title "Windows launcher N" --notes "Pinned launcher for releases built with PyInstaller X.Y.Z."
   ```

5. Record its `sha256` and download `url` in `packaging/windows-launcher.json`, and commit. Tagged builds then ship exactly this file.

## Adding the macOS companions

Both macOS companions are built on an Apple Silicon Mac from the tagged commit, with a Developer ID Application certificate and a `notarytool` keychain profile. The Intel build runs under Rosetta with an x86_64 Python 3.11 or newer, for example one installed with `uv python install cpython-3.11-macos-x86_64-none`:

```text
python3 tools/release.py build --out dist/macos-arm64 --companion --tag v1.0.0 --sign-identity "Developer ID Application: NAME (TEAMID)" --notary-profile PROFILE
arch -x86_64 PATH_TO_X86_64_PYTHON tools/release.py build --out dist/macos-x64 --companion --tag v1.0.0 --sign-identity "Developer ID Application: NAME (TEAMID)" --notary-profile PROFILE
```

On Intel the builder pins `cryptography` below 49, the last series with Intel macOS wheels.

Quarantine a fresh extraction of each and confirm it launches with no workaround. Then add both archives to the draft and regenerate the checksums:

```text
gh release download v1.0.0 --dir dist/publish
cp dist/macos-*/battlemap-mcp-companion-1.0.0-macos-*.tar.gz dist/publish/
```

Then add the Claude bundle below before regenerating the checksums and uploading.

## Adding the Claude bundle

`battlemap-mcp-<version>.mcpb` is both the Claude Desktop extension and the MCP server of the Claude Code plugin. It carries all four companions, so build it on the Mac once the macOS archives are in `dist/publish`:

```text
python3 tools/release.py mcpb --companions dist/publish --out dist/mcpb --tag v1.0.0 --sign-identity "Developer ID Application: NAME (TEAMID)" --notary-profile PROFILE
cp dist/mcpb/battlemap-mcp-1.0.0.mcpb dist/publish/
(cd dist/publish && shasum -a 256 *.zip *.tar.gz *.whl *.mcpb > SHA256SUMS)
gh release upload v1.0.0 dist/publish/battlemap-mcp-companion-1.0.0-macos-*.tar.gz dist/publish/battlemap-mcp-1.0.0.mcpb dist/publish/SHA256SUMS --clobber
```

The builder replaces the archives' symlinks with real files, because a client's extraction does not keep them, then re-signs and notarizes the macOS copies, and starts the companion for this Mac from a plain unzip of the finished bundle. `--allow-unnotarized` makes a local test bundle that must never be published.

`.claude-plugin/plugin.json` names the bundle by its release URL, and `release.py set-version` keeps it current. That URL only works once the release is published, so `main` must not reach users before then: push the version commit on a release branch, tag it there, and fast-forward `main` to it only after publishing.

## Before publishing

1. Set the CHANGELOG heading's date before tagging: the release page's notes are built from the tagged commit, and an undated heading is refused.
2. Scan every download with VirusTotal, including the `.mcpb`, and the Windows launcher and `battlemap-mcp.pkg` inside the Windows ZIP. Fix a detection at its source before publishing.
3. Install the exact draft downloads on each platform, connect a client, and run a live map check, including save and reopen. Install the downloaded `.mcpb` in Claude Desktop and connect it from a cold start.
4. Publish the draft. Then install the plugin in Claude Code from the release branch and connect it from a cold start: its bundle URL works only now. Only then fast-forward `main` to the tagged commit, which is what plugin users receive.

## Release order at a glance

1. If the launcher's pin is empty, publish the launcher first (see The Windows launcher).
2. Commit the version and dated CHANGELOG on a release branch, and push a `v` tag there; the workflow builds the draft.
3. Add the macOS companions and the Claude bundle, and regenerate `SHA256SUMS`.
4. Run the checks above, publish, and fast-forward `main`.

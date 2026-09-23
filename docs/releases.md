# Building release packages

Releases are published on GitHub from a version tag. The workflow builds the Windows and Linux companions, the mod, and the wheel into a draft release. The macOS companions (Apple Silicon and Intel) are built, signed, and notarized on a Mac by the maintainer and attached to the draft before it is published. Nothing is published to a package index. Windows companions are unsigned.

## Versions and local builds

Keep Python, mod, and plugin versions aligned. From the repository root:

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
cd dist/publish && shasum -a 256 *.zip *.tar.gz *.whl > SHA256SUMS
gh release upload v1.0.0 battlemap-mcp-companion-1.0.0-macos-*.tar.gz SHA256SUMS --clobber
```

## Before publishing

Install the exact draft downloads on each platform, connect a client, and run a live map check, including save and reopen. Then publish the draft.

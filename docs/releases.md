# Building candidate packages

This workflow builds unsigned private candidate packages for `thekannen/battlemap-mcp`. It does not publish public releases or package-index distributions, sign Windows binaries, or sign/notarize macOS binaries. Changing repository visibility does not enable publication: the workflow refuses to build in a public repository. A future public workflow requires separate authorization, permission review, signing, and package acceptance.

## Versions and local builds

Keep Python, mod, and plugin versions aligned. From the repository root:

```text
python tools/release.py check
python tools/release.py set-version 0.2.1
python tools/release.py check --tag v0.2.1
python tools/release.py build --out dist/candidate --companion --tag v0.2.1
```

Use the intended version consistently; the version above is an example. The builder uses an isolated build environment and requires network access for dependencies. Build each companion on its target OS/architecture. Resulting companions start without downloading a runtime.

Outputs include a universal `battlemap-mcp-mod-<version>.zip`, a Python wheel, the native `battlemap-mcp-companion-<version>-<platform>` archive, and `SHA256SUMS`. Windows uses ZIP; macOS/Linux use tar.gz to preserve executable permissions and symlinks. Keep the complete extracted companion folder together.

After extracting an archive, run:

```text
python tools/release.py smoke PATH_TO_EXTRACTED_EXECUTABLE
```

This checks version, bundled payload identity, and MCP startup/tool discovery. It does not establish live editor acceptance, signing, or reproducible binary output. Retain the dependency inventory and test the exact downloaded files.

## Hosted candidate builds

The package workflow first checks the repository identity and its current private visibility through GitHub's API. It checks versions and runs the offline gate before building Windows x64, macOS Intel, macOS Apple Silicon, and Linux x64 companions. Each native archive is extracted and smoke-tested before its assets are assembled with checksums.

Manual workflow dispatch produces artifacts retained for 14 days. A matching version-tag push additionally creates a draft prerelease, with a second identity/privacy check immediately before creation. Only that draft job has repository write permission; it does not run repository code. The release stays a draft and is never promoted automatically. Existing releases are not overwritten.

## Acceptance before distribution

Run clean install, update, rollback, removal, client connection, and live map checks against each exact candidate package. Include map persistence and image review where applicable. Record OS/architecture, editor, client, model, package hashes, and results. Earlier results from differently named artifacts do not satisfy this candidate's acceptance.

Public distribution remains a separate decision. Complete rights/permission review, Windows signing, Apple signing/notarization, hosted checks, final live UAT, and a security review of any publishing permissions before authorizing a public workflow. Do not reuse artifacts from unrelated repositories.

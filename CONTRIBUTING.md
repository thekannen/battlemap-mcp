# Contributing

This repository contains the battlemap-mcp candidate: a Python MCP companion and a Dungeondraft bridge mod. Start with the [technical reference](docs/TECHNICAL_REFERENCE.md) and [developer installation](docs/developer-installation.md).

## Local checks

Use Python 3.11 or newer. From the repository root, in an activated virtual environment:

```text
python -m pip install -e "./server[dev]"
python server/tools/gate.py
python tools/release.py check
python -m ruff check tools/release.py tools/collect_release.py
python -m ruff format --check tools/release.py tools/collect_release.py
```

The gate runs formatting, lint, types, tests, bridge checks, and skill checks. Its `--quick` option is useful during iteration but does not replace the full gate. CI also checks Python 3.11 and 3.12 on Windows, macOS, and Linux.

## Live testing

Offline tests cannot establish editor compatibility. Use a separate Dungeondraft instance and a disposable map you own. Read each live check's `--help` before running it; the map-name guard must identify that scratch map. The available runners are `server/tools/uat.py`, `server/tools/verify_live.py`, and `server/tools/verify_transport.py`.

After a bridge change, restart the disposable editor, check authenticated `ping` identity and protocol, then confirm `get_status` reports the intended map. Review screenshots and saved/reopened results where the change affects appearance or persistence. Report the exact OS, package, client, editor version, and checks performed. Do not describe a platform as accepted based on another platform's results.

## Changes

Keep changes focused, include behavioral regression coverage where appropriate, and describe validation and remaining limits. Do not include asset packs, maps, credentials, machine-specific paths, or research records. Follow the [code of conduct](CODE_OF_CONDUCT.md); report security problems through [SECURITY.md](SECURITY.md).

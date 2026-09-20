# Security policy

## Supported development line

Security fixes target `main`. This repository currently contains a private
candidate; its packages are not approved public releases. See the
[known limitations](docs/KNOWN_LIMITATIONS.md) for acceptance status.

## Report a vulnerability

Do not disclose exploit details in a public issue. While this candidate is
private, contact the maintainer through the existing private channel used to
arrange access. Private vulnerability reporting is not currently available for
this repository.

After public release, if private vulnerability reporting has been enabled, use
[Report a vulnerability](https://github.com/thekannen/battlemap-mcp/security/advisories/new).
Until then, use the existing private channel rather than assuming that link works.

Include the affected version and component, operating system, reproduction
steps, and relevant redacted logs. Never include authentication tokens, private
maps, or licensed assets without permission. The maintainer will coordinate
assessment, a fix, and disclosure; no response deadline is guaranteed.

## Disclosure approach

Handle findings privately when they could extend an attacker's access, such as
exposure beyond localhost, credentials readable by another OS user, arbitrary
file access, or execution of untrusted input. If the impact is unclear, begin
privately. A private report can be disclosed later.

Bugs that do not extend an attacker's existing privileges can be discussed as
ordinary issues after review. Document data-loss defects promptly in user-facing
limitations and release notes; report privately first if they also have a
security impact. Private candidate status does not authorize public disclosure.

## Security boundary

The companion communicates with the MCP client over standard input/output.
The bridge listens on localhost TCP and authenticates commands and responses;
it does not encrypt traffic. Do not expose its port beyond localhost. This is
a local, single-user integration and does not protect against administrators or
malicious software running as the same OS user. See the
[protocol](docs/PROTOCOL.md) and [privacy policy](docs/PRIVACY.md).

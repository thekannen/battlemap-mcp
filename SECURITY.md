# Security policy

## Supported versions

Security fixes target `main` and ship in the next release. Use the latest
release.

## Report a vulnerability

Do not disclose exploit details in a public issue. Report privately through
[Report a vulnerability](https://github.com/thekannen/battlemap-mcp/security/advisories/new)
(the repository's **Security** tab).

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
security impact.

## Security boundary

The companion communicates with the MCP client over standard input/output.
The bridge listens on localhost TCP and authenticates commands and responses;
it does not encrypt traffic. Do not expose its port beyond localhost. This is
a local, single-user integration and does not protect against administrators or
malicious software running as the same OS user. See the
[protocol](docs/PROTOCOL.md) and [privacy policy](docs/PRIVACY.md).

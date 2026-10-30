# Security Policy

MCP Hub runs locally and handles credentials: tokens in the keychain (macOS keychain, Secret Service on Linux, Credential Manager on Windows), OAuth access and refresh tokens, and references to 1Password. Reports about anything that could expose those, or let another website or process control the hub, are very welcome.

## Reporting a vulnerability

Please do **not** open a public issue. Use GitHub’s private reporting instead:

**[Report a vulnerability](https://github.com/endorfin/mcp-hub/security/advisories/new)**

Include what you found, how to reproduce it and which version or commit you tested. You will get an answer as soon as possible; fixes are released with a note in the advisory.

## Scope

In scope, for example:

- Secrets ending up in plain text (`servers.json`, logs, the call log, API responses)
- Bypassing the origin check or reaching the hub from outside `127.0.0.1`
- Weaknesses in the OAuth flow (state, PKCE, token storage, redirect handling)
- Anything that lets a web page or another local user trigger actions in the hub
- The update mechanism: installing code from anywhere other than the releases of `endorfin/mcp-hub`, or writing outside the program folder

Out of scope: vulnerabilities in the MCP servers you connect to the hub, and attacks that already require full control of your user account.

## Supported versions

Only the latest commit on `main` and the latest release receive fixes.

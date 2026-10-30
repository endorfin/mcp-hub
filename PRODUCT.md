# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Developers who work with several AI clients (Claude Code, Claude Desktop, VS Code/Copilot) and many MCP servers. Their job: maintain each server once instead of managing the same entries, tokens and paths in every client separately, and see at any time which tools are active and who uses them.

The project is open source. The interface runs locally on the user’s own machine at `http://127.0.0.1:4747`.

## Product Purpose

MCP Hub is a local hub for MCP servers: it starts local (stdio) servers, connects remote (Streamable HTTP, SSE) servers and serves all of them bundled behind a single MCP endpoint. A web interface for managing, testing and observing comes with it.

Success means: every client needs exactly one entry (`mcp-hub`), new servers are available everywhere immediately, and no plain-text tokens remain in configuration files.

## Positioning

One local endpoint for all clients instead of per-client configuration, with no dependencies besides Python. The hub is management (GUI, profiles, tool selection), test bench (inspector) and observation (call log with client attribution, live clients) at once. Clients learn about changes live via `list_changed`, Claude Desktop included through the bundled stdio bridge.

## Operating Context

- Runs permanently in the background, started via `autostart.sh` (LaunchAgent) or a tool of the user’s choice; the GUI is opened now and then, often next to a terminal and an editor.
- Typical tasks: add or import a server, store a token in the keychain, deselect a server’s tools, switch between profiles, test a server in the inspector, look up in the log which agent called which tool when.
- Configuration lives outside the repository in `~/.config/mcp-hub/` (`servers.json`, `profiles.json`, `usage.json`, `calls.jsonl`, `clients.json`).
- Clients: Claude Code (HTTP), VS Code/Copilot (HTTP), Claude Desktop (stdio via `bridge.py`), any other MCP client via `/mcp` or `/p/<profile>/mcp`.

## Capabilities and Constraints

- Python 3.11+ without third-party packages; server and GUI in one process (`app.py`), interface as a single file (`index.html`) without a build step.
- Local only: listens on `127.0.0.1`, rejects write requests with a foreign `Origin`.
- Tool and prompt names carry the server name as a prefix (`server__tool`), titles read `server: Name`.
- Secrets as references: `${keychain:…}` (macOS keychain) and `${op://…}` (1Password CLI).
- OAuth for remote servers per the MCP specification (discovery, automatic client registration, PKCE), also with fixed client credentials; tokens in the keychain, refreshed automatically.
- Statistics over the last 5,000 calls: key figures, daily history, per server, slowest tools.
- Profiles store on/off and deselected tools per server; every profile has its own endpoint.
- macOS is the only tested platform (keychain, LaunchAgent).
- License: MIT. Interface in German and English (selectable in Settings, default: browser language); README, design documents and messages from hub and API in English.
- **Open:** support for Linux and Windows.

## Brand Commitments

- Name: **MCP Hub**.
- No tie to a personal tool: project files do not assume a particular launcher.

## Evidence on Hand

- Working implementation with tests (`tests/`, smoke tests including the bridge, a hub restart and the complete OAuth flow).
- README with entry formats, client setup, API and troubleshooting.
- There are no user numbers, testimonials, marketing screenshots or release notes; do not invent any.

## Product Principles

1. **Maintain in one place.** Every setting exists exactly once in the hub; clients only get the endpoint.
2. **Visible, not guessed.** What runs, what is deselected, who is connected and who calls what is shown in the interface, not buried in log files.
3. **No secrets in plain text.** Tokens belong in the keychain or a password manager; files only hold references.
4. **No baggage.** No dependencies, no build, one process; new features must stay within that frame.
5. **Changes take effect immediately.** Saving syncs the hub, clients are notified live, restarts only where needed.

## Accessibility & Inclusion

Keyboard operable (custom listboxes and menus with arrow keys, Enter, Esc), visible focus rings, roles and labels for screen readers, light and dark color scheme following the system setting, interface in German and English.

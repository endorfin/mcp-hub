# MCP Hub

A local hub for MCP servers: manage all your servers in one place, test them, and serve them bundled behind a single endpoint to Claude Code, Claude Desktop, Copilot and other clients.

```bash
python3 app.py   # GUI: http://127.0.0.1:4747, hub: http://127.0.0.1:4747/mcp
```

No dependencies besides Python 3.11+. The server only listens on `127.0.0.1`. The interface is available in English and German (see “GUI”).

## Files

Everything lives in `~/.config/mcp-hub/` (override with `MCP_HUB_HOME`), not in the repository. An old `~/.config/mcp-proxy/` folder is moved there on first start; `MCP_PROXY_GUI_HOME` still works.

| File | Contents |
| --- | --- |
| `servers.json` | Server definitions in `mcpServers` format; `servers.json.bak` is written before every change |
| `gui-settings.json` | Path to the server file, `passEnvironment`, `language` |
| `usage.json` | Usage counter per server (count, last call) |
| `calls.jsonl` | Call log, the last 5,000 entries |
| `profiles.json` | Saved profiles and the active profile |
| `clients.json` | Session ID → client mapping, the last 300 sessions |

Tokens either sit in `servers.json` or, better, as a reference to the keychain or 1Password (see “Secrets”). `servers.json` does not belong in a repository.

## Server entries

Local commands (stdio):

```json
"grafana": { "command": "uvx", "args": ["mcp-grafana"], "env": { "GRAFANA_URL": "…" } }
```

Remote servers via Streamable HTTP or SSE:

```json
"timing-sync-mcp": { "type": "http", "url": "https://…/mcp", "headers": { "Authorization": "Bearer …" } },
"openbrain": { "type": "sse", "url": "http://…/sse?key=…" }
```

An entry with `url` and no `type` is treated as Streamable HTTP. Optional fields:

- `description`: what the server is for, shown in the GUI only. Without it, the GUI shows the server’s own description or its first tools.
- `enabled: false`: the server stays in the list, but the hub does not start it.
- `disabledTools`: list of tool names (without prefix) that the hub hides and refuses to call. Easiest to manage via ⋯ → “Choose tools…”: the dialog lists all tools with a short description, can be filtered, and “All on” / “All off” only affect the filtered tools (e.g. filter “incident”, then “All off”). The list then shows a chip in orange text, e.g. “6 tools disabled”; its tooltip names the tools and a click opens the dialog. A change does not restart the server.
- `env` (stdio) or `headers` (HTTP/SSE).

### OAuth

Remote servers that require OAuth only need their URL; no token in a header is needed. When the server answers `401`, the list shows “Sign-in required – sign in”. A click opens the provider’s sign-in page in a new window.

The flow follows the MCP specification: the hub discovers the authorization server via Protected Resource Metadata (RFC 9728) and Authorization Server Metadata (RFC 8414), registers itself as a client (RFC 7591) and signs in using the authorization code flow with PKCE (S256) and the `resource` parameter. The provider redirects back to `http://127.0.0.1:4747/oauth/callback`.

- Access and refresh tokens are stored in the macOS keychain under `mcp-hub/oauth/<server>`, never in `servers.json`.
- When a token expires, the hub fetches a new one with the refresh token and retries the call; clients never notice.
- Signed-in servers carry an “OAuth” chip (tooltip: validity). ⋯ → “Sign out” deletes the token.
- If the entry already has an `Authorization` header, the hub uses it instead of OAuth.

**Providers without automatic registration** (e.g. GitHub): create an OAuth app with the provider, set `http://127.0.0.1:4747/oauth/callback` as its callback URL and enter the client ID (and secret, if required) in the editor under “OAuth”. The lock moves the secret into the keychain. If the provider offers no discovery, add the authorization and token URLs:

```json
"github": {
  "type": "http",
  "url": "https://api.githubcopilot.com/mcp/",
  "oauth": { "clientId": "Iv1.…", "clientSecret": "${keychain:github/oauth-client-secret}", "scopes": "repo read:user" }
}
```

Available fields: `clientId`, `clientSecret`, `scopes`, `authorizationUrl`, `tokenUrl` and `tokenAuth` (`client_secret_post`, the default, or `client_secret_basic`). If a provider without registration is missing a client ID, the error message on sign-in explains what to do.

### Secrets

Instead of plain-text tokens, values in `env`, `headers`, `url` and `args` can contain references that the hub only resolves when it starts a server:

```json
"glitchtip": { "type": "http", "url": "https://…/mcp", "headers": { "Authorization": "${keychain:glitchtip/Authorization}" } },
"grafana": { "command": "uvx", "args": ["mcp-grafana"], "env": { "GRAFANA_SERVICE_ACCOUNT_TOKEN": "${op://Private/Grafana/token}" } }
```

The notation alone decides the source, per value. There is no setting and no fallback: if `op` is not signed in, the hub does not look in the keychain instead. A server may mix both sources.

- `${keychain:name}` reads the macOS keychain (account `mcp-hub`, service `mcp-hub/<name>`; searching for `mcp-hub` in Keychain Access lists all entries). The easiest way is the lock next to a value in the editor: it creates the entry and replaces the value with the reference; nothing is written to the file until you click “Save”. By hand: `security add-generic-password -a mcp-hub -s mcp-hub/<name> -w`. Printable ASCII values only; `security` returns anything else as hex.
- `${op://vault/item/field}` reads via the 1Password CLI (`op read`). `op` must be signed in within the hub’s environment, e.g. through the 1Password app integration. The hub never writes to 1Password; the lock always writes to the keychain. Useful for tokens that are already maintained, shared or rotated in 1Password; otherwise the keychain is simpler.
- References may be part of a longer value, such as `Bearer ${keychain:…}` or `?key=${keychain:…}`.
- Resolved values stay in memory until the hub restarts. After changing a value in the keychain or 1Password, restart the hub (e.g. `./autostart.sh restart`); switching the server off and on is not enough. Only the lock in the GUI refreshes its own entry immediately.
- If an entry is missing, the server does not start. The tooltip on the status chip then shows e.g. “Secret: No keychain entry …”.

With `passEnvironment` (Settings), local servers inherit the hub’s environment; otherwise they only get `env`.

## Hub

At `/mcp`, the hub bundles all enabled servers into one MCP endpoint (Streamable HTTP, JSON responses).

- **Names:** tools and prompts get the server name as a prefix (`grafana__query_loki_logs`); resources keep their URI.
- **Titles:** every tool gets the title `server: Name`. Claude Desktop only shows the title in its connector permissions, so you can still tell which server a tool belongs to.
- **Changes:** saving in the GUI syncs the hub immediately. Only servers whose command, URL, headers or environment changed are restarted. Changing just the description restarts nothing.
- **Processes:** local servers run in their own process group. On shutdown, the hub cleans up the whole group, child processes included.
- **Working directory:** local servers run in the hub folder, so tools that expect a project path need an absolute path.
- **Security:** write requests (`POST`, `PUT`) with a foreign `Origin` header are rejected, for the MCP endpoint and the GUI API alike (protection against DNS rebinding and CSRF).
- **Messages:** error messages from the hub and its API are in English, since agents read them too. The GUI translates the common ones when German is selected.

### Connecting clients

Claude Code:

```bash
claude mcp add --scope user --transport http mcp-hub http://127.0.0.1:4747/mcp
```

Copilot / VS Code (`~/.copilot/mcp-config.json`):

```json
{ "mcpServers": { "mcp-hub": { "type": "http", "url": "http://127.0.0.1:4747/mcp", "tools": ["*"] } } }
```

Claude Desktop can only start local commands. For that, the repository ships `bridge.py`, a dependency-free bridge from stdio to the hub (`~/Library/Application Support/Claude/claude_desktop_config.json`; the GUI shows the matching snippet with absolute paths below the server list):

```json
{ "mcpServers": { "mcp-hub": { "command": "/opt/homebrew/bin/python3", "args": ["/path/to/mcp-hub/bridge.py", "http://127.0.0.1:4747/mcp"] } } }
```

The bridge forwards the hub’s notifications to Claude Desktop and re-initializes on its own after the hub restarts. If the hub is not reachable, it answers requests with an error instead of hanging. [mcp-proxy](https://github.com/sparfenyuk/mcp-proxy) works as well but does not forward notifications.

### Live updates

When the tool list changes (server on/off, tools deselected, profile switched, a server reports new tools itself), the hub sends `notifications/tools/list_changed` (likewise for prompts and resources). Clients receive it over an open SSE stream (`GET /mcp` with `Accept: text/event-stream`) that they open right after `initialize`.

- **Claude Code and VS Code/Copilot** support this. Changes arrive without reconnecting.
- **Indicator:** the GUI header counts the clients with an open stream (“· 2 clients”); the tooltip names them.
- **Claude Desktop** via `bridge.py`: the bridge keeps the stream open and forwards the notifications. With mcp-proxy as the bridge they are lost, and only restarting Claude Desktop helps.
- **Hub restart:** sessions only last until the hub restarts. Afterwards, the hub answers old session IDs with `404` and clients initialize again (as the MCP specification requires). `DELETE /mcp` ends a session.

## Autostart

For Claude Code, Claude Desktop and Copilot to have their tools after a reboot, the hub needs to start at login. `autostart.sh` sets up a LaunchAgent (`~/Library/LaunchAgents/io.github.endorfin.mcp-hub.plist`) that runs `python3 app.py` and restarts it after a crash:

```bash
./autostart.sh install     # set up and start right away
./autostart.sh status      # set up? is the hub running?
./autostart.sh restart     # restart the hub, e.g. after a keychain change
./autostart.sh uninstall   # remove and stop the hub
```

Log: `~/Library/Logs/mcp-hub.log`. The path to `python3`, `PATH` and `PORT` are captured at install time; after moving the repository or installing a new Python, run `install` again. If a hub is already running on the port, the script aborts instead of starting a second one.

## GUI

Design rules and components of the interface are documented in [DESIGN.md](DESIGN.md); audience, purpose and principles of the product in [PRODUCT.md](PRODUCT.md).

- **Servers:** list with on/off switch, hub status per server (tools, errors), usage, and sorting by recently used, name or file order in both directions. The ⋯ menu inspects a server, chooses its tools for the hub, edits, duplicates and deletes it. Import accepts `mcpServers` JSON from other configurations.
- **Log:** every call through the hub with time, client, server, tool, arguments, result preview, duration and error status. Filter by server, client and errors.
- **Inspector:** connects directly to a server (independent of the hub) and lists tools, resources, templates and prompts. Everything can be called with form or JSON input; stderr and notifications appear below.
- **Settings:** path to the server file, language, `passEnvironment`, and below that the complete `mcpServers` definition as JSON for direct editing.

**Language:** English or German, chosen under Settings → Language. “Automatic (browser)” follows the browser language. The choice is stored in `gui-settings.json`; it also decides the language of the OAuth return page.

### Profiles

A profile remembers, per server, whether it is enabled and which tools are deselected. It lets you switch quickly between setups, such as “Frontend” with nuxt, nuxt-ui and chrome-devtools, or “Ops” with grafana and glitchtip.

- **Save:** set up servers and tools, then ⋯ → “Save as new profile…” at the top.
- **Switch:** open the profile picker at the top (with search field, arrow keys and Enter) and choose a profile. The hub writes on/off and `disabledTools` to `servers.json`, starts or stops the affected servers and hides tools. Connected clients receive the new tool list automatically (see “Live updates”).
- **Modified:** when the current state differs from the active profile, the picker shows an orange dot (tooltip: unsaved changes). ⋯ → “Update …” stores the current state in the profile. Switching with unsaved changes asks first.
- **No profile:** turns on all servers and enables all tools (removes every `disabledTools`), even if “No profile” is already selected. Clicking a modified profile again resets it to its saved state.
- **New servers:** servers a profile does not know are left unchanged by a switch. “Update” adds them to the profile.
- **Manage:** under ⋯ → “Manage profiles…”, each profile has its own ⋯ menu: copy URL, activate, rename and delete, without applying it first. Clicking the URL copies it as well. Servers and tools stay as they are. Names must not contain `/`.

The profile selected at the top applies to the whole hub, i.e. to all clients on the default endpoint `/mcp`.

**Endpoint per profile:** each profile is also available at `http://127.0.0.1:4747/p/<profile>/mcp` (copy the URL in “Manage profiles…”). A client there always sees that profile’s servers and tools, regardless of which profile is active at the top. That way, Copilot can work with “Frontend” only while Claude Code gets everything:

```bash
claude mcp add --scope user --transport http mcp-hub-frontend http://127.0.0.1:4747/p/Frontend/mcp
```

The profile endpoint only filters: servers switched off in the hub are missing there too. Servers the profile does not know appear with their current setting. The log shows the profile after the client, e.g. `claude-code · Frontend`.

### Statistics

Above the call log, a collapsible statistics panel shows key figures (calls, error rate, typical duration, clients), calls per day for the last 14 days including errors, a table per server (calls, errors, median, p95, last call; a click filters the log) and the five slowest tools by p95. It is based on the last 5,000 calls in `calls.jsonl`.

### Usage and call log

Only real calls are counted (`tools/call`, `prompts/get`, `resources/read`), not list requests. In the log, arguments are truncated to 4,000 and results to 600 characters.

The hub identifies the client from `clientInfo` during `initialize` and assigns it an `Mcp-Session-Id`. Requests without a session ID appear as `<user agent> (no session)`.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/state` | Configuration and settings |
| `PUT` | `/api/servers` | Save `{"mcpServers": {…}}` and sync the hub |
| `PUT` | `/api/settings` | Save settings |
| `GET` | `/api/hub` | Status per server (state, error, number of tools/prompts/resources, OAuth status) |
| `GET` | `/api/hub/tools?name=` | All tools of a server with their `enabled` state |
| `GET` | `/api/live` | Clients with an open notification stream |
| `GET` | `/api/usage` | Usage counter |
| `GET` | `/api/calls?limit=300` | Recent calls (max. 1,000) |
| `GET` | `/api/stats?days=14` | Call statistics (key figures, per day, per server, slowest tools) |
| `POST` | `/api/oauth/start` | `{"name"}`: start sign-in, returns the sign-in page `{"url"}` |
| `POST` | `/api/oauth/logout` | `{"name"}`: delete the token |
| `GET` | `/oauth/callback` | Return from the authorization server |
| `POST` | `/api/profiles` | `{"action": "save" \| "apply" \| "rename" \| "delete" \| "clear", "name", "newName"}`; `clear` enables everything |
| `POST` | `/api/secrets` | Store `{"name", "value"}` in the keychain, returns `{"ref"}` |
| `POST` | `/api/inspect/connect` | Open an inspector session (`{"name": …}`) |
| `POST` | `/api/inspect/call` | Send `{"name", "method", "params"}` to the server |
| `POST` | `/api/inspect/disconnect` | Close the session |
| `GET` | `/api/inspect/log?name=&since=` | stderr and notifications of the session |
| `POST` | `/mcp` | The hub’s MCP endpoint |
| `GET` | `/mcp` | SSE stream for notifications (`Accept: text/event-stream`) |
| `POST` | `/p/<profile>/mcp` | MCP endpoint with a fixed profile (`GET` for the stream as well) |

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests start their own hub with its own configuration folder on a free port and two instances of a small stdio server (`tests/dummy_server.py`). They cover prefixes and titles, sessions (404 after ending), the bridge including a hub restart, routing and logging, errors, `disabledTools`, profiles including profile endpoints, notifications, origin protection, statistics and (macOS only) keychain resolution, plus the complete OAuth flow against a test provider (`tests/dummy_oauth_server.py`: sign-in, refreshing an expired token, sign-out; once with automatic registration, once with a fixed client ID and secret). Your real configuration stays untouched; the keychain tests create `mcp-hub/selftest/hub-tests` and `mcp-hub/oauth/selftest-oauth` and delete them again.

## Troubleshooting

- **Server shows “error”:** hover over the status chip; the tooltip shows the error message including the last stderr line. For more detail, use the inspector, which starts the same entry directly.
- **Tool missing in the client:** is the server enabled and green in the hub? Then reconnect the client.
- **Orphaned processes:** processes left over after a client quits usually come from clients that only end the top-level process. The hub itself ends whole process groups. Check with `ps -axo pid,ppid,command | grep <server>`.
- **Port in use:** `lsof -iTCP:4747 -sTCP:LISTEN`. Set a different port with `PORT=…`, but then update the client URLs too.

## Roadmap

- **Linux and Windows:** secrets, OAuth tokens and autostart currently rely on the macOS keychain and LaunchAgents.
- **Profile endpoint starts servers on demand:** a server switched off in the hub is currently missing from profile endpoints as well.

## License

[MIT](LICENSE)

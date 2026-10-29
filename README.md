# MCP Hub

Lokaler Hub für MCP-Server: alle Server an einer Stelle pflegen, testen und gebündelt unter einem Endpunkt an Claude Code, Claude Desktop, Copilot & Co. ausliefern.

```bash
python3 app.py   # GUI: http://127.0.0.1:4747, Hub: http://127.0.0.1:4747/mcp
```

Keine Abhängigkeiten außer Python 3.11+.

- Server-Definitionen: `~/.config/mcp-proxy/servers.json` (Format `mcpServers`; vor jedem Schreiben entsteht `servers.json.bak`)
- Einstellungen: `~/.config/mcp-proxy/gui-settings.json`
- Nutzungszähler: `~/.config/mcp-proxy/usage.json`

## Server-Einträge

Lokale Befehle (stdio):

```json
"grafana": { "command": "uvx", "args": ["mcp-grafana"], "env": { "GRAFANA_URL": "…" } }
```

Entfernte Server per Streamable HTTP oder SSE:

```json
"timing-sync-mcp": { "type": "http", "url": "https://…/mcp", "headers": { "Authorization": "Bearer …" } },
"openbrain": { "type": "sse", "url": "http://…/sse?key=…" }
```

Optional: `description` (nur für die GUI) und `enabled: false`.

## Hub

Unter `/mcp` bündelt der Hub alle aktivierten Server zu einem MCP-Endpunkt (Streamable HTTP). Tool- und Prompt-Namen bekommen den Servernamen als Präfix (`server__tool`). Änderungen an der Serverliste greifen sofort. Lokale Server laufen im Hub-Ordner als aktuellem Verzeichnis; Tools mit Projektpfad brauchen daher einen absoluten Pfad.

```bash
claude mcp add --scope user --transport http mcp-hub http://127.0.0.1:4747/mcp
```

Claude Desktop kann nur lokale Befehle starten, deshalb dort [mcp-proxy](https://github.com/sparfenyuk/mcp-proxy) als Brücke:

```json
{ "mcpServers": { "mcp-hub": { "command": "/Users/<du>/.local/bin/mcp-proxy", "args": ["--transport", "streamablehttp", "http://127.0.0.1:4747/mcp"] } } }
```

## Inspector

Der Tab **Inspector** verbindet sich direkt mit einem Server (unabhängig vom Hub) und listet Tools, Resources, Templates und Prompts; alles lässt sich mit Formular- oder JSON-Eingabe aufrufen. stderr und Notifications des Servers erscheinen darunter.

`MCP_PROXY_GUI_HOME` verlegt das Konfigurationsverzeichnis, `PORT` den Port.

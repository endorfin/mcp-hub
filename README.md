# MCP Hub

Lokaler Hub für MCP-Server: alle Server an einer Stelle pflegen, testen und gebündelt unter einem Endpunkt an Claude Code, Claude Desktop, Copilot & Co. ausliefern.

```bash
python3 app.py   # GUI: http://127.0.0.1:4747, Hub: http://127.0.0.1:4747/mcp
```

Keine Abhängigkeiten außer Python 3.11+. Der Server lauscht nur auf `127.0.0.1`.

## Dateien

Alles liegt in `~/.config/mcp-proxy/` (änderbar per `MCP_PROXY_GUI_HOME`), nicht im Repo:

| Datei | Inhalt |
| --- | --- |
| `servers.json` | Server-Definitionen im Format `mcpServers`; vor jedem Schreiben entsteht `servers.json.bak` |
| `gui-settings.json` | Pfad zur Serverdatei, `passEnvironment` |
| `usage.json` | Nutzungszähler je Server (Anzahl, letzter Aufruf) |
| `calls.jsonl` | Aufrufprotokoll, die letzten 1.000 Einträge |
| `profiles.json` | gespeicherte Profile und das aktive Profil |
| `clients.json` | Zuordnung Sitzungs-ID → Client, die letzten 300 Sitzungen |

Tokens stehen in `servers.json` oder, besser, als Referenz im Schlüsselbund bzw. in 1Password (siehe „Secrets“). `servers.json` gehört nicht ins Repo.

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

Ein Eintrag mit `url` und ohne `type` gilt als Streamable HTTP. Optional:

- `description`: Zweck des Servers, nur für die GUI. Fehlt sie, zeigt die GUI die Beschreibung des Servers oder seine ersten Tools.
- `enabled: false`: Server bleibt eingetragen, der Hub startet ihn aber nicht.
- `disabledTools`: Liste von Tool-Namen (ohne Präfix), die der Hub ausblendet und deren Aufruf er ablehnt. Pflege am einfachsten über ⋯ → „Tools auswählen…“: Der Dialog listet alle Tools mit Kurzbeschreibung, lässt sich filtern, und „Alle an“ / „Alle aus“ wirken nur auf die gefilterten Tools (z. B. „incident“ filtern, „Alle aus“). In der Liste zeigt dann ein Chip mit orangefarbener Schrift „6 Tools deaktiviert“, der Tooltip nennt die Tools, ein Klick öffnet die Auswahl. Eine Änderung startet den Server nicht neu.
- `env` (stdio) bzw. `headers` (HTTP/SSE).

### Secrets

Statt Tokens im Klartext können Werte in `env`, `headers`, `url` und `args` Referenzen enthalten, die der Hub erst beim Start eines Servers auflöst:

```json
"glitchtip": { "type": "http", "url": "https://…/mcp", "headers": { "Authorization": "${keychain:glitchtip/Authorization}" } },
"grafana": { "command": "uvx", "args": ["mcp-grafana"], "env": { "GRAFANA_SERVICE_ACCOUNT_TOKEN": "${op://Private/Grafana/token}" } }
```

Welche Quelle gilt, entscheidet allein die Schreibweise, pro Wert. Es gibt keine Einstellung und keinen Fallback: Ist `op` nicht angemeldet, sucht der Hub nicht ersatzweise im Schlüsselbund. Ein Server kann beide Quellen mischen.

- `${keychain:name}` liest den macOS-Schlüsselbund (Account `mcp-hub`, Dienst `mcp-hub/<name>`; die Suche nach `mcp-hub` in der Schlüsselbundverwaltung zeigt alle Einträge). Am einfachsten über das Schloss neben einem Wert im Editor: Es legt den Eintrag an und ersetzt den Wert durch die Referenz, gespeichert wird erst mit „Speichern“. Von Hand geht es mit `security add-generic-password -a mcp-hub -s mcp-hub/<name> -w`. Nur druckbare ASCII-Werte, andere gibt `security` als Hex aus.
- `${op://Tresor/Eintrag/Feld}` liest per 1Password-CLI (`op read`). `op` muss dafür in der Umgebung des Hubs angemeldet sein, z. B. über die Integration mit der 1Password-App. Der Hub legt in 1Password nichts an, das Schloss schreibt immer in den Schlüsselbund. Sinnvoll für Tokens, die ohnehin in 1Password gepflegt, geteilt oder rotiert werden; sonst ist der Schlüsselbund einfacher.
- Referenzen dürfen in einem längeren Wert stehen, etwa `Bearer ${keychain:…}` oder `?key=${keychain:…}`.
- Aufgelöste Werte bleiben bis zum Neustart des Hubs im Speicher. Nach einer Änderung im Schlüsselbund oder in 1Password den Hub neu starten (`prun restart mcp-hub`); den Server aus- und einzuschalten reicht nicht. Nur das Schloss in der GUI aktualisiert den Speicher für seinen Eintrag sofort.
- Fehlt ein Eintrag, startet der Server nicht. Der Tooltip am Status-Chip zeigt dann z. B. „Secret: Kein Schlüsselbund-Eintrag …“.

Mit `passEnvironment` (Einstellungen) erben lokale Server die Umgebung des Hubs, sonst nur `env`.

## Hub

Unter `/mcp` bündelt der Hub alle aktivierten Server zu einem MCP-Endpunkt (Streamable HTTP, JSON-Antworten).

- **Namen:** Tools und Prompts bekommen den Servernamen als Präfix (`grafana__query_loki_logs`), Resources behalten ihre URI.
- **Titel:** Jedes Tool bekommt den Titel `server: Name`. Claude Desktop zeigt in den Konnektor-Berechtigungen nur den Titel an, dadurch bleibt erkennbar, von welchem Server ein Tool stammt.
- **Änderungen:** Speichern in der GUI synchronisiert den Hub sofort. Neu gestartet werden nur Server, deren Befehl, URL, Header oder Umgebung sich geändert hat. Eine reine Änderung der Beschreibung startet nichts neu.
- **Prozesse:** Lokale Server laufen in einer eigenen Prozessgruppe. Beim Beenden räumt der Hub die ganze Gruppe ab, auch Kindprozesse.
- **Arbeitsverzeichnis:** Lokale Server laufen im Hub-Ordner. Tools, die einen Projektpfad erwarten, brauchen daher einen absoluten Pfad.
- **Sicherheit:** Schreibende Anfragen (`POST`, `PUT`) mit fremdem `Origin`-Header werden abgelehnt, für den MCP-Endpunkt wie für die GUI-API (Schutz vor DNS-Rebinding und CSRF).

### Clients anbinden

Claude Code:

```bash
claude mcp add --scope user --transport http mcp-hub http://127.0.0.1:4747/mcp
```

Copilot / VS Code (`~/.copilot/mcp-config.json`):

```json
{ "mcpServers": { "mcp-hub": { "type": "http", "url": "http://127.0.0.1:4747/mcp", "tools": ["*"] } } }
```

Claude Desktop kann nur lokale Befehle starten, deshalb dort [mcp-proxy](https://github.com/sparfenyuk/mcp-proxy) als Brücke (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{ "mcpServers": { "mcp-hub": { "command": "/Users/<du>/.local/bin/mcp-proxy", "args": ["--transport", "streamablehttp", "http://127.0.0.1:4747/mcp"] } } }
```

Clients laden die Tool-Liste meist nur beim Start. Nach neuen Servern also den Client neu starten bzw. in Claude Code `/mcp` → Reconnect.

## Betrieb über prun

Der Hub läuft als prun-Projekt `mcp-hub` (Port 4747, Befehl `python3 app.py`). Die prun-Tools sind selbst über den Hub angebunden (`mcp__mcp-hub__prun__*`). Ein Neustart des Hubs über diese Tools kappt die eigene Verbindung, daher für den Hub selbst die CLI nehmen:

```bash
prun restart mcp-hub
```

## GUI

- **Server:** Liste mit An/Aus-Schalter, Hub-Status je Server (Tools, Fehler), Nutzung und Sortierung nach zuletzt verwendet, Name oder Datei. Über das Menü ⋯ lassen sich Server inspizieren, Tools für den Hub an- und abwählen, bearbeiten, duplizieren und löschen. Import nimmt `mcpServers`-JSON aus anderen Konfigurationen an.
- **Protokoll:** Jeder Aufruf über den Hub mit Zeit, Client, Server, Tool, Argumenten, Ergebnisvorschau, Dauer und Fehlerstatus. Filterbar nach Server, Client und Fehlern.
- **Inspector:** Verbindet sich direkt mit einem Server (unabhängig vom Hub) und listet Tools, Resources, Templates und Prompts. Alles lässt sich mit Formular- oder JSON-Eingabe aufrufen, stderr und Notifications erscheinen darunter.
- **JSON:** Die Serverdatei direkt bearbeiten.
- **Einstellungen:** Pfad zur Serverdatei, `passEnvironment`.

### Profile

Ein Profil merkt sich je Server, ob er aktiviert ist und welche Tools abgewählt sind. Es dient dazu, schnell zwischen Setups zu wechseln, etwa „Frontend“ mit nuxt, nuxt-ui und chrome-devtools oder „Ops“ mit grafana und glitchtip.

- **Speichern:** Server und Tools einstellen, dann oben über ⋯ → „Als neues Profil speichern…“.
- **Wechseln:** In der Auswahl oben ein Profil wählen. Der Hub schreibt An/Aus und `disabledTools` in `servers.json`, startet oder stoppt die betroffenen Server und blendet Tools aus. Clients sehen die neue Tool-Liste nach einem Reconnect.
- **Geändert:** Weicht der Stand vom aktiven Profil ab, steht „geändert“ neben der Auswahl. Über ⋯ → „… aktualisieren“ übernimmt das Profil den aktuellen Stand. Beim Wechsel mit ungespeicherten Änderungen fragt die GUI nach.
- **Neue Server:** Server, die ein Profil nicht kennt, lässt der Wechsel unverändert. Mit „aktualisieren“ kommen sie ins Profil.
- **Löschen:** über ⋯ → „… löschen“ für das aktive Profil. Server und Tools bleiben dabei, wie sie sind.

Das Profil gilt für den ganzen Hub, also für alle Clients gleichzeitig.

### Nutzung und Protokoll

Gezählt werden nur echte Aufrufe (`tools/call`, `prompts/get`, `resources/read`), keine Listenabfragen. Im Protokoll sind Argumente auf 4.000 und Ergebnisse auf 600 Zeichen gekürzt.

Den Client ermittelt der Hub aus `clientInfo` beim `initialize` und vergibt dafür eine `Mcp-Session-Id`. Clients, die schon vor einem Hub-Neustart verbunden waren, schicken eine unbekannte Sitzung mit. Sie erscheinen als `<User-Agent> (ohne Sitzung)`, bis sie sich neu verbinden.

## API

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/api/state` | Konfiguration und Einstellungen |
| `PUT` | `/api/servers` | `{"mcpServers": {…}}` speichern, Hub synchronisieren |
| `PUT` | `/api/settings` | Einstellungen speichern |
| `GET` | `/api/hub` | Status je Server (Zustand, Fehler, Anzahl Tools/Prompts/Resources) |
| `GET` | `/api/hub/tools?name=` | Alle Tools eines Servers mit Status `enabled` |
| `GET` | `/api/usage` | Nutzungszähler |
| `GET` | `/api/calls?limit=300` | Letzte Aufrufe (max. 1.000) |
| `POST` | `/api/profiles` | `{"action": "save" \| "apply" \| "delete" \| "clear", "name"}` |
| `POST` | `/api/secrets` | `{"name", "value"}` im Schlüsselbund ablegen, liefert `{"ref"}` |
| `POST` | `/api/inspect/connect` | Inspector-Sitzung öffnen (`{"name": …}`) |
| `POST` | `/api/inspect/call` | `{"name", "method", "params"}` an den Server schicken |
| `POST` | `/api/inspect/disconnect` | Sitzung schließen |
| `GET` | `/api/inspect/log?name=&since=` | stderr und Notifications der Sitzung |
| `POST` | `/mcp` | MCP-Endpunkt des Hubs |

## Fehlersuche

- **Server zeigt „Fehler“:** Mit der Maus über den Status-Chip fahren, der Tooltip zeigt die Fehlermeldung samt letzter stderr-Zeile. Genauer geht es mit dem Inspector, der denselben Eintrag direkt startet.
- **Tool fehlt im Client:** Ist der Server aktiviert und im Hub grün? Danach den Client neu verbinden.
- **Verwaiste Prozesse:** Prozesse, die nach dem Beenden eines Clients übrig bleiben, stammen meist von Clients, die nur den obersten Prozess beenden. Der Hub selbst beendet ganze Prozessgruppen. Prüfen mit `ps -axo pid,ppid,command | grep <server>`.
- **Port belegt:** `lsof -iTCP:4747 -sTCP:LISTEN`. Einen anderen Port per `PORT=…` setzen, dann aber auch die Client-URLs anpassen.

## Ideen und nächste Schritte

1. **Remote und Backup:** Den Code in ein privates Git-Repo pushen und `servers.json` verschlüsselt sichern, etwa per Time Machine oder als 1Password-Dokument.
2. **Tokens aus der JSON holen:** Erledigt, siehe „Secrets“.
3. **Tools pro Server ein- und ausschalten:** Erledigt, siehe `disabledTools`.
4. **Änderungen an Clients melden:** `notifications/tools/list_changed` per SSE an verbundene Clients schicken, damit neue Server ohne Reconnect erscheinen.
5. **Statistik im Protokoll:** Aufrufe pro Tag, langsamste Tools und Fehlerquote je Server, berechnet aus `calls.jsonl`.
6. **OAuth für entfernte Server:** Für gehostete MCPs, die nur OAuth anbieten.
7. **Alte Reste entfernen:** Erledigt.
8. **Tests:** Ein Smoke-Test, der den Hub mit einem Dummy-Server startet und `tools/list` sowie `tools/call` prüft.

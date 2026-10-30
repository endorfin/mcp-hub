# MCP Hub

Lokaler Hub für MCP-Server: alle Server an einer Stelle pflegen, testen und gebündelt unter einem Endpunkt an Claude Code, Claude Desktop, Copilot & Co. ausliefern.

```bash
python3 app.py   # GUI: http://127.0.0.1:4747, Hub: http://127.0.0.1:4747/mcp
```

Keine Abhängigkeiten außer Python 3.11+. Der Server lauscht nur auf `127.0.0.1`.

## Dateien

Alles liegt in `~/.config/mcp-hub/` (änderbar per `MCP_HUB_HOME`), nicht im Repo. Ein alter Ordner `~/.config/mcp-proxy/` wird beim ersten Start dorthin umgezogen; `MCP_PROXY_GUI_HOME` funktioniert weiter.

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
- Aufgelöste Werte bleiben bis zum Neustart des Hubs im Speicher. Nach einer Änderung im Schlüsselbund oder in 1Passwordden Hub neu starten (z. B. `./autostart.sh restart`); den Server aus- und einzuschalten reicht nicht. Nur das Schloss in der GUI aktualisiert den Speicher für seinen Eintrag sofort.
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

Claude Desktop kann nur lokale Befehle starten. Dafür liegt `bridge.py` im Repo: eine Brücke von stdio auf den Hub, ohne Abhängigkeiten (`~/Library/Application Support/Claude/claude_desktop_config.json`, das passende Snippet mit absoluten Pfaden zeigt die GUI unter der Serverliste):

```json
{ "mcpServers": { "mcp-hub": { "command": "/opt/homebrew/bin/python3", "args": ["/pfad/zu/mcp-hub/bridge.py", "http://127.0.0.1:4747/mcp"] } } }
```

Die Brücke reicht Benachrichtigungen des Hubs an Claude Desktop weiter und meldet sich nach einem Neustart des Hubs von selbst neu an. Ist der Hub nicht erreichbar, beantwortet sie Anfragen mit einer Fehlermeldung, statt zu hängen. [mcp-proxy](https://github.com/sparfenyuk/mcp-proxy) funktioniert ebenfalls, leitet aber keine Benachrichtigungen weiter.

### Live-Aktualisierung

Ändert sich die Tool-Liste (Server an/aus, Tools abgewählt, Profil gewechselt, ein Server meldet selbst neue Tools), schickt der Hub `notifications/tools/list_changed` (ebenso für Prompts und Resources). Clients empfangen das über einen offenen SSE-Stream (`GET /mcp` mit `Accept: text/event-stream`), den sie direkt nach `initialize` öffnen.

- **Claude Code und VS Code/Copilot** unterstützen das. Nach dem ersten Update des Hubs einmal neu verbinden (Claude Code: `/mcp` → Reconnect), danach kommen Änderungen ohne Reconnect an.
- **Anzeige:** Die Kopfzeile der GUI zählt die Clients mit offenem Stream („· 2 Clients“), der Tooltip nennt sie.
- **Claude Desktop** über `bridge.py`: Die Brücke hält den Stream offen und reicht die Meldungen weiter. Mit mcp-proxy als Brücke gehen sie verloren, dann hilft nur ein Neustart von Claude Desktop.
- **Neustart des Hubs:** Sitzungen gelten nur bis zum Neustart. Danach beantwortet der Hub alte Sitzungs-IDs mit `404`, und Clients melden sich neu an (so verlangt es die MCP-Spezifikation). `DELETE /mcp` beendet eine Sitzung.

## Autostart

Damit Claude Code, Claude Desktop und Copilot nach einem Neustart des Macs ihre Tools haben, muss der Hub beim Login starten. `autostart.sh` richtet dafür einen LaunchAgent ein (`~/Library/LaunchAgents/de.tpwd.mcp-hub.plist`), der `python3 app.py` startet und nach einem Absturz neu startet:

```bash
./autostart.sh install     # einrichten und sofort starten
./autostart.sh status      # eingerichtet? läuft der Hub?
./autostart.sh restart     # Hub neu starten, z. B. nach einer Änderung im Schlüsselbund
./autostart.sh uninstall   # entfernen und den Hub beenden
```

Log: `~/Library/Logs/mcp-hub.log`. Pfad zu `python3`, `PATH` und `PORT` werden beim Einrichten festgehalten; nach einem Umzug des Repos oder einer neuen Python-Installation erneut `install` ausführen. Läuft beim Einrichten schon ein Hub auf dem Port, bricht das Skript ab, statt einen zweiten zu starten.

## GUI

Gestaltungsregeln und Komponenten der Oberfläche stehen in [DESIGN.md](DESIGN.md), Zielgruppe, Zweck und Grundsätze des Produkts in [PRODUCT.md](PRODUCT.md).

- **Server:** Liste mit An/Aus-Schalter, Hub-Status je Server (Tools, Fehler), Nutzung und Sortierung nach zuletzt verwendet, Name oder Datei. Über das Menü ⋯ lassen sich Server inspizieren, Tools für den Hub an- und abwählen, bearbeiten, duplizieren und löschen. Import nimmt `mcpServers`-JSON aus anderen Konfigurationen an.
- **Protokoll:** Jeder Aufruf über den Hub mit Zeit, Client, Server, Tool, Argumenten, Ergebnisvorschau, Dauer und Fehlerstatus. Filterbar nach Server, Client und Fehlern.
- **Inspector:** Verbindet sich direkt mit einem Server (unabhängig vom Hub) und listet Tools, Resources, Templates und Prompts. Alles lässt sich mit Formular- oder JSON-Eingabe aufrufen, stderr und Notifications erscheinen darunter.
- **Einstellungen:** Pfad zur Serverdatei, `passEnvironment` und darunter die komplette `mcpServers`-Definition als JSON zum direkten Bearbeiten.

### Profile

Ein Profil merkt sich je Server, ob er aktiviert ist und welche Tools abgewählt sind. Es dient dazu, schnell zwischen Setups zu wechseln, etwa „Frontend“ mit nuxt, nuxt-ui und chrome-devtools oder „Ops“ mit grafana und glitchtip.

- **Speichern:** Server und Tools einstellen, dann oben über ⋯ → „Als neues Profil speichern…“.
- **Wechseln:** Oben die Profilauswahl öffnen (mit Suchfeld, Pfeiltasten und Enter) und ein Profil wählen. Der Hub schreibt An/Aus und `disabledTools` in `servers.json`, startet oder stoppt die betroffenen Server und blendet Tools aus. Verbundene Clients bekommen die neue Tool-Liste automatisch (siehe „Live-Aktualisierung“).
- **Geändert:** Weicht der Stand vom aktiven Profil ab, zeigt die Auswahl einen orangefarbenen Punkt (Tooltip: ungespeicherte Änderungen). Über ⋯ → „… aktualisieren“ übernimmt das Profil den aktuellen Stand. Beim Wechsel mit ungespeicherten Änderungen fragt die GUI nach.
- **Kein Profil:** schaltet alle Server ein und alle Tools frei (entfernt jedes `disabledTools`), auch wenn „Kein Profil“ schon ausgewählt ist. Ein geändertes Profil erneut anzuklicken setzt es auf seinen gespeicherten Stand zurück.
- **Neue Server:** Server, die ein Profil nicht kennt, lässt der Wechsel unverändert. Mit „aktualisieren“ kommen sie ins Profil.
- **Verwalten:** Unter ⋯ → „Profile verwalten…“ hat jedes Profil ein eigenes ⋯-Menü: URL kopieren, Aktivieren, Umbenennen und Löschen, ohne es vorher anzuwenden. Ein Klick auf die URL kopiert sie ebenfalls. Server und Tools bleiben dabei, wie sie sind. Namen dürfen kein `/` enthalten.

Das Profil oben gilt für den ganzen Hub, also für alle Clients am Standard-Endpunkt `/mcp`.

**Endpunkt pro Profil:** Jedes Profil ist zusätzlich unter `http://127.0.0.1:4747/p/<profil>/mcp` erreichbar (URL zum Kopieren in „Profile verwalten…“). Ein Client dort sieht immer die Server und Tools dieses Profils, egal welches Profil oben aktiv ist. So kann z. B. Copilot fest mit „Frontend“ arbeiten und Claude Code mit allem:

```bash
claude mcp add --scope user --transport http mcp-hub-frontend http://127.0.0.1:4747/p/Frontend/mcp
```

Der Profil-Endpunkt filtert nur: Server, die im Hub ausgeschaltet sind, fehlen auch dort. Server, die das Profil nicht kennt, erscheinen mit ihrer aktuellen Einstellung. Im Protokoll steht hinter dem Client das Profil, z. B. `claude-code · Frontend`.

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
| `GET` | `/api/live` | Clients mit offenem Benachrichtigungs-Stream |
| `GET` | `/api/usage` | Nutzungszähler |
| `GET` | `/api/calls?limit=300` | Letzte Aufrufe (max. 1.000) |
| `POST` | `/api/profiles` | `{"action": "save" \| "apply" \| "rename" \| "delete" \| "clear", "name", "newName"}`; `clear` schaltet alles ein |
| `POST` | `/api/secrets` | `{"name", "value"}` im Schlüsselbund ablegen, liefert `{"ref"}` |
| `POST` | `/api/inspect/connect` | Inspector-Sitzung öffnen (`{"name": …}`) |
| `POST` | `/api/inspect/call` | `{"name", "method", "params"}` an den Server schicken |
| `POST` | `/api/inspect/disconnect` | Sitzung schließen |
| `GET` | `/api/inspect/log?name=&since=` | stderr und Notifications der Sitzung |
| `POST` | `/mcp` | MCP-Endpunkt des Hubs |
| `GET` | `/mcp` | SSE-Stream für Benachrichtigungen (`Accept: text/event-stream`) |
| `POST` | `/p/<profil>/mcp` | MCP-Endpunkt mit festem Profil (auch `GET` für den Stream) |

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Die Tests starten einen eigenen Hub mit eigenem Konfigurationsordner auf einem freien Port und zwei Instanzen eines kleinen stdio-Servers (`tests/dummy_server.py`). Geprüft werden Präfixe und Titel, Sitzungen (404 nach Ende), die Brücke samt Hub-Neustart, Weiterleitung und Protokoll, Fehler, `disabledTools`, Profile samt Profil-Endpunkt, Benachrichtigungen, Origin-Schutz und (nur macOS) die Auflösung aus dem Schlüsselbund. Die echte Konfiguration bleibt unberührt; der Schlüsselbund-Test legt `mcp-hub/selftest/hub-tests` an und löscht ihn wieder.

## Fehlersuche

- **Server zeigt „Fehler“:** Mit der Maus über den Status-Chip fahren, der Tooltip zeigt die Fehlermeldung samt letzter stderr-Zeile. Genauer geht es mit dem Inspector, der denselben Eintrag direkt startet.
- **Tool fehlt im Client:** Ist der Server aktiviert und im Hub grün? Danach den Client neu verbinden.
- **Verwaiste Prozesse:** Prozesse, die nach dem Beenden eines Clients übrig bleiben, stammen meist von Clients, die nur den obersten Prozess beenden. Der Hub selbst beendet ganze Prozessgruppen. Prüfen mit `ps -axo pid,ppid,command | grep <server>`.
- **Port belegt:** `lsof -iTCP:4747 -sTCP:LISTEN`. Einen anderen Port per `PORT=…` setzen, dann aber auch die Client-URLs anpassen.

## Ideen und nächste Schritte

1. **Remote und Backup:** Den Code in ein privates Git-Repo pushen und `servers.json` verschlüsselt sichern, etwa per Time Machine oder als 1Password-Dokument.
2. **Tokens aus der JSON holen:** Erledigt, siehe „Secrets“.
3. **Tools pro Server ein- und ausschalten:** Erledigt, siehe `disabledTools`.
4. **Änderungen an Clients melden:** Erledigt, siehe „Live-Aktualisierung“.
5. **Statistik im Protokoll:** Aufrufe pro Tag, langsamste Tools und Fehlerquote je Server, berechnet aus `calls.jsonl`.
6. **OAuth für entfernte Server:** Für gehostete MCPs, die nur OAuth anbieten.
7. **Alte Reste entfernen:** Erledigt.
8. **Tests:** Erledigt, siehe „Tests“.

# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Entwicklerinnen und Entwickler, die mit mehreren KI-Clients (Claude Code, Claude Desktop, VS Code/Copilot) und vielen MCP-Servern arbeiten. Ihre Aufgabe: Server einmal pflegen, statt dieselben Einträge, Tokens und Pfade in jedem Client einzeln zu verwalten, und jederzeit sehen, welche Tools gerade aktiv sind und wer sie benutzt.

Das Projekt ist als Open Source gedacht. Die Oberfläche läuft lokal auf dem eigenen Rechner unter `http://127.0.0.1:4747`.

## Product Purpose

MCP Hub ist ein lokaler Hub für MCP-Server: Er startet lokale (stdio) und bindet entfernte (Streamable HTTP, SSE) Server an und liefert alle gebündelt unter einem einzigen MCP-Endpunkt aus. Dazu kommt eine Web-Oberfläche zum Verwalten, Testen und Beobachten.

Erfolg heißt: Jeder Client braucht genau einen Eintrag (`mcp-hub`), neue Server stehen sofort überall zur Verfügung, und es liegen keine Tokens mehr im Klartext in Konfigurationsdateien.

## Positioning

Ein einziger lokaler Endpunkt für alle Clients statt Konfiguration pro Client, ohne Abhängigkeiten außer Python. Der Hub ist zugleich Verwaltung (GUI, Profile, Tool-Auswahl), Prüfstand (Inspector) und Beobachtung (Aufrufprotokoll mit Client-Zuordnung, Live-Clients). Clients erfahren Änderungen live über `list_changed`, auch Claude Desktop über die mitgelieferte stdio-Brücke.

## Operating Context

- Läuft dauerhaft im Hintergrund, gestartet über `autostart.sh` (LaunchAgent) oder ein eigenes Werkzeug; die GUI wird zwischendurch geöffnet, oft neben Terminal und Editor.
- Typische Abläufe: Server hinzufügen oder importieren, Token im Schlüsselbund ablegen, Tools eines Servers abwählen, zwischen Profilen wechseln, einen Server im Inspector testen, im Protokoll nachsehen, welcher Agent welches Tool wann aufgerufen hat.
- Konfiguration liegt außerhalb des Repos in `~/.config/mcp-hub/` (`servers.json`, `profiles.json`, `usage.json`, `calls.jsonl`, `clients.json`).
- Clients: Claude Code (HTTP), VS Code/Copilot (HTTP), Claude Desktop (stdio über `bridge.py`), beliebige weitere MCP-Clients über `/mcp` oder `/p/<profil>/mcp`.

## Capabilities and Constraints

- Python 3.11+ ohne Fremdpakete; Server und GUI in einem Prozess (`app.py`), Oberfläche als eine Datei (`index.html`) ohne Build-Schritt.
- Nur lokal: lauscht auf `127.0.0.1`, lehnt schreibende Anfragen mit fremdem `Origin` ab.
- Tool- und Prompt-Namen tragen den Servernamen als Präfix (`server__tool`), Titel `server: Name`.
- Secrets als Referenz: `${keychain:…}` (macOS-Schlüsselbund) und `${op://…}` (1Password-CLI).
- Statistik über die letzten 5.000 Aufrufe: Kennzahlen, Verlauf je Tag, je Server, langsamste Tools.
- Profile speichern An/Aus und abgewählte Tools je Server; jedes Profil hat einen eigenen Endpunkt.
- macOS ist die einzige getestete Plattform (Schlüsselbund, LaunchAgent).
- **Offen:** Lizenz; Sprache der Oberfläche und der Doku (derzeit Deutsch, für Open Source eventuell Englisch oder zweisprachig); neutrale Defaults statt persönlicher Werte (z. B. LaunchAgent-Label `de.tpwd.mcp-hub`); Unterstützung für Linux und Windows.

## Brand Commitments

- Name: **MCP Hub**.
- Keine Bindung an ein persönliches Werkzeug: Projektdateien setzen kein bestimmtes Startwerkzeug voraus.

## Evidence on Hand

- Funktionierende Implementierung mit Tests (`tests/`, 13 Smoke-Tests inklusive Brücke und Hub-Neustart).
- README mit Eintragsformaten, Client-Anbindung, API und Fehlersuche.
- Es gibt keine Nutzerzahlen, Erfahrungsberichte, Screenshots für Marketing oder Release-Notes; nichts davon erfinden.

## Product Principles

1. **Eine Stelle pflegen.** Jede Einstellung existiert genau einmal im Hub; Clients bekommen nur den Endpunkt.
2. **Sichtbar statt vermutet.** Was läuft, was abgewählt ist, wer verbunden ist und wer was aufruft, steht in der Oberfläche, nicht in Logdateien.
3. **Keine Geheimnisse im Klartext.** Tokens gehören in Schlüsselbund oder Passwortmanager; Dateien enthalten nur Referenzen.
4. **Ohne Ballast.** Keine Abhängigkeiten, kein Build, ein Prozess; neue Funktionen müssen diesen Rahmen halten.
5. **Änderungen wirken sofort.** Speichern synchronisiert den Hub, Clients werden live benachrichtigt, Neustarts nur dort, wo nötig.

## Accessibility & Inclusion

Bedienbar per Tastatur (eigene Listboxen und Menüs mit Pfeiltasten, Enter, Esc), sichtbare Fokusringe, Rollen und Labels für Screenreader, helles und dunkles Farbschema nach Systemeinstellung.

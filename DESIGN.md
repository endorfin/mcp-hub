---
name: MCP Hub
description: Lokale Schaltzentrale für alle MCP-Server
colors:
  accent: "#1f8a4c"
  accent-dark: "#4cc27f"
  on-accent: "#ffffff"
  on-accent-dark: "#0e1a12"
  warn: "#b26a00"
  warn-dark: "#e0a440"
  bad: "#c0362c"
  bad-dark: "#ff7366"
  bg: "#f6f6f4"
  bg-dark: "#141413"
  panel: "#ffffff"
  panel-dark: "#1d1d1b"
  field: "#f6f6f4"
  field-dark: "#151514"
  chip: "#efeeea"
  chip-dark: "#262624"
  line: "#e3e2de"
  line-dark: "#2e2e2b"
  ink: "#1c1c1a"
  ink-dark: "#ecebe6"
  muted: "#6b6b66"
  muted-dark: "#9a998f"
  scrim: "rgb(0 0 0 / .35)"
  series: "#85847d"
  series-dark: "#96958e"
  series-error: "#c0362c"
  series-error-dark: "#d9493f"
typography:
  title:
    fontFamily: "-apple-system, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 650
    letterSpacing: "-0.01em"
  item-name:
    fontFamily: "-apple-system, system-ui, sans-serif"
    fontSize: "15.5px"
    fontWeight: 600
    letterSpacing: "-0.01em"
  body:
    fontFamily: "-apple-system, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "-apple-system, system-ui, sans-serif"
    fontSize: "12.5px"
    fontWeight: 400
  kpi:
    fontFamily: "-apple-system, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 600
    letterSpacing: "-0.02em"
  mono:
    fontFamily: "ui-monospace, SF Mono, Menlo, monospace"
    fontSize: "12.5px"
  chip:
    fontFamily: "ui-monospace, SF Mono, Menlo, monospace"
    fontSize: "11.5px"
rounded:
  check: "4px"
  item: "6px"
  control: "7px"
  segment: "8px"
  popover: "9px"
  card: "10px"
  dialog: "12px"
  pill: "99px"
spacing:
  xs: "6px"
  sm: "8px"
  md: "14px"
  lg: "20px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
    height: "36px"
  button-secondary:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
    height: "36px"
  input:
    backgroundColor: "{colors.field}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "7px 10px"
    height: "36px"
  chip:
    backgroundColor: "{colors.chip}"
    textColor: "{colors.muted}"
    typography: "{typography.chip}"
    rounded: "{rounded.pill}"
    padding: "1px 7px"
  listbox-option:
    textColor: "{colors.ink}"
    rounded: "{rounded.item}"
    padding: "6px 8px"
  listbox-option-active:
    backgroundColor: "{colors.chip}"
  kpi:
    backgroundColor: "{colors.field}"
    rounded: "{rounded.segment}"
    padding: "12px 14px"
  card:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.card}"
    padding: "18px 20px"
---

# Design System: MCP Hub

## Overview

**Creative North Star: "Das Schaltpult"**

Eine ruhige Steuerzentrale, die man nebenbei öffnet und in Sekunden versteht. Die Fläche ist zurückhaltend und warm-grau, Inhalt steht in klaren Listen, und Farbe trägt fast immer eine Bedeutung: Grün heißt „läuft“ oder „Hauptaktion“, Orange „abweichend“, Rot „Fehler“. Alles Weitere liegt hinter einem ⋯-Menü oder einer Liste, nicht offen auf der Fläche.

Die Dichte ist die eines Werkzeugs, nicht einer Marketingseite: 14 px Grundschrift, technische Werte in Monospace, Status als kleine Chips. Helles und dunkles Schema sind gleichwertig und folgen der Systemeinstellung; das dunkle Schema ist der Alltag neben Terminal und Editor.

Native Bedienelemente des Betriebssystems kommen nicht vor. Auswahlfelder, Checkboxen und Menüs sind eigene Komponenten, damit sie in beiden Schemata gleich aussehen und sich gleich bedienen lassen.

**Key Characteristics:**
- Ein Akzent (Grün) mit Bedeutung, sonst neutrale, leicht warme Grautöne
- Flach: Tiefe durch Flächentöne, Schatten nur bei schwebenden Elementen
- Zusammengehörige Bedienelemente als FieldGroup mit gemeinsamem Rahmen
- Sekundäre Aktionen hinter ⋯-Menüs, Auswahl über eigene Listboxen
- Systemschrift für Text, Monospace für Befehle, URLs, Namen und Chips

## Colors

Neutrale, leicht warme Grautöne mit einem einzigen Akzent; jede Farbe außerhalb der Grautöne meldet einen Zustand.

### Primary
- **Schaltgrün** (`accent`, dunkel `accent-dark`): Primärbuttons, aktive Schalter und Checkboxen, Fokusringe (40–50 % gemischt), Status „läuft“. Text auf Grün nutzt `on-accent`.

### Neutral
- **Werkstattgrau** (`bg`): Seitenhintergrund und Kopfleiste.
- **Pultfläche** (`panel`): Listen, Karten, Dialoge, Popover und Bedienelemente auf dem Seitenhintergrund.
- **Mulde** (`field`): Eingabefelder innerhalb von Dialogen, Karten, Inspector und Popover; etwas dunkler als die Pultfläche, damit Felder eingelassen wirken.
- **Kappe** (`chip`): Chips, Hover- und Auswahlflächen in Menüs und Listen, aktiver Tab.
- **Fuge** (`line`): Rahmen und Trennlinien, 1 px.
- **Tinte** (`ink`) und **Beschriftung** (`muted`): Text und Sekundärtext, Icons im Ruhezustand.

### Status
- **Signalorange** (`warn`): Abweichungen, die keine Fehler sind: „Tools deaktiviert“, ungespeicherte Profiländerung (Punkt), Server startet.
- **Signalrot** (`bad`): Fehler und destruktive Menüeinträge („Löschen“).

### Diagramme
- **Datenreihe** (`series`): neutrales Grau für die Menge, z. B. erfolgreiche Aufrufe. Geprüft mit dem Dataviz-Validator: Kontrast ≥ 3:1 zur Pultfläche in beiden Schemata.
- **Fehlerreihe** (`series-error`): Signalrot für Flächen, im dunklen Schema etwas gedämpft (`series-error-dark`), damit es sich auch bei Rot-Schwäche vom Grau abhebt (ΔE ≥ 8).

### Named Rules
**The Meaning-Only Rule.** Grün, Orange und Rot erscheinen nur, wenn sie einen Zustand oder die Hauptaktion bezeichnen. Dekorative Farbe gibt es nicht.

**The Twin Scheme Rule.** Jede Farbe existiert als helles und dunkles Paar (`-dark`); neue Farben werden immer für beide Schemata als Token auf `:root` angelegt, nie direkt im Element.

## Typography

**Body Font:** System-UI (`-apple-system, system-ui, sans-serif`)
**Mono Font:** `ui-monospace, SF Mono, Menlo, monospace`

**Character:** Die Systemschrift lässt das Werkzeug wie Teil des Betriebssystems wirken; Monospace markiert alles, was man kopieren oder in eine Konfiguration übernehmen könnte.

### Hierarchy
- **Title** (650, 16 px, −0.01em): Produktname in der Kopfleiste.
- **KPI** (600, 24 px, −0.02em, Ziffern gleicher Breite): Werte in den Kennzahl-Kacheln der Statistik.
- **Item Name** (600, 15,5 px, −0.01em): Servernamen in der Liste.
- **Section** (600, 14 px): Überschriften in Karten und Dialogköpfen.
- **Body** (400, 14 px, 1.45): Fließtext und Bedienelemente.
- **Label** (400, 12,5–13 px, muted): Feldbeschriftungen mit fettem Begriff, Hinweise, Beschreibungen.
- **Mono** (12–12,5 px): Befehle, URLs, Tool-Namen, Codefragmente.
- **Chip** (Mono, 11,5 px): Status- und Zähler-Chips.

### Named Rules
**The Copyable Is Mono Rule.** Was in eine Konfiguration, ein Terminal oder eine URL-Zeile gehört, steht in Monospace; Beschreibungen nie.

## Layout

Eine zentrierte Spalte mit maximal 1040 px Breite und 20 px Rand. Darüber eine haftende Kopfleiste mit Produktname, Hub-Status, Profilauswahl und Tabs (Server, Protokoll, Inspector, Einstellungen). Unter der Kopfleiste steht je Tab eine Werkzeugleiste (Filter, Sortierung, +-Menü) über einer Liste oder Karten.

Abstände folgen einem kleinen Raster: 6 px innerhalb von Feldgruppen, 8 px zwischen Bedienelementen einer Leiste, 14 px zwischen Feldern in Dialogen und Karten, 16–24 px zwischen Karten und Abschnitten. Bei unter 760 px fällt der Inspector auf eine Spalte und das Protokoll blendet Nebenspalten aus; bei unter 640 px stapeln sich zweispaltige Formulare.

## Elevation & Depth

Flach. Ebenen entstehen durch Flächentöne (`bg` → `panel` → `field`) und 1-px-Fugen. Schatten tragen nur schwebende Elemente.

### Shadow Vocabulary
- **Schwebend** (`box-shadow: 0 8px 24px rgb(0 0 0 / .18)`): Menüs, Listboxen, Popover.
- **Angehoben** (`box-shadow: 0 1px 2px rgb(0 0 0 / .08)`): aktiver Tab im Segment.
- **Abdunklung** (`scrim`): Hintergrund hinter Dialogen.

### Named Rules
**The Float-Only Shadow Rule.** Ein Schatten bedeutet „schwebt über dem Inhalt und verschwindet wieder“. Karten, Listen und Felder bekommen keinen.

**The One Height Rule.** Felder, Listbox-Auslöser und Buttons sind gleich hoch (36 px: 20 px Zeilenhöhe, 7 px Polsterung, 1 px Rahmen), damit sie in jeder Zeile bündig nebeneinanderstehen. Felder setzen ihre Schrift selbst auf 14 px und erben nicht die kleinere Beschriftung.

## Shapes

Weich, aber nicht rund: Radien wachsen mit der Größe des Elements. Checkboxen 4 px, Menüeinträge 6 px, Bedienelemente 7 px, Tab-Segment und Rückmeldung unten 8 px, Popover 9 px, Karten und Listen 10 px, Dialoge 12 px. Chips und Schalter sind Pillen (99 px).

**The Shared Edge Rule.** In einer FieldGroup sind nur die äußeren Ecken gerundet (7 px außen, innen 6 px); innen trennt eine gerade 1-px-Fuge. Kein Element überlappt das andere mit negativem Abstand.

## Components

### Buttons
- **Shape:** 7 px Radius, 7 px × 12 px Polsterung, 1 px Rahmen, 36 px hoch.
- **Primary:** Schaltgrün mit `on-accent`, Schrift 550; nur für die Hauptaktion einer Ansicht (Speichern, +).
- **Secondary:** Pultfläche, Tinte, Fuge als Rahmen; beim Überfahren Rahmen in `muted`.
- **Ghost:** ohne Rahmen und Fläche, `muted`; beim Überfahren Kappe und Tinte. Für ⋯-Menüs und Zeilenaktionen.
- **Icon-Button:** quadratisch, Icon exakt mittig, Höhe der benachbarten Gruppe.

### Inputs / Fields
- **Style:** 1 px Fuge, 7 px Radius, 7 px × 10 px Polsterung, 14 px Schrift (Monospace 12,5 px) auf 20 px Zeilenhöhe; auf dem Seitenhintergrund in Pultfläche, in Dialogen und Karten in Mulde.
- **Focus:** Rahmen in Schaltgrün plus 2 px Ring (Schaltgrün 40 %).
- **Labels:** über dem Feld, Begriff fett in Tinte, Erläuterung in `muted` nach einem Gedankenstrich.

### Checkbox
- 16 px, 4 px Radius, Rahmen `muted`, Fläche Mulde. Angehakt: Schaltgrün mit Häkchen in `on-accent`, das in 120 ms einblendet. Fokus: 2 px Ring mit 2 px Abstand.

### Switch
- 32 × 18 px Pille für An/Aus direkt in Listen; an = Schaltgrün. Nur für sofort wirksame Zustände, nicht in Formularen.

### FieldGroup
- Mehrere Bedienelemente teilen einen Rahmen (Filter + Sortierung, Richtung + Sortierart, Profilauswahl + ⋯). Innen keine eigenen Rahmen und Fokusringe; die Gruppe zeigt Hover und Fokus gemeinsam.

### Listbox (Signature Component)
Ersetzt jedes native Auswahlfeld.
- **Auslöser:** Button mit Wert und Pfeil (10 × 6 px, `muted`); allein mit Rahmen wie ein Feld, in einer FieldGroup ohne.
- **Popover:** Pultfläche, 9 px Radius, Fuge, Schatten „Schwebend“, 4 px Innenabstand. Fuge und Schatten zusammen sind hier gewollt: Im dunklen Schema trägt der Schatten allein keine Kante; öffnet unter dem Auslöser, linksbündig oder rechtsbündig je nach Platz.
- **Suchfeld:** nur bei Listen, die lang werden können (Profile, Server, Clients), oben im Popover.
- **Einträge:** 6 px × 8 px, 6 px Radius; hervorgehoben in Kappe; der gewählte Eintrag trägt ein Häkchen in Tinte (`ink`) rechts außen; Grün bleibt Zuständen und Hauptaktionen vorbehalten.
- **Tastatur:** ↑/↓ öffnet und bewegt (umlaufend), Enter oder Leertaste übernimmt, Esc schließt und gibt den Fokus an den Auslöser zurück, Tab schließt. Ein Klick daneben schließt.

### Statistik
- **Kennzahl-Kachel:** Mulde als Fläche, 8 px Radius, Beschriftung `muted` 12,5 px, Wert 24 px / 600 mit Ziffern gleicher Breite, Zusatz 12 px `muted`. Vier nebeneinander, unter 760 px zwei.
- **Säulen je Tag:** höchstens 24 px breit, oben 4 px gerundet, unten gerade auf der Grundlinie; Fehler oben auf den erfolgreichen Aufrufen mit 2 px Abstand. Eine gestrichelte Linie markiert das Maximum, beschriftet rechts. Legende rechts über dem Diagramm. Beim Überfahren hebt sich die Spalte in Kappe ab, der Tooltip (Tinte auf Werkstattgrau, invertiert) nennt Datum, Aufrufe und Fehler.
- **Tabellen:** rechtsbündige Zahlen mit gleicher Ziffernbreite, Namen in Monospace, Trennlinien in Fuge; die Server-Tabelle zeigt den Anteil als dünnen Balken in `series`, ein Klick auf die Zeile filtert das Protokoll.

### Menüs
- Gleiches Popover wie die Listbox; Einträge ohne Häkchen, destruktive Einträge in Signalrot nach einer Trennlinie. Auslöser ist ein Ghost-Button mit ⋯ oder ein Icon-Button.

### Chips
- Pille, Monospace 11,5 px, Kappe als Fläche, Text `muted`. Statusfarbe nur im Text: grün „Hub: 18 Tools“, orange „2 Tools deaktiviert“, rot „Hub: Fehler“. Klickbar nur, wenn sie eine Aktion öffnen.

### Cards / Containers
- **Corner Style:** 10 px; **Background:** Pultfläche; **Border:** 1 px Fuge; **Internal Padding:** 18 px × 20 px; keine Schatten. Listen sind Karten mit 1-px-Fugen zwischen den Zeilen.

### Navigation
- Segmentierte Tabs in einer Kappe (8 px Radius, 3 px Innenabstand); aktiver Tab als Pultfläche mit Schatten „Angehoben“, sonst `muted`.

## Do's and Don'ts

### Do:
- **Do** jede Auswahl als eigene Listbox bauen; Häkchen rechts, Tastatur wie oben.
- **Do** zusammengehörige Bedienelemente als FieldGroup mit gemeinsamem Rahmen zeigen.
- **Do** sekundäre und destruktive Aktionen in ein ⋯-Menü legen; „Löschen“ zuletzt, rot, nach einer Trennlinie.
- **Do** neue Farben als Token-Paar auf `:root` anlegen, hell und dunkel.
- **Do** Felder in Dialogen und Karten in der Mulde (`field`) zeigen, damit sie sich abheben.
- **Do** Diagrammfarben mit dem Dataviz-Validator für beide Schemata prüfen, bevor sie eingesetzt werden.

### Don't:
- **Don't** native `<select>`, Checkboxen oder Browser-Fokusringe sichtbar lassen.
- **Don't** Grün, Orange oder Rot dekorativ einsetzen.
- **Don't** Karten, Listen oder Felder mit Schatten versehen.
- **Don't** Elemente einer Gruppe mit negativem Abstand überlappen lassen; die Trennlinie gehört einem Element.
- **Don't** Kommentare ins HTML schreiben; die Datei wird ausgeliefert.

---
name: MCP Hub
description: A local control panel for all MCP servers
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

**Creative North Star: "The Control Panel"**

A calm control center you open in passing and understand in seconds. The surface is restrained and warm gray, content sits in clear lists, and color almost always carries meaning: green means “running” or “primary action”, orange “deviating”, red “error”. Everything else lives behind a ⋯ menu or a list, not out on the surface.

The density is that of a tool, not a marketing page: 14 px base type, technical values in monospace, status as small chips. Light and dark schemes are equal and follow the system setting; the dark scheme is the everyday one, next to terminal and editor.

There are no native operating-system controls. Selects, checkboxes and menus are custom components so they look and behave the same in both schemes.

**Key Characteristics:**
- One accent (green) with meaning, otherwise neutral, slightly warm grays
- Flat: depth through surface tones, shadows only on floating elements
- Related controls as a FieldGroup with a shared border
- Secondary actions behind ⋯ menus, choices through custom listboxes
- System font for text, monospace for commands, URLs, names and chips

## Colors

Neutral, slightly warm grays with a single accent; every color outside the grays reports a state.

### Primary
- **Switch Green** (`accent`, dark `accent-dark`): primary buttons, active switches and checkboxes, focus rings (mixed at 40–50 %), status “running”. Text on green uses `on-accent`.

### Neutral
- **Workshop Gray** (`bg`): page background and header.
- **Console** (`panel`): lists, cards, dialogs, popovers and controls on the page background.
- **Well** (`field`): input fields inside dialogs, cards, the inspector and popovers; slightly darker than the console so fields look recessed.
- **Keycap** (`chip`): chips, hover and selection surfaces in menus and lists, the active tab.
- **Seam** (`line`): borders and dividers, 1 px.
- **Ink** (`ink`) and **Label** (`muted`): text and secondary text, icons at rest.

### Status
- **Signal Orange** (`warn`): deviations that are not errors: “tools disabled”, unsaved profile change (dot), server starting.
- **Signal Red** (`bad`): errors and destructive menu items (“Delete”).

### Charts
- **Data Series** (`series`): neutral gray for quantity, e.g. successful calls. Checked with the dataviz validator: contrast ≥ 3:1 against the console in both schemes.
- **Error Series** (`series-error`): Signal Red for areas, slightly muted in the dark scheme (`series-error-dark`) so it stays distinct from the gray under red-weak vision too (ΔE ≥ 8).

### Named Rules
**The Meaning-Only Rule.** Green, orange and red only appear when they denote a state or the primary action. There is no decorative color.

**The Twin Scheme Rule.** Every color exists as a light and dark pair (`-dark`); new colors are always added as tokens on `:root` for both schemes, never directly on an element.

## Typography

**Body Font:** System UI (`-apple-system, system-ui, sans-serif`)
**Mono Font:** `ui-monospace, SF Mono, Menlo, monospace`

**Character:** The system font makes the tool feel like part of the operating system; monospace marks everything you might copy or put into a configuration.

### Hierarchy
- **Title** (650, 16 px, −0.01em): product name in the header.
- **KPI** (600, 24 px, −0.02em, tabular figures): values in the statistics tiles.
- **Item Name** (600, 15.5 px, −0.01em): server names in the list.
- **Section** (600, 14 px): headings in cards and dialog headers.
- **Body** (400, 14 px, 1.45): running text and controls.
- **Label** (400, 12.5–13 px, muted): field labels with a bold term, hints, descriptions.
- **Mono** (12–12.5 px): commands, URLs, tool names, code fragments.
- **Chip** (mono, 11.5 px): status and counter chips.

### Named Rules
**The Copyable Is Mono Rule.** Anything that belongs in a configuration, a terminal or a URL bar is set in monospace; descriptions never are.

## Layout

A centered column, at most 1040 px wide with a 20 px margin. Above it, a sticky header: product name, hub status and profile picker in the first row, the tabs (Servers, Log, Inspector, Settings) on its bottom edge. Below 600 px the status moves to its own row. Below the header, each tab has a toolbar (filter, sort, + menu) above a list or cards.

Spacing follows a small grid: 6 px inside field groups, 8 px between controls in a toolbar, 14 px between fields in dialogs and cards, 16–24 px between cards and sections. Below 760 px the inspector collapses to one column and the log hides secondary columns; below 640 px two-column forms stack.

## Elevation & Depth

Flat. Layers come from surface tones (`bg` → `panel` → `field`) and 1 px seams. Only floating elements carry shadows.

### Shadow Vocabulary
- **Floating** (`box-shadow: 0 8px 24px rgb(0 0 0 / .18)`): menus, listboxes, popovers.
- **Raised** (`box-shadow: 0 1px 2px rgb(0 0 0 / .08)`): the active tab in the segment.
- **Scrim** (`scrim`): backdrop behind dialogs.

### Named Rules
**The Float-Only Shadow Rule.** A shadow means “floats above the content and goes away again”. Cards, lists and fields get none.

**The One Height Rule.** Fields, listbox triggers and buttons share one height (36 px: 20 px line height, 7 px padding, 1 px border) so they line up in every row. Fields set their own 14 px type instead of inheriting the smaller label size.

## Shapes

Soft but not round: radii grow with the size of the element. Checkboxes 4 px, menu items 6 px, controls 7 px, tab segment and toast 8 px, popovers 9 px, cards and lists 10 px, dialogs 12 px. Chips and switches are pills (99 px).

**The Shared Edge Rule.** In a FieldGroup only the outer corners are rounded (7 px outside, 6 px inside); inside, a straight 1 px seam separates the parts. No element overlaps another with a negative margin.

## Components

### Buttons
- **Shape:** 7 px radius, 7 px × 12 px padding, 1 px border, 36 px tall.
- **Primary:** Switch Green with `on-accent`, weight 550; only for the primary action of a view (Save, +).
- **Secondary:** Console, Ink, Seam as border; border turns `muted` on hover.
- **Ghost:** no border or fill, `muted`; Keycap and Ink on hover. For ⋯ menus and row actions.
- **Icon button:** square, icon exactly centered, height of the neighboring group.

### Inputs / Fields
- **Style:** 1 px Seam, 7 px radius, 7 px × 10 px padding, 14 px type (mono 12.5 px) on a 20 px line height; Console on the page background, Well in dialogs and cards.
- **Focus:** Switch Green border plus a 2 px ring (Switch Green at 40 %).
- **Labels:** above the field, the term bold in Ink, an explanation in `muted` after a dash.

### Checkbox
- 16 px, 4 px radius, `muted` border, Well fill. Checked: Switch Green with a check mark in `on-accent` that fades in over 120 ms. Focus: 2 px ring with a 2 px offset.

### Switch
- 32 × 18 px pill for on/off directly in lists; on = Switch Green. Only for states that take effect immediately, not in forms.

### FieldGroup
- Several controls share one border (filter + sort, direction + sort type, profile picker + ⋯). No borders or focus rings of their own inside; the group shows hover and focus as a whole.

### Listbox (Signature Component)
Replaces every native select.
- **Trigger:** button with value and chevron (10 × 6 px, `muted`); bordered like a field when standalone, borderless inside a FieldGroup.
- **Popover:** Console, 9 px radius, Seam, “Floating” shadow, 4 px inner padding. Seam and shadow together are intentional here: in the dark scheme the shadow alone carries no edge. Opens below the trigger, left- or right-aligned depending on space.
- **Search field:** only for lists that can grow long (profiles, servers, clients), at the top of the popover.
- **Items:** 6 px × 8 px, 6 px radius; highlighted in Keycap; the selected item carries a check mark in Ink (`ink`) at the far right; green stays reserved for states and primary actions.
- **Keyboard:** ↑/↓ opens and moves (wrapping), Enter or Space selects, Esc closes and returns focus to the trigger, Tab closes. A click outside closes.

### Statistics
- **KPI tile:** Well as fill, 8 px radius, label `muted` 12.5 px, value 24 px / 600 with tabular figures, note 12 px `muted`. Four side by side, two below 760 px.
- **Daily columns:** at most 24 px wide, 4 px rounded on top, square on the baseline; errors stacked on top of successful calls with a 2 px gap. A dashed line marks the maximum, labeled on the right. Legend at the top right of the chart. On hover the column lifts in Keycap and the tooltip (Ink on Workshop Gray, inverted) shows date, calls and errors.
- **Tables:** right-aligned tabular figures, names in monospace, Seam dividers; the server table shows the share as a thin bar in `series`, a click on a row filters the log.

### Menus
- Same popover as the listbox; items without check marks, destructive items in Signal Red after a divider. The trigger is a ghost button with ⋯ or an icon button.

### Chips
- Pill, mono 11.5 px, Keycap fill, `muted` text. Status color only in the text: green “Hub: 18 tools”, orange “2 tools disabled”, red “Hub: error”. Clickable only when they open an action.

### Cards / Containers
- **Corner Style:** 10 px; **Background:** Console; **Border:** 1 px Seam; **Internal Padding:** 18 px × 20 px; no shadows. Lists are cards with 1 px seams between rows.

### Navigation
- Main tabs: text tabs sitting on the header’s bottom seam, 22 px apart, `muted`; the active tab is `ink` with a 2 px `ink` underline that covers the seam.
- Tabs inside a card (the connect snippets) use the same text tabs on a 1 px Seam line.
- Small mode switches (Inspector: tools, prompts, resources): segmented tabs in a Keycap (8 px radius, 3 px inner padding); the active tab is Console with the “Raised” shadow, the others `muted`.

## Do's and Don'ts

### Do:
- **Do** build every choice as a custom listbox; check mark on the right, keyboard as above.
- **Do** show related controls as a FieldGroup with a shared border.
- **Do** put secondary and destructive actions into a ⋯ menu; “Delete” last, red, after a divider.
- **Do** add new colors as a token pair on `:root`, light and dark.
- **Do** show fields in dialogs and cards in the Well (`field`) so they stand out.
- **Do** check chart colors with the dataviz validator for both schemes before using them.
- **Do** keep every interface string in the translation dictionary in German and English.

### Don't:
- **Don't** leave native `<select>`, checkboxes or browser focus rings visible.
- **Don't** use green, orange or red decoratively.
- **Don't** give cards, lists or fields a shadow.
- **Don't** let elements of a group overlap with negative margins; the divider belongs to one element.
- **Don't** write comments into the HTML; the file is shipped to the browser.

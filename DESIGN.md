---
name: Telegram Campaign Manager
description: Persian RTL dispatch register for a local Windows operator.
colors:
  ink: "#1c3038"
  muted: "#566b74"
  accent: "#164e57"
  accent-soft: "#e4f0f0"
  paper: "#fff"
  ground: "#f3f6f7"
  line: "#dbe3e7"
  danger: "#a32632"
  warning: "#7c4d08"
  accent-hover: "#0d3c45"
  secondary-line: "#b8c8cf"
  secondary-hover: "#eaf0f2"
  field-line: "#b5c6cd"
  focus: "#42838e"
  status-neutral-bg: "#edf1f3"
  status-neutral-ink: "#435c67"
  status-good-bg: "#e5f2eb"
  status-good-ink: "#23613e"
  status-warning-bg: "#fff0d7"
  status-bad-bg: "#fbe9eb"
  status-bad-ink: "#932633"
  status-live-bg: "#e3eff4"
  status-live-ink: "#245e79"
typography:
  headline:
    fontFamily: '"Segoe UI", Tahoma, Arial, sans-serif'
    fontSize: "28px"
    fontWeight: 750
    lineHeight: 1.5
  title:
    fontFamily: '"Segoe UI", Tahoma, Arial, sans-serif'
    fontSize: "18px"
    fontWeight: 700
  body:
    fontFamily: '"Segoe UI", Tahoma, Arial, sans-serif'
    fontSize: "15px"
    lineHeight: 1.85
  label:
    fontFamily: '"Segoe UI", Tahoma, Arial, sans-serif'
    fontSize: "13px"
    fontWeight: 600
  mono:
    fontFamily: "Consolas, monospace"
rounded:
  panel: "12px"
  button: "7px"
  field: "6px"
  badge: "5px"
  banner: "8px"
spacing:
  control-gap: "8px"
  panel-padding: "22px"
  panel-stack: "22px"
  layout-gap: "26px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.paper}"
    rounded: "{rounded.button}"
    padding: "9px 18px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-secondary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.button}"
    padding: "9px 18px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.accent}"
    rounded: "{rounded.button}"
    padding: "5px 10px"
  button-danger:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.danger}"
    rounded: "{rounded.button}"
    padding: "9px 18px"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "9px 12px"
  panel:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.panel}"
  badge:
    backgroundColor: "{colors.status-neutral-bg}"
    textColor: "{colors.status-neutral-ink}"
    rounded: "{rounded.badge}"
    padding: "3px 9px"
---

# Design System: Telegram Campaign Manager

## Overview

**Creative North Star: "Dispatch register"**

The implemented interface uses cool white surfaces, slate text, and a deep petrol accent. It is a compact Persian RTL working environment with clear dividers, aligned fields, and persistent written status labels.

This document records the built system, using `static/style.css`, `static/index.html`, and `static/app.js` as its source. The direction and code-first implementation were authorized; this record does not claim visual approval.

**Key Characteristics:**

- Persian RTL structure with isolated mixed-direction identifiers.
- Flat bordered registers and compact rectangular controls.
- Written status labels supported by color and an active-state dot.
- Responsive navigation and message preview ordering.

## Colors

### Primary

Deep petrol (`accent`) identifies primary actions, links, checked controls, and navigation emphasis. Its pale companion (`accent-soft`) marks the current navigation item, review acknowledgement, and empty-state icon backgrounds. Primary hover uses `accent-hover`.

### Neutral

Cool white (`paper`) sits over a pale cool ground (`ground`). Slate ink (`ink`) carries main text, while `muted` carries hints, metadata, and secondary descriptions. `line` separates panels, rows, and regions. Fields and secondary controls use their dedicated border colors.

Status colors are functional: green for connected, ready, completed, or sent; amber for partial, paused, or uncertain; red for failures, restrictions, disconnection, or cancellation; blue for active collection or delivery. Unclassified and pending statuses use the neutral badge. Danger actions use `danger`; warning text uses `warning`.

**The Written State Rule.** Every status badge includes its Persian status word; color supplements that word.

## Typography

The interface uses the local Segoe UI, Tahoma, Arial, sans-serif stack. No web font is required. Consolas with a monospace fallback is reserved for technical identifiers and errors; tabular numerals support comparison.

The headline role is the page title and becomes smaller on narrow screens (24px). Section titles use the title role; third-level headings use the body size with heading weight. Tables and secondary descriptions use smaller text (13px), and metadata, hints, and badges use compact text (12px). Body paragraphs are capped at a readable measure (72ch); empty-state guidance is narrower (46ch). Form labels use the label role.

## Layout

The document declares Persian language and RTL direction. On desktop, a sticky right navigation rail (228px) stands beside the workspace. A top bar separates local connection context from content. The main content is centered within a maximum width (1520px), with desktop padding (36px 38px 48px). The working register shares a grid with an instructional column (260px).

At widths of at least 1500px, the guide becomes wider (280px), the main top padding increases (44px), and the grid gap increases (36px). At 1150px and below, the rail narrows (200px), the guide moves below the register, and campaign detail becomes one column with the preview region first. At 720px and below, the rail becomes a top region with horizontally scrollable navigation; forms become one column, page actions wrap beneath the heading, and main padding becomes compact (24px 16px 32px).

Tables retain column structure inside their own scrolling wrapper, except account, saved-list, and campaign overview records at 720px and below. Those records become two-column stacked grids (10px 16px gaps, 16px padding), with full-width identity and wrapped action rows; their action buttons have a minimum height (36px). Recipient tables retain their scrolling wrapper. Usernames and phone numbers use bidirectional isolation; dedicated technical notes may use LTR direction. Message text uses automatic direction and wraps long content.

## Elevation & Depth

Panels, navigation, forms, tables, and message previews use borders and tonal separation without box shadows. A fixed transient notice is the exception: it uses a soft shadow (`0 8px 24px #00000025`) to sit above the workspace.

## Shapes

The system uses compact rectangles with modest rounded corners. Panels and message bubbles have the broadest recurring radius; buttons, fields, badges, and banners use smaller radii from the frontmatter. The message bubble has one tighter corner (12px 12px 3px 12px). Circular forms are limited to numbered steps and small status dots.

## Components

### Buttons

Primary actions are solid petrol with white text. Secondary actions use white surfaces, slate text, and a visible border. Quiet row actions use transparent backgrounds with petrol text. Danger actions use white surfaces with red text and a subdued red border. All variants use semibold text, short background transitions, and a visible keyboard focus outline (3px with a 3px offset). Disabled buttons reduce opacity (.48) and show a disabled cursor.

### Deletion and cleanup

Account, list, and campaign rows pair their ordinary actions with compact red delete controls; list and campaign detail headers use the existing full-size danger variant. Native browser confirmations explain the effects before deletion: account removal clears the local session while preserving Telegram accounts and historical report labels; source-list removal preserves existing campaign snapshots; campaign removal clears local recipients and delivery reports while retaining already-sent Telegram messages. Unfinished campaigns using a removed sender require replacement accounts and another preview review.

Accounts also contains a divided orphan-photo cleanup section with a secondary action and explanatory copy limiting removal to photos unused by any campaign. Deletion and cleanup controls are disabled during active jobs. An account whose cleanup failed remains as an unavailable row with a written retry-delete action; successful removal refreshes the row set and count. Notices report deletion results or cleanup warnings. These additions reuse the existing danger, secondary, field, panel, and status treatments.
### Inputs / Fields

White fields have a visible cool border, aligned labels, and a minimum height (43px). Textareas have a taller minimum (140px), vertical resizing, and generous line height (1.9). Checkboxes retain native semantics with the petrol accent. Hints remain adjacent to the field.

### Collection method and history range

The collection form reuses the existing full-width method select, divided form section, two-column field grid, and mobile single-column layout. Choosing message authors reveals the history range controls. All accessible history is the default; the days field retains its prefill (30) while disabled. A limited range enables and requires an integer days-back value (1–36500). Member-list collection hides the history section and disables its days field.

Saved-list metadata identifies CSV, group members, or chat history and its selected range. Supporting text explains the fixed collection-start boundary, identifiable authors, possible former members, and omission of message contents. These controls extend the incumbent form without changing its visual tokens.
### Navigation

Each destination pairs a line icon with a Persian label. The current page uses a pale petrol background and petrol text; hover uses a subtle cool wash. The mobile navigation remains a visible horizontal list. A keyboard skip link appears on focus.

### Cards / Containers

Bordered white panels organize tables and forms. A divided header contains the section title and optional count or action. Panel bodies use the frontmatter padding, reduced on mobile (18px 16px). Tables use compact headers, row dividers, and a light hover background; names and metadata occupy separate lines where needed.

### Status badges

Small rounded labels pair written state with semantic foreground and background colors. Active states add a small leading dot. Banners provide persistent state notes and relevant controls; a paused campaign uses the warning banner treatment.

### Review and message preview

The message preview uses a cool tinted field behind a white message bubble. An optional image is contained within the bubble. The review acknowledgement uses pale petrol and a native checkbox; confirming review makes the start control available. Campaign details keep the preview ahead of the recipient table at narrower widths.

Live campaign updates preserve focus on an equivalent available action. If an action disappears, focus moves to the refreshed controls region. Reduced-motion preference removes transitions and animation. The implemented transitions are short background changes (180ms) and progress changes (300ms), both using the source easing curve.

## Do's and Don'ts

### Do:

- Do preserve Persian RTL layout and isolate mixed-direction identifiers.
- Do keep status words visible alongside their semantic colors.
- Do use bordered white panels and aligned compact controls for operational content.
- Do keep message preview before recipient details when the detail grid collapses.
- Do retain visible keyboard focus and the reduced-motion override.

### Don't:

- Don't replace status words with color alone.
- Don't add shadows to ordinary register panels.
- Don't let wide tables force horizontal scrolling on the entire page.
- Don't claim a visual approval or live Telegram verification from the recorded fixture review.

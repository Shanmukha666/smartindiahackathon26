---
name: IP-SAKTI Sahayak
colors:
  surface: '#f8f9ff'
  surface-dim: '#ccdbf4'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eff4ff'
  surface-container: '#e6eeff'
  surface-container-high: '#dde9ff'
  surface-container-highest: '#d5e3fd'
  on-surface: '#0d1c2f'
  on-surface-variant: '#404942'
  inverse-surface: '#233144'
  inverse-on-surface: '#ebf1ff'
  outline: '#707971'
  outline-variant: '#c0c9c0'
  surface-tint: '#2d6a48'
  primary: '#003820'
  on-primary: '#ffffff'
  primary-container: '#0f5132'
  on-primary-container: '#84c39b'
  inverse-primary: '#95d4ac'
  secondary: '#a14009'
  on-secondary: '#ffffff'
  secondary-container: '#fd844c'
  on-secondary-container: '#6a2500'
  tertiary: '#002584'
  on-tertiary: '#ffffff'
  tertiary-container: '#173baa'
  on-tertiary-container: '#a0b1ff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#b0f1c7'
  primary-fixed-dim: '#95d4ac'
  on-primary-fixed: '#002111'
  on-primary-fixed-variant: '#0f5132'
  secondary-fixed: '#ffdbcd'
  secondary-fixed-dim: '#ffb596'
  on-secondary-fixed: '#360f00'
  on-secondary-fixed-variant: '#7d2d00'
  tertiary-fixed: '#dde1ff'
  tertiary-fixed-dim: '#b8c4ff'
  on-tertiary-fixed: '#001453'
  on-tertiary-fixed-variant: '#173bab'
  background: '#f8f9ff'
  on-background: '#0d1c2f'
  surface-variant: '#d5e3fd'
typography:
  display-lg:
    fontFamily: Public Sans
    fontSize: 40px
    fontWeight: '700'
    lineHeight: 48px
    letterSpacing: -0.02em
  display-lg-mobile:
    fontFamily: Public Sans
    fontSize: 30px
    fontWeight: '700'
    lineHeight: 38px
    letterSpacing: -0.015em
  headline-xl:
    fontFamily: Public Sans
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.015em
  headline-xl-mobile:
    fontFamily: Public Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-lg:
    fontFamily: Public Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Public Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.005em
  headline-sm:
    fontFamily: Public Sans
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: 0em
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 26px
    letterSpacing: 0em
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
    letterSpacing: 0em
  body-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0.005em
  label-lg:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: 0.01em
  label-md:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.02em
  label-sm:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.03em
  code-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.02em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1.5rem
  gutter-mobile: 1rem
  margin: 2rem
  margin-mobile: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2rem
---

## Brand & Style

This design system establishes an authoritative, institutional civic-tech aesthetic designed for Indian Intellectual Property legal compliance, bio-resource access verification, and the Traditional Knowledge Digital Library (TKDL). The visual signature combines the dignity and permanence of sovereign institutions with the responsiveness, precision, and speed of modern regulatory SaaS platforms.

The personality balances unshakeable legal certainty with clear technological execution. Interfaces prioritize high information density without visual chaos, establishing immediate trust for IP attorneys, patent examiners, research institutes, and corporate compliance officers auditing claims under the Indian Patent Act (notably Section 3(p)), the Biological Diversity Act 2002, and reciprocal WIPO treaties.

The visual style employs crisp slate surfaces, subtle structural hairline dividers, balanced geometric alignment, and restrained status accents. The interface avoids frivolous ornamental patterns, heavy skeuomorphism, or loud neon gradients, relying instead on razor-sharp typography, deliberate whitespace ratios, and clear compliance badges that signal audit readiness and statutory rigor.

## Colors

The color palette is built around sovereign public-sector authority, bio-heritage context, and precise legal verification:

- **Primary (`#0F5132` - Deep Sovereign Emerald):** Signifies legal stewardship, bio-diversity protection, and authoritative verification. Deployed across navigation frameworks, primary interactive triggers, active tab indicators, and verified clearance badges.
- **Secondary (`#C05621` - Warm Saffron Ochre):** Evokes traditional knowledge, ancient Ayurvedic treatises, and heightened regulatory scrutiny. Deployed strictly for statutory alerts, Section 3(p) prior art flags, advisory warnings, and secondary action touchpoints.
- **Tertiary (`#1E40AF` - WIPO Civic Blue):** Represents multilateral legal frameworks, global patent databases, international priority searches, and formal treaty alignments.
- **Neutral (`#334155` - Slate Gray):** Anchors all data-dense tables, legal statutes, body narratives, borders, and structured surface tiers, eliminating visual fatigue across prolonged document examination sessions.

### Functional Palette Tiers
- **Canvas Base:** `#F8FAFC` (Slate 50) establishes a clean, glare-free, non-pure-white reading foundation.
- **Surface Elevation:** `#FFFFFF` (Solid White) for interactive modules, inspection cards, and compliance drawers.
- **Borders & Rules:** Hairline `#E2E8F0` (Slate 200) for standard layout grids; `#CBD5E1` (Slate 300) for active form fields and component perimeters.
- **Status & Compliance:**
  - *Certified / Non-infringing:* `#0F5132` text on `#ECFDF5` container.
  - *Statutory Review Required / Section 3(p):* `#9A3412` text on `#FFFBEB` container.
  - *Prohibited / Non-Patentable:* `#991B1B` text on `#FEF2F2` container.
  - *International Treaty Pending:* `#1E40AF` text on `#EFF6FF` container.

## Typography

The typographic architecture combines **Public Sans** for display, section headers, and statutory metadata banners, with **Inter** for dense analytical narratives, multilingual scientific names, and interface controls.

Public Sans imparts structural rectitude derived from official civic guidelines, projecting unassailable institutional authenticity. Inter provides vertical metrics optimized for screen legibility, high x-height for cross-referencing Sanskrit/Ayurvedic botanical nomenclature alongside Latin equivalents, and tabular numerals that prevent alignment drift in numerical patent claim comparisons.

Text hierarchy maintains high contrast ratios (exceeding WCAG AAA for legal text blocks). Letter spacing is marginally condensed on large displays to maintain visual density and expanded on labels and statutory status markers to preserve legibility at micro scales.

## Layout & Spacing

The layout is built on a responsive 12-column grid system paired with an 8pt structural rhythm. This handles analytical tools like split-pane TKDL formula comparisons, citation lineage graphs, and statutory compliance checklists.

- **Desktop (>= 1280px):** 12 columns, 24px (`1.5rem`) gutters, 32px (`2rem`) page margins. Maximum content boundary capped at 1600px to maintain line lengths within optimal legal reading measures (65–75 characters per line).
- **Tablet (768px – 1279px):** 8 columns, 16px (`1rem`) gutters, 24px (`1.5rem`) outer canvas margins. Multi-pane claim views stack into sequential vertical cards with persistent anchored tabs.
- **Mobile (< 768px):** 4 columns, 16px (`1rem`) gutters, 16px (`1rem`) canvas margins. Sidebars collapse into an off-canvas drawer; tables transition into stacked key-value verification lists.

Component padding relies strictly on `space-*` tokens:
- Micro actions and badge insets: `space-xs` (4px) to `space-sm` (8px).
- Internal input and cell padding: `space-sm` (8px) to `space-md` (16px).
- Container framing and inspection cards: `space-md` (16px) to `space-lg` (24px).
- Section boundaries and module separations: `space-xl` (32px).

## Elevation & Depth

Visual hierarchy uses low-contrast outlines paired with restrained surface tiers rather than heavy dramatic shadows, reinforcing a clean regulatory aesthetic.

Depth is expressed through three structural methods:

1. **Surface Tiers:**
   - *Canvas Background (`#F8FAFC`):* Base level for overall platform shell.
   - *Panel Surface (`#FFFFFF`):* Elevated workspace for document inspection cards, form clusters, and analysis engines.
   - *Sub-Container Layer (`#F1F5F9`):* Recessed zones for citation code blocks, historical document transcripts, and nested Ayurvedic reference excerpts.

2. **Low-Contrast Structural Outlines:**
   - All interactive and data containers are framed with a precise 1px border (`#E2E8F0`).
   - Active, focused, or flagged containers upgrade to a 1px border in `#0F5132` (Primary) or `#C05621` (Statutory Review Required).

3. **Subtle Elevation Shadows:**
   - *Level 1 (Card Default):* `0 1px 2px 0 rgba(15, 23, 42, 0.04)`, `0 1px 1px 0 rgba(15, 23, 42, 0.02)`
   - *Level 2 (Dropdowns, Overlays, Active Hover):* `0 4px 6px -1px rgba(15, 23, 42, 0.07)`, `0 2px 4px -2px rgba(15, 23, 42, 0.04)`
   - *Level 3 (Modal Modifiers, Drawer Panels):* `0 12px 24px -4px rgba(15, 23, 42, 0.12)`, `0 4px 8px -2px rgba(15, 23, 42, 0.04)`

## Shapes

The design system uses a strict **Soft (`1`)** roundedness standard. This subtle 4px corner treatment delivers a modern software experience while avoiding overly playful pill-shapes that conflict with statutory authority.

- **Base Radius (`0.25rem` / 4px):** Standard controls, text input fields, action buttons, dropdown menus, table row containers, and statutory status chips.
- **Large Radius (`0.5rem` / 8px):** Primary analytical modules, regulatory verification summaries, and document canvas modals.
- **Extra Large Radius (`0.75rem` / 12px):** Top-level system drawers, onboarding walkthrough modules, and global search containers.
- **Pill Shape (`9999px`):** Reserved exclusively for discrete numerical counters, active system health status pings, and TKDL entry accession code tags.

## Components

### Buttons
- **Primary:** Background `#0F5132`, foreground `#FFFFFF`, border 1px solid `#0F5132`. Hover: `#0B3D26`. Focus: 2px ring `#0F5132` with 2px offset.
- **Secondary (Statutory / Warning Action):** Background `#FFFBEB`, foreground `#9A3412`, border 1px solid `#FCD34D`. Hover: `#FEF3C7`. Focus: 2px ring `#C05621`.
- **Outline / Neutral:** Background `#FFFFFF`, foreground `#334155`, border 1px solid `#CBD5E1`. Hover: `#F8FAFC`. Focus: 2px ring `#94A3B8`.
- **Destructive:** Background `#FEF2F2`, foreground `#991B1B`, border 1px solid `#FECACA`. Hover: `#FEE2E2`.

### Statutory Compliance Badges & Chips
- Compact, high-legibility markers with uppercase `label-sm` tracking.
- **Section 3(p) Traditional Knowledge Exclusion:** `#FFFBEB` fill, `#9A3412` text, hairline `#FDE68A` border with an authoritative warning octagonal indicator icon.
- **National Biodiversity Authority (NBA) Clearance:** `#ECFDF5` fill, `#0F5132` text, `#A7F3D0` border with a shield-check icon.
- **WIPO PCT Priority Status:** `#EFF6FF` fill, `#1E40AF` text, `#BFDBFE` border with a globe icon.

### Cards & Modules
- Solid `#FFFFFF` fill with 1px `#E2E8F0` hairline boundary and Level 1 elevation.
- Header bands integrate a 3px left vertical indicator rule reflecting compliance state (Green for cleared, Amber for Section 3(p) alert, Slate for neutral).
- Explicit 16px internal padding (`space-md`) with structured divider lines separating metadata rows.

### Form Inputs & Search Fields
- Inset padding of 10px vertical by 14px horizontal.
- Borders use `#CBD5E1` resting; transitions to `#0F5132` with a 2px `#0F5132` ring at 15% opacity on focus.
- Micro-labels set in `label-md` uppercase with `#64748B` slate tint. Integrated right-aligned action slots for formula auto-fill, botanical synonym lookup, and patent publication numbers.

### Lists & Data Grids
- Alternating subtle rows (`#FFFFFF` to `#F8FAFC`) with border-bottom 1px `#F1F5F9`.
- Column headers set in `label-md`, uppercase, `#475569`, tracking 0.05em.
- Interactive rows provide `#F1F5F9` background hover feedback and a distinct `#0F5132` 2px left border marker upon row selection.

### Checkboxes & Radios
- Square 16px boxes with 3px corner rounding.
- Resting border `#94A3B8`. Checked fill `#0F5132` displaying a crisp white micro-check.
- Indeterminate states (for bulk claim selections) display a solid `#0F5132` centered dash.

### Specialized AI & Regulatory Components
- **Prior Art Conflict Inspector:** Two-pane comparative drawer contrasting English patent claims against translated Ayurvedic Sanskrit slokas with matching term highlights.
- **Statutory Audit Stepper:** Linear progression bar tracking filings across Form 1, Section 3(p) clearance, NBA Approval Form III, and final Controller General verification.
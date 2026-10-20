---
name: Typeset
description: A monochrome, light-first system that reads like a beautifully set README — whitespace and typography do the work, with the repo's own file tree as the memorable hook.
colors:
  background: "oklch(0.99 0 0)"
  foreground: "oklch(0.16 0 0)"
  card: "oklch(1 0 0)"
  card-foreground: "oklch(0.16 0 0)"
  primary: "oklch(0.16 0 0)"
  primary-foreground: "oklch(0.99 0 0)"
  secondary: "oklch(0.965 0 0)"
  secondary-foreground: "oklch(0.16 0 0)"
  muted: "oklch(0.965 0 0)"
  muted-foreground: "oklch(0.52 0 0)"
  border: "oklch(0.92 0 0)"
  input: "oklch(0.92 0 0)"
  ring: "oklch(0.556 0 0)"
  destructive: "oklch(0.577 0.245 27.325)"
  destructive-foreground: "oklch(0.99 0.01 240)"
typography:
  display:
    fontFamily: Schibsted Grotesk Variable
    fontSize: 72px
    fontWeight: 600
    lineHeight: 1.02
    letterSpacing: -0.02em
  h1:
    fontFamily: Schibsted Grotesk Variable
    fontSize: 32px
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: -0.02em
  h2:
    fontFamily: Schibsted Grotesk Variable
    fontSize: 24px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: -0.015em
  body-md:
    fontFamily: Schibsted Grotesk Variable
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.6
  body-sm:
    fontFamily: Schibsted Grotesk Variable
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.5
  label-caps:
    fontFamily: JetBrains Mono Variable
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1
    letterSpacing: 0.2em
  mono-code:
    fontFamily: JetBrains Mono Variable
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.6
  mono-sm:
    fontFamily: JetBrains Mono Variable
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: 4px
  md: 6px
  lg: 8px
  xl: 12px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 32px
  xl: 64px
  section: 96px
  gutter: 24px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.lg}"
    padding: 20px
  button-primary-hover:
    backgroundColor: "{colors.primary}"
  button-secondary:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.secondary-foreground}"
    rounded: "{rounded.lg}"
  input:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.card-foreground}"
    rounded: "{rounded.lg}"
    padding: 24px
  button-destructive:
    backgroundColor: "{colors.destructive}"
    textColor: "{colors.destructive-foreground}"
    rounded: "{rounded.lg}"
  separator:
    backgroundColor: "{colors.border}"
  input-border:
    backgroundColor: "{colors.input}"
  focus-ring:
    backgroundColor: "{colors.ring}"
  muted-chip:
    backgroundColor: "{colors.muted}"
    textColor: "{colors.muted-foreground}"
    rounded: "{rounded.md}"
---

## Overview

The system is a **Typeset README** — the product is a TanStack Start starter, so the UI borrows the vernacular of its subject: mono paths, a copyable terminal line, and the prose rhythm of a spec document. Light is the default (paper), dark is an inverted ink; the palette stays strictly monochrome.

- **One risk, fully committed:** the “What’s inside” inventory is an annotated directory tree set in JetBrains Mono with real box-drawing characters. No cards, no icons — a tree is what a template _is_, so the structure encodes truth.
- **Restraint elsewhere:** hairline rules and whitespace separate sections; a single hero fade-in is the only motion; underlines carry links; focus rings are neutral gray.
- **Audience:** developers evaluating a foundation. The page’s single job is to name what’s wired (auth, Drizzle/Postgres, Resend, S3 presign, Testcontainers, Playwright, Sentry/OpenTelemetry) and get them to `git clone` → `bun dev`.

## Colors

Light-first. Dark inverts background/foreground and softens muted/border to translucent white stops so hairlines remain subtle. No chromatic accent — pure grayscale; destructive red is reserved for errors and destructive actions.

- **Background (oklch(0.99 0 0)):** paper white; page and section grounds.
- **Foreground (oklch(0.16 0 0)):** near-black ink for headings, primary buttons, and body emphasis.
- **Card (oklch(1 0 0)):** slightly lifted mono-code and form surfaces.
- **Muted (oklch(0.965 0 0)) / Muted-foreground (oklch(0.52 0 0)):** secondary text, captions, tree annotations, and the “TANSTACK START TEMPLATE” eyebrow.
- **Border (oklch(0.92 0 0)) / Input (oklch(0.92 0 0)):** hairline dividers, table rules, card strokes.
- **Primary (oklch(0.16 0 0)) / Primary-foreground (oklch(0.99 0 0)):** solid ink buttons; hover is a subtle opacity shift, not a hue shift.
- **Ring (oklch(0.556 0 0)):** neutral focus ring.
- **Destructive (oklch(0.577 0.245 27.325)):** error states and destructive actions (delete note, delete passkey, delete account).

Dark: background oklch(0.155 0 0), foreground oklch(0.96 0 0), card oklch(0.185 0 0), muted oklch(0.235 0 0), muted-foreground oklch(0.68 0 0), border white/12%, input white/16%, ring oklch(0.68 0 0), destructive oklch(0.704 0.191 22.216).

## Typography

Two faces. Schibsted Grotesk Variable carries voice; JetBrains Mono Variable carries structure.

- **Display / H1 / H2:** Schibsted Grotesk Variable, 600, tight tracking (-0.02em → -0.015em), leading 1.02–1.1. The hero “Start from done.” is set at 48–72px (text-5xl → text-7xl, tight) to make the typesetting itself the memorable move.
- **Body-md / Body-sm:** Schibsted Grotesk Variable, 400, 16px/14px, leading 1.6/1.5 for readable paragraphs and table copy.
- **Label-caps:** JetBrains Mono Variable, 500, 12px, tracking 0.2em, uppercase, muted-foreground — used for eyebrows (“TANSTACK START TEMPLATE”, “QUICKSTART”, section labels) and table headers.
- **Mono-code / Mono-sm:** JetBrains Mono Variable, 400, 14px/12px — the quickstart block, tree glyphs, and upload keys. The `$` prompt glyph stays muted-foreground.

Pairing is deliberate: a slightly quirky grotesk (not the default Inter) against a developer-mono that developers already associate with tool output.

## Layout

Single centered column, max 56rem (max-w-4xl, px-6). Interior reading measure for prose is ~40rem via `max-w-xl` constraints; the tree and definition list use the full width. Sections are separated by hairline `border-t border-border` and generous whitespace (py-20 / pt-16 / mt-12), not by cards.

- **Grid:** not a 12-col broadsheet — one column, with the tree rendered as flex rows (`w-64` path column + flexible note) that stack on small viewports.
- **Spacing scale:** 4 / 8 / 16 / 32 / 64 / 96 (section). Content breathes; the hero (py-20 md:py-28) is deliberately tall before the first rule.
- **Header:** sticky, h-14, `border-b border-border bg-background`, mono wordmark `tanstack-start` (text, not image), right-aligned GitHub + theme toggle.

## Elevation & Depth

Flat. No shadows, no blurs, no gradients. Hierarchy comes from type scale, weight, color (ink vs. muted), and hairline rules. Cards that existed previously (glass-card, glass-tile) were removed; the remaining “cards” are plain bordered containers (`border border-border bg-card rounded-md`) for the quickstart block only. The note table and file upload are border-t sections, not elevated surfaces.

## Shapes

Minimal radius. `--radius: 0.5rem (8px)` — `rounded-md` for inputs, `rounded-lg` for buttons and the quickstart block. No pill, no 3xl. The language is softly rectangular, engineered rather than bubbly, consistent with a spec-document tone.

## Components

- **Primary button:** `bg-primary text-primary-foreground h-10 px-5 rounded-md text-sm font-medium`, hover opacity-80, focus ring `ring-ring/50`. Used for “Get started” and “Continue with email”.
- **Secondary / outline button:** `variant="outline"` — `border-border bg-background` with `hover:bg-muted`; used for “Sign in with passkey”, “Continue with Google”, “Choose file”.
- **Links (text):** `text-foreground underline decoration-border underline-offset-4 hover:decoration-foreground`. The hero secondary link and “Account settings” use this; header/footer nav links are `text-muted-foreground hover:text-foreground` (with underline on hover for the doc links).
- **Input:** `h-9 border-input rounded-md bg-background px-3 text-sm`, focus `ring-ring/50`.
- **Table:** `border-b border-border` header, `border-b border-border/60` rows, destructive icon button for delete. Table cells use the primitive's own typography; table-level treatments belong in `src/components/ui/table.tsx`.
- **Quickstart block:** `border border-border bg-card rounded-md p-4`, mono 12–14px, `$` muted prefix, absolute `bg-card` copy button (Copy/Check icons).
- **Theme toggle:** two 32px square icon buttons, active `bg-primary text-primary-foreground rounded-md`, inactive `text-muted-foreground hover:text-foreground`.

## Do's and Don'ts

- Do keep the palette grayscale — add chromatic color only for destructive states; do not reintroduce an accent hue.
- Do use the directory tree for inventories that _are_ file trees; don’t use 01/02/03 numerals where order carries no information.
- Do preserve `text-muted-foreground` for annotations and eyebrows, `text-foreground` for truths — don’t mute headlines.
- Do keep `max-w-4xl` as the outer measure and `max-w-xl` for prose; don’t introduce dense multi-column broadsheet grids.
- Do keep motion to the single hero `fade-in`; don’t re-add staggered `slide-in` or `glass` blur choreography.
- Do maintain the mono wordmark (`tanstack-start`); don’t reintroduce remote TanStack SVG logos.
- Do respect `prefers-reduced-motion` (global 0.01ms override) and keep keyboard focus visible via neutral rings.

## Lint rules

`@shadcn/lint` enforces this system through six Oxlint rules. Each rule reports the approved fix, and `settings.shadcn.note` in `.oxlintrc.json` appends a pointer back to this file.

| Rule                            | Enforces                                                                                                                    |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `shadcn/no-restyle`             | Components own their appearance; call sites pass only `layout` classes. The `Skeleton` contract also allows `rounded-full`. |
| `shadcn/no-raw-colors`          | Theme tokens instead of raw palette classes such as `bg-pink-500`.                                                          |
| `shadcn/no-arbitrary-values`    | The theme scale instead of one-off values such as `p-[13px]`; `layout` values are exempt.                                   |
| `shadcn/no-inline-styles`       | No `style={}` props or `<style>` elements; styling stays in Tailwind classes.                                               |
| `shadcn/no-unknown-classes`     | Only classes the project's Tailwind setup can generate.                                                                     |
| `shadcn/require-static-classes` | Class strings the linter can read; no `` `bg-${color}` ``.                                                                  |

Approved exceptions live in the `overrides` array of `.oxlintrc.json`. `src/components/ui/**` has its own block because those files are upstream shadcn components this design system does not own, and `src/features/emails/**` turns off `no-inline-styles` because email clients need them. Individual upstream components allowlist or disable `no-unknown-classes` and `no-inline-styles` where their internals defeat static analysis.

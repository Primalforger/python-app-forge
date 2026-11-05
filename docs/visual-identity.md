# Forge Universe visual system

Python App Forge uses a restrained, blue-dominant visual identity. The interface
should remain a professional developer workspace; the Aura Guild is a secondary
personality layer and must never compete with project information or controls.

## Brand palette

| Role | Light | Dark |
|---|---|---|
| Primary blue | `#2563EB` | `#3989E8` |
| Green status | `#087A55` | `#45C99A` |
| Purple accent | `#6D42C7` | `#A88AEF` |
| Background | `#F4F7FB` | `#111827` |
| Surface | `#FFFFFF` | `#192438` |
| Text | `#172033` | `#F1F5FB` |

Blue is the primary interaction color. Green communicates healthy or successful
states. Purple is reserved for optional advanced-feature accents. Neutral
surfaces provide most of the visual area.

## Interface principles

- Prefer clear hierarchy, consistent spacing, and restrained borders.
- Use shared Qt stylesheet tokens rather than screen-specific color literals.
- Keep focus indicators visible in both themes.
- Preserve readable contrast for text and status indicators.
- Avoid excessive glow, gradients, and decorative backgrounds.
- Keep data-driven dashboard content factual; never substitute mock metrics
  or example projects for live application data.
- Mascots are optional illustrations for welcome, empty, or completion states.
  They must not obscure actions, status, or project information.
- Respect reduced-motion preferences for any future animation.

## Implementation

The canonical palette and Qt stylesheet live in
`src/app_forge/gui/theme.py`. `check_theme()` exposes contrast checks for
the core text and status color pairs. Changes to the palette should update
the theme tests and this document together.

The logo and Aura Guild artwork will be added as separate, optimized assets
after each design is approved. Do not use generated dashboard mockup text or
sample metrics as application content.

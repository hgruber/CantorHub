# CantorHub Frontend Design Guide

Apply this design system when building or modifying UI. The full reference is
`docs/frontend.md`; the hard rules are in `CLAUDE.md` („CSS uses tokens only", „Font sizes in
`rem`").

## Colours are tokens, never literals

Every colour comes from a custom property in the `:root` block of
`intern/static/intern/css/intern.css`, and every new one needs a `[data-theme="dark"]` value.

| Role | Token |
|---|---|
| Accent (configurable, `BRAND_FARBE`) | `--brand` |
| Accent as a **fill** with white text, and for lines | `--brand-dark` |
| Accent as a **letter** on a surface | `--brand-text` |
| Tinted background / focus ring | `--brand-light` / `--brand-ring` |
| App background / card | `--bg-app` / `--bg-card` |
| Text, strongest to faintest | `--t1` … `--t4` |
| Borders | `--border` / `--border-dark` |
| Table head / alternating row / hover | `--bg-thead` / `--bg-row-alt` / `--bg-row-hover` |
| Warnings | `--warn-bg`, `--warn-border`, `--warn-text`, `--warn-strong`, `--warn-icon` |
| Voices | `--stimme-s/a/t/b` (fill) and `--stimme-*-text` (letter) |
| Permission categories | `--kat-1` … `--kat-6` |

The accent is set per installation; never write its value into a stylesheet.

## Layout

```
┌─ .sidebar (--sb-width) ─┬─ .top-bar (--tb-h, white, icons right) ────┐
│ logo + VEREINSNAME_KURZ │ next-event banner (site-wide, dismissible) │
│ navigation              │ .content — the only scroll container       │
└─────────────────────────┴────────────────────────────────────────────┘
```

- Below 768 px the sidebar is off-canvas and opens with the ☰ button.
- No body scroll; pages that fill `.content` use `height: 100%`.

## Typography and shape

- `--font` for text, `--mono` for code; sizes as `calc(13rem / 14)` — never `px`.
- Radii `--r-sm` / `--r` / `--r-lg`, shadows `--shadow-xs` / `-sm` / `-md`.

## Components to reuse

`{% form_field %}`, `ChipMultiSelect` / `_chip_multiselect.html`, `_confirm_delete_dialog.html`,
`{% hilfe %}` tooltips, `_leaflet_map.html`, detail pages built from `.detail-card` /
`.detail-card-row`, off-canvas panels for filter and column choice. Logos and images through
`{% startseite_datei %}`, other assets through `{% static %}`.

## Do / Don't

- **Do** check dark mode for every change (`[data-theme="dark"]`).
- **Do** keep JavaScript vanilla, one file per concern, served from `intern/static/intern/`.
- **Don't** add CDN dependencies or choir-specific literals (`KeineChorliteraleTest`).
- **Don't** add page scrollbars; scrolling stays inside `.content` or a dedicated container.

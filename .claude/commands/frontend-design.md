# CantorHub Frontend Design Guide

Apply this design system consistently when building or modifying UI in this project.

## Colour palette

| Role | Value |
|---|---|
| Primary / accent | `#c14468` |
| Primary dark (hover) | `#a83a5a` |
| Top-bar background | `#c14468` |
| Sidebar background | `#eee` |
| Content background | `#f8f9fa` |
| Card / panel background | `#fff` |
| Body text | `#333` |
| Muted text | `#777` / `#888` |
| Section headings | `#a83a5a` |
| Error text | `#c53030` |
| Error background | `#fff5f5` |

## Layout structure

The page is a fixed-height shell — no body scroll. All scrolling happens inside `.content`.

```
┌─── .top-bar (fixed, 50 px) ────────────────────────────┐
├─── .layout (height: calc(100% - 50px), flex row) ──────┤
│  .sidebar (250 px)  │  .content (flex: 1, overflow-y)  │
└─────────────────────────────────────────────────────────┘
```

- **Top bar**: `height: 50px`, `background: #c14468`, `z-index: 1000`
- **Sidebar**: `width: 250px`, collapsible via `.collapsed` (sets `width: 0`)
- **Mobile** (`max-width: 768px`): sidebar is `position: fixed`, slides in with `.active` class

## Typography

- Body: `Arial, sans-serif`
- Tables / profiles: `"Segoe UI", Tahoma, Geneva, Verdana, sans-serif`
- `font-size: 0.95rem` for body text; `0.75rem` for timestamps
- Headings in wiki/profile sections: `color: #a83a5a`

## Component patterns

### Buttons
```css
background: #c14468;  color: white;  border: none;
padding: 10px 15px;   border-radius: 4px;
```
Hover: `background: #a83a5a`

### Cards / panels
```css
background: #fff;
box-shadow: 0 2px 5px rgba(0,0,0,0.1);
border-radius: 8px;
```

### Form inputs
```css
border: 1px solid #ccc;  border-radius: 4px;
padding: 0.5rem;         font-family: inherit;  font-size: 1rem;
box-sizing: border-box;
```

### Tables
- Container: `.table-container` (overflow-x, rounded, shadowed card)
- Sticky `thead th`, alternating rows `#fff` / `#fafafa`
- Sort arrows use `#c14468` (asc `↑`) / `#a53a5a` (desc `↓`)
- Row hover: `background: #f1f1f1`

### Offcanvas panels (Filter, ColumnSelector, PoolSelector)
- `position: fixed; top: 50px; right: -100%` — slides in via `.open` class
- `transition: right 0.3s ease`
- Specific z-index: `ColumnSelector` 103, `Action` 102, `Filter` 101

### Section headings (wiki / profile)
```css
color: #a83a5a;
border-bottom: 2px solid #c14468;
```

## CSS file

All styles live in `intern/static/intern/css/intern.css`. Add new rules there, grouped under a clearly labelled `/* === Section Name === */` comment block.

## Templates

- Base template: `intern/templates/base.html`
- All intern pages extend `base.html` and fill `{% block content %}`
- Use `{% static 'intern/...' %}` for asset URLs (not hardcoded `/static/` paths)
- Static JS/CSS assets: `intern/static/intern/`

## Do / Don't

- **Do** use the `#c14468` primary colour for interactive elements, active states, and accent borders.
- **Do** keep new panels as offcanvas (slide-in from right) rather than modals.
- **Don't** add new external CDN dependencies — bundle JS/CSS in `intern/static/intern/`.
- **Don't** add body/page scrollbars; keep scrolling confined to `.content` or specific scrollable containers.

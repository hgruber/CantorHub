---
name: Dark and Light Mode
description: "Dark/light mode toggle is live: CSS token block in intern.css, toggle button in sidebar footer, localStorage persistence, prefers-color-scheme fallback"
type: project
originSessionId: 2aa8bfbb-ac7a-48fe-933f-6cda1f033e02
---
Dark/light mode toggle is implemented. A `[data-theme="dark"]` CSS token block in `intern.css` provides dark values for all design tokens. A toggle button in the sidebar footer (sun/moon icon) swaps themes and persists to `localStorage`. An inline script in `base.html` head sets the theme before paint to avoid flash. Falls back to `prefers-color-scheme` when no stored preference exists.

**How to apply:** Any new color should use a CSS variable from `:root`. Add dark-mode values to `[data-theme="dark"]` if the variable is new. Avoid hardcoded hex colors in component styles.
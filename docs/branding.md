# Branding extraction plan (for open-sourcing)

**Goal:** make CantorHub deployable by any choir without editing source. All
"Just Gospel Frankfurt"–specific text, addresses, and logos must come from
configuration/assets, so the open-source default is generic and a deployer only
sets a few values.

This is a **plan for later**, not fully implemented. Do the rest as its own change set.
Note: `VEREINSNAME`/`VEREINSNAME_LANG`/`VEREINSNAME_KURZ` (text) and `BRAND_FARBE` (accent
colour, see `docs/configuration.md`) already landed outside this plan; the logo/photo assets and
the `Just Gospel`/`example.org` literals in `config/settings.py`, `config/urls.py`,
`intern/pdf.py`, `intern/forms.py` and `intern/static/intern/manifest.json` are still open.

## Homepage override (in progress)

Done: `DATEN/startseite/` overrides the shipped page file by file (`docs/startseite.md`), this
choir's page lives in its own repository checked out there, and the shipped page is a neutral
demo guarded by `NeutraleDemoTest`. Remaining:

1. Dynamic content: a placeholder contract plus whitelisted tags (`oeffentliche_termine`,
   `konfig` limited to public keys), sub-pages `seiten/<name>.html` → `/<name>/` as the last
   route, and wiki articles opted in through a `STARTSEITE_ARTIKEL` key, rendered by a public
   mode of `apply_replacements()` (no votes, internal links as plain text, no `/media/` embeds).

## Inventory of hardcoded branding

Found via `grep -rl "Just Gospel\|jg-frankfurt\|JG-Frankfurt\|Gospel\|Frankfurt"`.

### Text strings ("Just Gospel" / "Frankfurt")
- `intern/templates/base.html` — `<title>`, sidebar header
- `intern/templates/sidebar.html` — logo alt + `sidebar-title`
- `intern/templates/login.html` — welcome heading
- `intern/templates/dialog.html` — header
- `intern/templates/{400,403,404,500,503}.html` — title, alt text, wordmark span
- `intern/templates/titel.html` — audio-button logo alt
- `intern/replacements.py:523` — wiki footer `…Just Gospel!`
- `intern/tables.py:447` — audio player logo reference

### Email / domain identity
- `config/settings.py:190` + `intern/apps.py:26` — `DEFAULT_FROM_EMAIL`
  (now DB-config; default still `webmaster@example.org`)
- `intern/ejabberd.py`, `intern/apps.py` — XMPP host/MUC defaults reference the
  domain (already DB-config keys; just need generic defaults)

### Raster logos still choir-specific (`intern/static/intern/brand/`)
- `logo.png` — inline logo of every automated mail (`intern/mail.py`)
- `JG-Frankfurt-transparent.png` — PDF letterhead (`intern/pdf.py`)
- `icon-192.png`, `icon-512.png` + `intern/static/intern/manifest.json` (name, theme colour)
  — PWA install icon, also the notification icon (`intern.js`, `mail.py`)

  They need PNGs, which the SVG overlay cannot provide by itself; next step is the same lookup
  (`finde_statisch("logo.png")` etc.) with neutral PNGs rendered from `logo.svg` as defaults, and
  a manifest built from `Konfiguration`.

### Data convention (NOT pure branding — handle separately)
- Song filenames carry a literal `JG-` prefix (`JG-Titel` and `JG - Titel` are historically
  equivalent). This is a content/naming convention, not display branding — but it is **already
  configurable**: `FILE_PREFIX` in the `Konfiguration` table, read by
  `intern/views/files.py` (`_aufnahme_prefixes`). The two separators stay fixed. Nothing left
  to decide here; the key is what a deployer changes.

## Proposed approach

Reuse the existing `Konfiguration` key/value store + `app_settings` helpers — the
same mechanism this project already uses — so no new infrastructure.

### 1. New config keys (seed in `intern/apps.py` `_CONFIG_DEFAULTS`)
| Key | Generic default | Use |
|---|---|---|
| `SITE_NAME` | `CantorHub` | short wordmark (sidebar, `<title>` suffix) |
| `SITE_TITLE` | `CantorHub` | full org name (login heading, homepage) |
| `SITE_TAGLINE` | `` | optional subtitle on login/homepage |
| `DEFAULT_FROM_EMAIL` | `webmaster@example.org` | already exists; change default |

(Existing `EJABBERD_*` defaults should also be genericised to `example.org`.)

### 2. Expose to templates
Add `site_name`, `site_title`, `site_tagline` to
`config/context_processors.project_meta` (read once via `get_config`). Then every
template uses `{{ site_name }}` / `{{ site_title }}` instead of literals. This is
the bulk of the work — mechanical find-and-replace across the templates listed
above, plus `replacements.py` and `tables.py` (which build HTML in Python — read
config there directly).

### 3. Logo as a configurable asset — done for the SVG
The shipped logo is `intern/startseite/statisch/logo.svg`: the CantorHub seal (a tuning fork
stamped out of a disc, ring around it), in blue to match the default `BRAND_FARBE` `#2b6cb0`.
Every portal template, the wiki footer, the audio button and `/favicon.ico` reach it through
`startseite_datei("logo.svg")`, so an installation's `DATEN/startseite/statisch/logo.svg`
replaces it everywhere (`docs/startseite.md`). The other drafts were dropped once the seal was
chosen; this choir's logos live in its own homepage repository.

Two constraints the seal encodes, worth keeping in any successor:

- Colours are literals, not tokens — an SVG cannot read the CSS custom properties, and
  `BRAND_FARBE` is configurable, so a deployer who changes it replaces the logo too.
- Every colour is a presentation attribute; the embedded `<style>` only carries the
  `prefers-color-scheme: dark` override. Renderers that ignore CSS (librsvg, Inkscape's
  exporter, most SVG-to-PDF paths) would otherwise paint gradient stops black.

### 4. Favicon / PWA
The favicon follows the logo (`<link rel="icon">` and `/favicon.ico`). The PWA icons and the
manifest are still open — see „Raster logos" above.

## Suggested phasing
1. Text → `SITE_NAME`/`SITE_TITLE`/`SITE_TAGLINE` config + context processor +
   template/`.py` replacements. (Low risk, high coverage.)
2. Genericise email/XMPP defaults in `_CONFIG_DEFAULTS`.
3. Raster logos (mail, PDF, PWA) and the manifest — the SVG logo and favicon are done.
4. Decide on the `JG-` filename prefix convention (config key or documented
   convention) and document it.
5. README: add a "Branding / white-labelling" section listing the keys and the
   logo override path.

## Edge cases / watch-outs
- `replacements.py` and `tables.py` emit HTML from Python — they must call
  `get_config` directly (no template context there). Guard against the DB not
  being ready (these run per-request, so it's fine, but keep the helper's
  try/except fallback).
- Error pages (`500.html` etc.) may render when the DB/app is degraded — keep a
  hardcoded generic fallback (`{{ site_name|default:"CantorHub" }}`) so a broken
  DB doesn't blank the wordmark.
- Don't commit any deployer's real logo into the open-source default.
- The current `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` in `settings.py` also
  contain org hostnames; genericise or move to env vars as part of open-sourcing
  (separate from this branding pass, but related).

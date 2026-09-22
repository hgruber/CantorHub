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

## Inventory of hardcoded branding

Found via `grep -rl "Just Gospel\|jg-frankfurt\|JG-Frankfurt\|Gospel\|Frankfurt"`.

### Text strings ("Just Gospel" / "Frankfurt")
- `intern/templates/base.html` — `<title>`, sidebar header
- `intern/templates/sidebar.html` — logo alt + `sidebar-title`
- `intern/templates/login.html` — welcome heading
- `intern/templates/dialog.html` — header
- `intern/templates/{400,403,404,500,503}.html` — title, alt text, wordmark span
- `intern/templates/titel.html` — audio-button logo alt
- `templates/index.html` — public homepage copy
- `intern/replacements.py:523` — wiki footer `…Just Gospel!`
- `intern/tables.py:447` — audio player logo reference

### Email / domain identity
- `config/settings.py:190` + `intern/apps.py:26` — `DEFAULT_FROM_EMAIL`
  (now DB-config; default still `webmaster@example.org`)
- `intern/ejabberd.py`, `intern/apps.py` — XMPP host/MUC defaults reference the
  domain (already DB-config keys; just need generic defaults)

### Photo assets (`intern/static/intern/img/`)
- `chor-{800,1400,2000}.jpg` — choir photo used as homepage hero (`srcset`)
- `chor-band-{1100,1800}.jpg` — wide crop of the same photo, homepage gallery band

  Choir-specific content, not a logo: a deployer needs a way to supply their own
  picture (config key with a filer file ID, analogous to `SATZUNG_FILE_ID`, would fit).

### Logo assets (`intern/static/intern/images/`)
- `JG-Frankfurt-wG-color.svg` — primary logo, used in ~12 templates
- `JG-Frankfurt-G-color.svg`, `JG-Frankfurt-test.svg` — variants

  Caveat: these live in the **gitignored** `static/` (STATIC_ROOT) only, i.e. they are
  not in a checkout. `JG-Frankfurt-wG-color.svg` has been copied to the tracked source
  dir `intern/static/intern/images/`; the other two still need the same treatment.

### Wordmark (`intern/static/intern/brand/`)
- `JG-Frankfurt.svg` (black) / `JG-Frankfurt-transparent.svg` (light, for dark grounds) —
  the "Just Gospel! Frankfurt" lettering, used as headline image on the homepage.
  The letters are outlines; the original typeface (Showcard Gothic) is not embedded and
  cannot be licensed as a webfont, so a deployer replacing the branding replaces the SVG.

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

### 3. Logo as a configurable asset
The logo is binary, so it doesn't belong in the key/value table. Options, in
order of preference:
- **A (recommended):** ship a neutral default `logo.svg` in static; allow an
  override file at a known media path (e.g. `media/branding/logo.svg`) served if
  present, else fall back to the static default. Add a small uploader in
  `/intern/konfiguration/` later. Keeps the repo free of org-specific art.
- **B:** keep a static `logo.svg` filename and tell deployers to replace the
  file. Simplest, but mixes deployment state into the repo tree.

Rename the three `JG-Frankfurt-*.svg` files to generic names (`logo.svg`,
`logo-mono.svg`) and update the ~12 references in one pass.

Candidates for that neutral default sit in the repository root, none of them
wired into a template yet. The current round is `cantorhub_a.svg` … `_d.svg`:
four square 128×128 marks that share one identical tuning-fork silhouette and
differ only in what surrounds it — sound arcs (a), a circle of four voices (b),
a stamped-out seal (c), a staff of five lines (d). The two earlier drafts
`cantorhub_v1.svg` / `_v2.svg` are icon-plus-wordmark lockups and are
superseded; delete them once a mark is chosen.

Two constraints these files encode, worth keeping in any successor:

- Colours are the `--brand` / `--brand-dark` literals, not tokens — an SVG
  cannot read the CSS custom properties, and `BRAND_FARBE` is configurable, so
  a deployer who changes it replaces the logo too.
- Every colour is a presentation attribute; the embedded `<style>` only carries
  the `prefers-color-scheme: dark` override. Renderers that ignore CSS (librsvg,
  Inkscape's exporter, most SVG-to-PDF paths) would otherwise paint gradient
  stops black.

Pick one, move it to `intern/static/intern/images/` under the generic name, and
delete the rest. The square viewBox doubles as the favicon/PWA mark of step 4.

### 4. Favicon / PWA
Same files drive the favicon (`<link rel="icon">` in base + error pages). Fold
into the logo-asset step so the favicon tracks the configured logo.

## Suggested phasing
1. Text → `SITE_NAME`/`SITE_TITLE`/`SITE_TAGLINE` config + context processor +
   template/`.py` replacements. (Low risk, high coverage.)
2. Genericise email/XMPP defaults in `_CONFIG_DEFAULTS`.
3. Logo/favicon asset strategy (option A) + file renames.
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

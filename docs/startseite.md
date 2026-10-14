# Public homepage: shipped page and installation override

The public homepage is the first piece of the „one code base, a generic template, our
configuration on top" direction in `CLAUDE.md`. The code ships a page; an installation replaces
it **file by file** from its data volume, without a fork and without a rebuild.

## Where a page comes from

`settings.STARTSEITE_WURZELN` lists two roots, searched in this order:

1. `DATEN/startseite/` — the installation's own page (`/data/startseite/` in the container,
   `./startseite/` in development, which is why `.gitignore` lists it).
2. `intern/startseite/` — the page shipped with the code.

The first root that has a file wins; a missing root is skipped. Both roots have the same layout:

```
startseite/
  index.html     the homepage (a Django template)
  _*.html        partials, for {% include %} only
  statisch/…     images, CSS, fonts → served under /startseite/…
```

So an installation may start with nothing but its own `index.html` and keep using the shipped
CSS and images, or replace only one image.

## The `startseite` template engine

`home()` renders with `using="startseite"`, the second entry of `TEMPLATES` in
`config/settings.py`:

- **`DIRS = STARTSEITE_WURZELN`, `APP_DIRS = False`.** A template from the volume can neither
  shadow a portal template (`base.html`, error pages) nor include one; the portal engine does not
  see the homepage either. Shared snippets therefore come as tags, not as includes —
  `{% markenfarbe %}` repeats the one rule of `intern/templates/_brand_boot.html`.
- **No `cached.Loader`.** A changed page (`git pull` in the volume) is live on the next request,
  without a restart. The cost is one file read per page view of a single public page.
- **Same context processors** as the portal, so `vereinsname*`, `brand_farbe` and `VERSION` are
  there. `home()` adds `termine`, `homepage_ueber_uns`, `homepage_aufnahme`, `vereinsadresse`
  and `kontakt_email`.

**The Termine list (`termine`) follows `Termin.extern`, not `Termin.repertoire`:** `home()`
excludes only the two empty forms of the announcement text, so an event without one stays off the
page even when it is a public gig. The gig-reminder mails follow the same set —
`OHNE_ANKUENDIGUNG` in `intern/models.py` (see `docs/mailinglist.md`). The selection deliberately
checks the raw field while the rendered block checks the filter result (`extern_html`) — that is
how a single space lists an event without producing an empty box. That is also why the condition
measures the field's *length* instead of comparing it to `""`: MariaDB's `utf8mb4_general_ci`
pads strings for comparison, so `' ' = ''` is true there and a `= ""` filter dropped exactly the
gigs the space was meant to lift onto the page — visible only on the production database, never
on SQLite.

`StartseiteUeberlagerungTest` pins all of this, and checks that every file the shipped page
references exists.

## Files under `/startseite/`

A page links its files with `{% load startseite_tags %}` and
`{% startseite_datei "img/foto.jpg" %}`, which yields `/startseite/img/foto.jpg?v=<mtime>` from
the first root that has `statisch/img/foto.jpg`. **Not `{% static %}`**: `collectstatic` runs at
build time and never sees the volume.

- **Container:** nginx answers `/startseite/` itself (`nginx.conf`), with `try_files` over
  `/data/startseite/statisch/` and then `/app/intern/startseite/statisch/`. Only `statisch/` is
  reachable, never the templates next to it. With `?v=` the files are cached for a year, without
  it for an hour. The files must be readable by the nginx worker.
- **Without nginx** (`runserver`): `views.startseite_statisch` serves the same lookup
  (`finde_statisch()` in `intern/templatetags/startseite_tags.py`, path checked with
  `safe_join`). The route exists in production as well; nginx simply answers first.

## The portal logo

The same overlay carries the logo of the whole portal: `statisch/logo.svg`. The shipped one is
the blue CantorHub seal; an installation's `DATEN/startseite/statisch/logo.svg` replaces it on
the login and dialog pages, in the sidebar, on the error pages, the privacy policy and the join
form, in the wiki footer, on the audio buttons of the repertoire and as `/favicon.ico` (a
non-permanent redirect, so a changed logo reaches browsers). Templates load `startseite_tags`
next to `static` and call `{% startseite_datei 'logo.svg' %}`; Python (`tables.py`,
`replacements.py`) calls `startseite_datei("logo.svg")`. A test fails if any of them points at
the old `intern/brand/logo.svg` again or at a file the shipped page does not have.

The raster logos follow the same overlay, under `statisch/brand/`:

| File | Used by |
|---|---|
| `brand/icon-192.png` | inline logo of every automated mail (`mail.py`), `apple-touch-icon`, PWA icon, lock-screen artwork of the audio player (`intern.js`) |
| `brand/icon-512.png` | PWA icon, lock-screen artwork |
| `brand/briefkopf.png` | PDF letterhead (`pdf.py`), drawn 5.5 cm wide — keep the wide aspect (the shipped one is 1400 × 471) |

Python finds them with `finde_statisch()`, templates and the manifest with `startseite_datei`.
The shipped PNGs are rendered from `logo.svg`; an installation that replaces the SVG should
replace these three as well. The web app manifest is no static file any more but the view
`/manifest.webmanifest` (`views/auth.py`): name from `VEREINSNAME_LANG`, `theme_color` from
`BRAND_FARBE`, icons from this overlay.

## The shipped page and this choir's own page

`intern/startseite/` is a neutral demo (described under „Public homepage" in
`docs/frontend.md`): no photo, the CantorHub logo, every text from `Konfiguration`. `NeutraleDemoTest`
fails as soon as a file there names a choir or is a binary other than the three PNGs rendered
from the seal; `KeineChorliteraleTest` does the same for the whole code base.

This choir's page — photo, logos (including the three PNGs above), `main.css` and the design
notes in `GESTALTUNG.md` — lives in
the repository `cantorhub-jg-startseite`, checked out as `/data/startseite` on the server; a push
there is live on the next page view. Sub-pages (`seiten/<name>.html` → `/<name>/`), whitelisted
placeholders and public wiki articles are planned on top (`docs/branding.md`).

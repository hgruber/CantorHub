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

## Our own page

The production page of this choir is the shipped page at the moment. Next it moves into its own
repository, checked out as `/data/startseite` on the server; after that the shipped page becomes
a neutral demo without photos or choir names. Sub-pages (`seiten/<name>.html` → `/<name>/`),
whitelisted placeholders and public wiki articles are planned on top. The plan and its order
are in `docs/branding.md`.

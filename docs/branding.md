# Branding: what an installation sets, and what is left

**Goal:** CantorHub runs for any choir without editing source. The code ships neutral defaults
(the CantorHub name, the blue seal, `example.org` addresses); everything that names a choir comes
from the `Konfiguration` table and from files in `DATEN/startseite/`. Production is such an
installation: its values are stored in its database and its homepage repository
(`cantorhub-jg-startseite`) is checked out as `/data/startseite`.

## How an installation brands itself

**Text and colour — `Konfiguration`** (catalog in `intern/apps.py`, reference in
`docs/configuration.md`):

| Key | Shipped default | Where it shows |
|---|---|---|
| `VEREINSNAME` | `CantorHub` | mail greetings, privacy policy |
| `VEREINSNAME_LANG` | `CantorHub` | page titles, mail header, PDF letterhead, web app manifest, DAV collection names |
| `VEREINSNAME_KURZ` | `CantorHub` | sidebar, login heading, alt texts, wiki footer |
| `BRAND_FARBE` | `#2b6cb0` | accent colour of portal, mails, PDF, manifest `theme_color` |
| `DEFAULT_FROM_EMAIL` | `webmaster@example.org` | sender of every mail (the setup form asks for it) |
| `FILE_PREFIX` | `Chor` | file name prefix of the choir's own recordings and their label („Chor Aufnahme“) |
| `HOSTING_ANBIETER_*`, `DSB_*` | empty — required | privacy policy; while blank the settings banner reports them and the policy shows a visible marker |
| `MAP_CENTER_LAT`/`_LNG`, `MAP_DEFAULT_ZOOM` | centre of Germany, zoom 6 | overview map when `MAP_CENTER_ID` names no place with coordinates |

The code fallbacks in `app_settings.py` equal the catalog defaults. They only apply while a row
is missing — `_seed_config` writes every catalog key on start, so a changed default never
reaches an installation that already has the row.

**Images — `DATEN/startseite/statisch/`** (`docs/startseite.md`): `logo.svg` (portal logo,
favicon), `brand/icon-192.png` (mail logo, touch icon, PWA), `brand/icon-512.png` (PWA),
`brand/briefkopf.png` (PDF letterhead). The homepage itself is `DATEN/startseite/index.html`.

**Fallback avatars** (`kein_photo.png`, `bot.png`) are filer files in Backstage/Profilbilder; the
first-run setup ships neutral ones from `intern/avatare_ersatz/`. An installation replaces them
there like any other file.

## What guards it

- `KeineChorliteraleTest` fails as soon as code or a template under `intern/` or `config/`
  names the original choir (migrations and the test file excepted).
- `NeutraleDemoTest` does the same for the shipped homepage and allows exactly the three PNGs
  rendered from the seal.

## Left to do

1. **Dynamic homepage content.** A placeholder contract plus whitelisted tags
   (`oeffentliche_termine`, `konfig` limited to public keys), sub-pages `seiten/<name>.html` →
   `/<name>/` as the last route, and wiki articles opted in through a `STARTSEITE_ARTIKEL` key,
   rendered by a public mode of `apply_replacements()` (no votes, internal links as plain text,
   no `/media/` embeds).
2. **Internal identifiers.** The own recording is still called `jg` inside the code — the CSS
   class `audio-btn--jg`, `data-ctx-kind="jg"`, the `kind` argument in `tables.py`. Invisible to
   users; renaming touches Python, JS and CSS at once and buys nothing visible.
3. **Wiki footer.** `replacements.py` appends `!` to `VEREINSNAME_KURZ` („CantorHub!“) — a habit
   of the original choir that is kept so production stays as it is. A key for the footer text
   would settle it.

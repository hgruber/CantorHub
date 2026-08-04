# Frontend: pages, components, design system

No framework. Vanilla JS per concern in `intern/static/intern/js/`, htmx for the few partial
swaps, one stylesheet (`intern/static/intern/css/intern.css`) built entirely on CSS custom
properties. The public homepage is the one page outside all of this — see the last section.

## Detail pages

All list views use django-tables2 with clickable rows (`data-href` on `<tr>`). Each table row
navigates to a detail page. Detail pages have an edit button in the top bar (via `edit`/`id`
context variables rendered in `base.html`).

| URL pattern | View | Template |
|---|---|---|
| `/intern/forum/<id>/` | `forum_view` | `forum.html` |
| `/intern/forum/<id>/edit/` | `forum_edit` | `forum_edit.html` |
| `/intern/termin/<id>/` | `termin_view` | `termin.html` |
| `/intern/termin/<id>/edit/` | `termin_edit` | `termin_edit.html` |
| `/intern/titel/<id>/` | `titel_view` | `titel.html` |
| `/intern/titel/<id>/edit/` | `titel_edit` | `titel_edit.html` |
| `/intern/mitglied/<id>/` | `member_view` | `mitglied.html` |
| `/intern/mitglied/<id>/edit/` | `member_edit` | `member_edit.html` |
| `/intern/gallerie/<ordner_id>/` | `gallerie_view` | `gallerie.html` |

Detail pages use the `.detail-page` / `.detail-card` CSS layout (2-column card grid, single
column on mobile). Edit pages use the `.wiki` container with `.form-grid`.

## Form fields

**Rendered via the `{% form_field %}` inclusion tag** (`intern/templatetags/form_tags.py` →
`_form_field.html`): `{% form_field form.feld "Label" %}` emits the standard `form-group`
(label, widget, `invalid-feedback` errors). Options: `req=True` shows the `*` marker when the
field is required (join form), `privacy=form.priv_x` appends the "verbergen" checkbox when
`can_set_privacy` is in the context (member edit), `hilfe=True` renders `help_text` (opt-in so
Django's default help texts, e.g. on `username`, don't leak in). Without `label` the form
field's own label is used. Non-standard groups (checkbox rows, label-less textareas, the
search-select Ort widget, static read-only rows) stay hand-written.

## Multiple selection as chips

Every multi-select in the project goes through one component: the chosen entries sit on top as
chips, below them a search box and a scrollable pool of what is left. Entries move by click, by
drag (SortableJS), or — on touch devices — via a target popover opened with a 500 ms
long-press.

- **`intern/templates/_chip_multiselect.html`** is the only markup, with two entry points.
  Forms use the `ChipMultiSelect` widget (`intern/forms.py`, built like `TriStateToggle`),
  which sets the partial as `template_name` and fills the contract in `get_context()`. Pages
  without a Django form — the three permission pages — `{% include %}` the same partial and
  build their `eintraege` with `chip_eintraege(objekte, ausgewaehlt, label_attr="name")`
  (`views/_auswahl.py`), which yields the `{id, label, selected}` dicts the partial expects.
  Options:
  `auswahl_label`, `vorrat_label`, `such_platzhalter`, `leer_text`, `suche_ab` (search box only
  from N entries, default 8) and `variante="exclude"` for the red styling of the „Nicht in
  Gruppen" filter.
- **The `<select multiple>` stays the single source of truth.** The server renders only it;
  `chip-multiselect.js` builds the chips from its `<option>`s and moving an entry does nothing
  but set `option.selected`. No hidden inputs, no state to synchronise on submit — and a
  `<select multiple name="read_groups">` posts exactly what same-named checkboxes post.
  Whoever reads the selection reads `option:checked` and listens for the `change` event the
  widget dispatches (see `berechtigungen.js`).
- **Progressive enhancement is load-bearing, and CSS must not break it.** The JS hides the
  native field via the `hidden` attribute, so `.chip-ms-native` must never get a `display` rule
  and `.chip-ms-ui` hangs its `display` on `:not([hidden])`. Without JS a fully usable native
  multi-select remains.
- **Drag is limited to `(pointer: fine)`** — on touch SortableJS would fight both page
  scrolling and the long-press for the same gesture. The popover is `position: fixed` and
  positioned from raw `getBoundingClientRect()` values (unlike `.att-move-picker`, which uses
  scroll offsets): the offcanvas panels are `fixed` and scroll internally, so a scroll-offset
  popover would drift. It is appended to `document.body` because `.offcanvas` establishes a
  containing block via `transform`.
- **The JS is loaded globally in `base.html`, deliberately not via `class Media`** — the
  permission pages have no form at all, and two `.media` calls on one page (`table.html`
  renders both a filter and an add form) would execute the IIFE twice. It bails out in its
  first line when the page has no `[data-chip-multiselect]`.

## Delete confirmation

**One `<dialog id="delete-dialog">`**, `_confirm_delete_dialog.html`, for `ort_edit.html`,
`termin_edit.html` and `titel_edit.html`: `{% include "_confirm_delete_dialog.html" with
titel="Ort löschen" objekt=ort.name action=loeschen_url %}` (resolve the URL with `{% url … as
loeschen_url %}` first). `warnungen` takes a list of extra lines naming what a delete would
take with it — `termin_edit` passes `loesch_warnungen`, built in the view so the pluralisation
stays in Python. The opening button stays in each page's `.form-actions`, because it is guarded
differently per page (`titel_edit` renders it disabled with a tooltip when the song is still
referenced, and then omits the dialog entirely).

The folder browser has its own flow — it asks the server what a delete or rename would break
first; see `files.md`.

## Attendance (Zusage) and the next-event banner

`Zusage.option` values: `"1"` = Zusage, `"2"` = Absage, `"3"` = Eventuell, empty/missing =
Keine Angabe. The attendance table on the termin detail page groups users by `Stimme`
(S, A, T, B, C, M) and splits into two tables on mobile.

A slim banner is shown site-wide at the top of `<main class="content">` in `base.html`
(`_termin_banner.html`), highlighting the next upcoming event (`banner_termin` /
`banner_my_option`, computed in `config/context_processors.py`'s `project_meta`) with a
`timeuntil` countdown, location and — when `anwesenheit=True` — the same quick Zusage buttons
(governed by `ZUSAGE_TRANSITIONS`). The buttons POST to `termin_zusage` with a hidden
`source=banner` field, which makes that view render `_termin_banner.html` instead of the detail
widget (htmx swaps `#termin-banner`).

The banner is rendered with the `hidden` attribute and only revealed by a small inline script
at the end of `_termin_banner.html` — the dismissed state lives in `localStorage` and is
therefore not known server-side, so deciding before paint avoids a flash of a banner that is
immediately removed. That script removes the banner on that termin's own detail page (avoids a
duplicate widget) and when it was dismissed for the current login session: both the dismiss
button and following the banner link store the session key `banner_login` (exposed as
`data-login`) in `localStorage["termin-banner-dismissed"]`, so the banner reappears after the
next login when that value changes. `banner_login` is `"<pk>-<last_login timestamp>"` and is
computed in `project_meta` from `request.user` on purpose — reading `user.last_login` in the
template would break on detail views such as `mitglied_view`/`mitglied_edit`, which shadow
`user` with the member being looked at. The script sits *inside* `#termin-banner` so an htmx
`outerHTML` swap replaces it along with the markup; `intern.js` (`initTerminBanner`) keeps the
dismiss click handler and the same logic as a fallback. On mobile (≤640px) the dismiss button
is absolutely positioned in the banner's top right corner.

## Calendar (month view)

`/intern/kalender/` (`termin_kalender` in `views/termine.py`, sidebar entry right after
"Termine") is a classic month grid (7 columns Mon–Sun) — not an agenda. Month is chosen via
`?jahr=&monat=` (defaults to the current month; invalid values fall back to it). The grid is
built with `calendar.Calendar(firstweekday=0).monthdatescalendar()`; the leading/trailing days
of neighbouring months are shown dimmed (`.is-outside`).

Events are loaded once with an **overlap** query (`datum__date <= grid_end AND (datum_bis >=
grid_start OR single-day in range)`) so multi-day events (`datum_bis`) that start before or end
after the grid are caught; each is expanded to one occurrence per covered day (a dict `{t,
mehrtaegig, start, ende}`), rendered as a connected band (`.is-span` chips bleed into the cell
padding, clipped by `.cal-day{overflow:hidden}`; only the start/end day is rounded,
continuation days show a `‹` marker) that wraps correctly across week and month boundaries.
Birthdays are active members with a set `geburtstag` **whose field is not hidden**
(`"geburtstag" not in user.private_fields`, no viewer/admin bonus — same for everyone) mapped
by `(month, day)`. Each event chip links to `termin_view`, each birthday chip to
`mitglied_view`. Group by `t.datum.date()` directly — `USE_TZ = False`.

Prev/next/"Heute" navigate via htmx: the toolbar + grid live in the partial
`_kalender_grid.html` (wrapped in `#cal-view` by `kalender.html`); an `HX-Request` renders only
the partial (swapped into `#cal-view`, `hx-push-url` keeps the URL in sync). Clicking any day
with entries opens a large offcanvas detail panel (`#cal-day-panel`, sibling of `#cal-view` so
it survives swaps): `kalender.js` clones that day's `.cal-day-detail` into the panel and shows
its German date label (`d.label` → `data-datum`); Esc/overlay/close button dismiss it.

**The panel also creates events.** Holders of `intern.add_termin` get the same `TerminForm` the
`/intern/termin/` add panel uses, rendered once into `#cal-day-panel` (below `.cal-panel-body`,
both inside the shared scroll box `.cal-panel-scroll`) — it lives outside `#cal-view` and thus
survives the htmx month swap, which is why `kalender.js` fills it per day instead of the
server: `form.reset()`, `datum` = the day's `data-iso`, and `next` = `location.pathname +
search`, i.e. the month currently shown. It sits collapsed behind a „Neuer Termin" button and
opens by itself on a day with no entries, where creating is the only thing left to do. For
those users **every** day opens the panel, empty ones included (`.cal-can-add` on `.cal-page`
supplies the cursor); without the permission the view renders no form and only days with
entries open.

`termin_add` honours that `next` (POST or GET) and redirects there instead of to `termin_view`,
guarded by `url_has_allowed_host_and_scheme` so it can't be turned into an open redirect;
`termin_edit.html` re-emits it as a hidden field so an invalid form keeps the way back. The
toggle relies on the `hidden` attribute, so `.cal-add-open[hidden]` must state `display: none`
explicitly — `.btn` sets `display` and would otherwise win over the UA default.

On desktop the cells show the chips inline; below 768px they collapse to coloured dots
(`--brand` = event, `--cal-geb` = birthday) and the panel is the readable view. The whole month
grid fills the viewport height — `.content:has(.cal-page)` becomes a flex column so the grid
(with `grid-auto-rows: 1fr`) shares the space with the next-event banner without a scrollbar.
CSS lives under `/* === Kalender === */` in `intern.css`; birthdays use the `--cal-geb` /
`--cal-geb-bg` tokens (green, distinct from the pink event colour) and weekend day
numbers/headers use `--cal-weekend` (red) — all with dark-mode values.

## Design tokens and colours

All colours use CSS custom properties defined in `:root` (light mode). Dark mode is a
`[data-theme="dark"]` block that overrides all colour tokens. When adding new colours, always
use CSS variables and add dark-mode values; avoid hardcoded hex values in component styles.

**Status ("Ampel") colours** — the green/yellow/red used by the attendance badges
(`.att-count-*`, `.att-inline-*`) and the Zusage widgets (`.zusage-state-*`, `.zusage-btn-*`)
come from one token family:
`--status-{success,warning,danger}-{bg,text,border,solid}`. `bg`/`text`/`border` are the soft
surface, `solid` the strong fill used on hover/active; the dark-mode block redefines the first
three, so those components need **no** `[data-theme="dark"]` rules of their own — only the
neutral "keine Angabe" state does. Destructive buttons use `--error-solid` /
`--error-solid-hover`; do **not** reach for `--error-bg` there, that is a pale surface colour
and carries no white text.

## Explanation tooltips

A small info icon whose bubble explains what an option means and what it does. Two rules make
it work:

- **The text lives as `help_text` on the model field, never in a template.** The form inherits
  it for free, and display-only pages read the same string. `Termin.repertoire` and
  `Termin.anwesenheit` are the current users — both options have effects a member cannot guess
  from the word alone, and `repertoire` even publishes to the homepage and mails the external
  gig list.
- **One component, two entry points.** `{% hilfe form.repertoire %}` takes a `BoundField`
  inside a form; `{% hilfe "Termin.repertoire" %}` takes a `"Model.field"` string on a display
  page (`intern/templatetags/ui_tags.py` → `_hilfe_icon.html`). A wrong field name raises
  rather than rendering an empty icon.

`tooltip.js` keeps a single `.hilfe-bubble` on the body and hangs **delegated** handlers off
`document` for `[data-hilfe]` — the calendar day panel is filled by `kalender.js`, the termin
banner is swapped by htmx and table rows arrive by infinite scroll, so an init-time
`querySelectorAll` would miss them all. It shows on hover (200 ms), on `:focus-visible`
(keyboard only — a mouse click would otherwise open and immediately re-close it) and on tap,
which is the only way touch devices reach it at all; that is why the plain `title` attribute
used elsewhere was not enough here. The bubble is `position: fixed` because `.table-container`
and `.cal-panel-scroll` scroll internally and would clip an absolutely positioned one.

Two traps when placing the icon: it must stay **outside** a checkbox `<label>` (inside, a click
on it toggles the checkbox), and where the surrounding template also renders `help_text` as
`<small>` (`table.html`'s generic add panel) that branch must be limited to non-checkbox
fields, or the same sentence appears twice. The attribute is `data-hilfe`, not `data-tooltip`,
because `gruppen.html` still carries its own page-local tooltip on the latter — moving it onto
this component is an open cleanup (its bubble also references `--border-strong`, a token only
defined on `.perm-matrix-wrap`, so it renders without a border).

## Theme boot

The inline `<script>` that sets `data-theme` before paint lives in exactly one place:
`intern/templates/_theme_boot.html`. Every standalone page includes it right after its
`intern.css` link and before any visible markup — `base.html`, `dialog.html`,
`mitglied_public_base.html`, `datenschutz.html` and the five error pages. Put it anywhere later
and the flash of the wrong theme comes back. The script only **reads** `localStorage["theme"]`,
falling back to `prefers-color-scheme`; it never writes.

Writing is the toggle's job alone (`initTheme` in `intern.js`, `apply(theme, persist)`): the
initial call passes `persist = false`, only a click persists. That distinction matters —
persisting on load would freeze whatever the system happened to prefer on the first visit, and
a later OS switch would have no effect. While nothing is stored, a `prefers-color-scheme`
change listener follows the system live.

**Auth pages** (`dialog.html` → `login.html`, `register.html`, `register_success.html`,
`reset_confirm.html`) are themed like everything else: they load `intern.css`, carry
`class="join-page"` on `<html>`/`<body>` and reuse the `.join-wrap`/`.join-card`/`.join-header`
shell of the public join pages. `login-style.css` loads *after* it and holds only what
`intern.css` does not cover (narrower card, the `<h1>` that sits outside `.join-header`,
full-width submit button, `helptext` sizing for `{{ form.as_div }}`) — tokens only, no hex
values. Form fields, labels, buttons, error boxes (`.error`, `ul.errorlist`) and the
password-strength meter all come from `intern.css`.

## Maps

Map pages use Leaflet, and everything they share lives in
`intern/static/intern/js/osm-map.js`, loaded once in `base.html` right after Leaflet:

- It patches `L.TileLayer.prototype.createTile` to set `referrerPolicy = "origin"` —
  OpenStreetMap's tile servers reject requests without a `Referer` header. Per-page map code
  must not re-add this patch.
- `window.CantorMap` holds the pieces every map needs: `tiles(map, opts)` (the `/tiles/…` layer
  plus attribution — never call `L.tileLayer` directly, or a server change misses one map),
  `pin("ort"|"mitglied")` (the `.karte-pin` divIcons, colour and SVG defined once), `esc(s)`,
  and `init(el)`/`initAll()`.
- **Detail-page maps are declarative.** `{% include "_leaflet_map.html" with lat=… lng=…
  popup=… %}` renders only a `[data-osm-map]` container; `initAll()` builds the map from its
  data attributes on load. Parameters: `lat`, `lng`, `zoom` (default 15), `popup` (first line),
  `popup_ort` (an `Ort` whose address is appended as further lines), `pin`, `map_id`, `hoehe`.
  Popup text travels as plain text with `&#10;` line breaks and is escaped in JS — no
  `escapejs` in a template, no HTML from the DB. Used by `ort_detail.html`, `termin.html` and
  `mitglied.html`.
- `karte.html` keeps its own init (layer groups, live locations, search) but takes the tile
  layer and both pin icons from `CantorMap`.

## Infinite scroll

List views load further rows through `views/_pagination.py`: `parse_offset(request)` reads
`?offset=` (never negative, never raises, capped at `_MAX_OFFSET`), `ist_nachladen(request)`
recognises the `X-Requested-With` fetch, and `nachlade_antwort(template, context, has_more,
next_offset, request=None, **extra)` renders the row fragment and returns the JSON the sentinel
script expects (`html`, `has_more`, `next_offset`, plus any `extra`). Pass `request` only when
the fragment really needs the context processors — otherwise they (and their termin-banner
queries) run on every scroll. `paginate_ordered()` applies `?sort=` before slicing.

## Public homepage

`templates/index.html` + `intern/static/intern/css/main.css`. The public landing page does
**not** extend `base.html` and does **not** use `intern.css` — it is a standalone one-pager
with its own stylesheet (light mode only, own token block in `:root`). Structure: fixed header
over a full-bleed photo hero (transparent at the top, `.is-solid` white after 60 px of scroll —
set by a small inline script at the end of the page), then Über uns (cards), Konzerte
(date/title/place rows), Galerie (single wide photo band) and a dark Kontakt section plus
footer.

It is the one page that stays **light only** on purpose, and therefore the one page that does
*not* include `_theme_boot.html`: the photo hero, the white `.is-solid` header state and the
already-dark Kontakt section are a composed look, not a token swap. Do not bolt a
`[data-theme="dark"]` block onto `main.css` without redesigning those three.

Logo usage: the header shows the round mark (`intern/images/JG-Frankfurt-wG-color.svg`) over
the photo and swaps to the black wordmark (`intern/brand/JG-Frankfurt.svg`) once the header
turns white — below 460 px the mark stays. Hero headline and footer use the light wordmark
(`intern/brand/JG-Frankfurt-transparent.svg`) as an image inside the `<h1>`; its font (Showcard
Gothic) exists only as outlines in the SVG, so the lettering can only be used as an asset,
never as a webfont. The favicon redirect in `config/urls.py` relies on the tracked source copy
of `JG-Frankfurt-wG-color.svg` in `intern/static/intern/images/`.

All copy comes from `Konfiguration` (`HOMEPAGE_UEBER_UNS`, `HOMEPAGE_AUFNAHME`, `VEREINSNAME*`,
`VEREINSADRESSE`, `DEFAULT_FROM_EMAIL`) — `home()` in `views/auth.py` additionally passes
`homepage_intro`, the first sentence of `HOMEPAGE_UEBER_UNS`, used as the hero subline. The
hero and gallery images are pre-scaled derivatives of the choir photo in
`intern/static/intern/img/` (`chor-{800,1400,2000}.jpg` for the hero `srcset`,
`chor-band-{1100,1800}.jpg` for the gallery band); regenerate them from the original with
ImageMagick when the photo changes. Assets are referenced via `{% static %}`, so
`collectstatic` covers them.

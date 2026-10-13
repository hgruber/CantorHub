# Frontend: pages, components, design system

No framework. Vanilla JS per concern in `intern/static/intern/js/`, htmx for the few partial
swaps, one stylesheet (`intern/static/intern/css/intern.css`) built entirely on CSS custom
properties. The public homepage is the one page outside all of this — see the last section.

## Detail pages

All list views use django-tables2 with clickable rows (`data-href` on `<tr>`). Each table row
navigates to a detail page. Detail pages have an edit button in the top bar (via `edit`/`id`
context variables rendered in `base.html`).

Every table is zebra-striped (`--bg-row-alt` on even `tbody` rows) except those that colour
their rows themselves: the member list (voice colours), wiki tables (own stripes), the
permission matrix and the article diff. They are listed in the `:not()` of the stripe rule in
`intern.css`; a new table with its own row colouring belongs there too. The rule is wrapped in
`:where()` so hover, drag-over and the live-refresh flash still win over it.

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

## Select fields

`SchnellSelect` (`intern/forms.py`) is the `<select>` the filter bars use, and
`SchnellSelectMultiple` its multi-value sibling; `TriStateToggle` builds on it. Django renders
**one template per `<option>`** (`django/forms/widgets/select_option.html`), and the „Konzert"
filter offers every event — 215 entries in the member list, 105 in the repertoire — which put
about 17 ms of each list page into the filter bar alone. The widget writes the same markup with
`format_html`, so escaping stays Django's.

`SchnellSelectTest` compares its output against `forms.Select` character for character (empty,
selected, optgroups, special characters, disabled). Should a future Django change the markup,
that test fails rather than the portal silently drifting.

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

## Color field: text + native picker

One component for every hex-color input: a text field (source of truth, allows empty/free-form
values) plus a native `<input type="color">` next to it, which doubles as both the picker *and*
a live swatch — every modern browser already renders it filled with the current color, so no
separate `<span>` swatch element exists.

- **`intern/templates/_color_picker.html`** is the only markup, with two entry points. Forms use
  the `ColorPickerInput` widget (`intern/forms.py`, built like `ChipMultiSelect`), which sets the
  partial as `template_name`. Pages without a Django form — the configuration page — `{% include
  %}` the same partial directly. Options: `extra_class` (adds a caller-defined class to the
  *text* input only — e.g. `kf-value-input` so `konfiguration.js`'s single `.kf-value-input`
  `querySelector` keeps finding exactly one element), `placeholder`, `pflicht`.
- **The text field stays the single source of truth.** `color-picker.js` only keeps the two
  fields in sync: typing a valid `#rrggbb` in the text field updates the picker; picking a color
  updates the text field and dispatches an `input` event on it (so change-tracking code that
  listens for `input`, e.g. `konfiguration.js`, sees it). An invalid or empty text value leaves
  the picker untouched rather than erroring — `<input type="color">` cannot represent "empty" at
  all, which is exactly why it is never the sole widget.
- **The JS is loaded globally in `base.html`**, like `chip-multiselect.js` — it bails out
  immediately if the page has no `[data-color-picker]`.

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

**The event list shows the answers as a stage picture** (column „Aufstellung", `_aufstellung.html`),
modelled on the legacy portal: one square per active member, back row Tenor | Bass, front row
Sopran | Alt, Chorleiter and Musiker set apart top right. Within a voice the Zusagen face the
aisle — the left voice runs Absage → Offen → Eventuell → Zusage from the outside in, the right
one mirrored — so a green block forms in the middle. The two-column grid is sized by the longer
voice of each side, which keeps the aisle aligned in both rows. There are no count chips — the
picture alone carries the numbers, and the totals only feed its `aria-label`, computed from the
very same placed members; members with Stimme `N` are neither drawn nor counted. The layout logic is
the pure `intern/aufstellung.py`; `_aufstellungen_anhaengen()` in `views/termine.py` is the DB
half and needs two queries per page, for the first load and the infinite-scroll reloads alike.
The viewer's own square carries a `--brand` outline, every square a name tooltip.

**A missing answer blinks.** Has the viewer not answered an upcoming event, or only with
„Eventuell", the `--brand` outline of their own square pulses (`offen-puls`, `1.6 s`, `intern.css`) *and* the event's own
name in the list carries the same pulsing outline (`render_kurz` → `span.termin-offen`). Only
the name is framed, not the row: the marker belongs to the event, not to its date and
aufstellung cells. The span has no padding — it would push the name out of line with the
unmarked events; the outline sits outside the text via `outline-offset` instead. Both elements share **one** animation, which is what keeps them in step —
same duration, same easing, same start, and both are rendered in the same fragment (a reloaded
page or an htmx batch brings square and name together). The class comes from the
`meine_antwort_fehlt` annotation, which `termin_list` sets **only for upcoming events** — an
open answer to a past event is meaningless — and `render_kurz` gates it on `record.anwesenheit`
because events without an attendance poll have no aufstellung at all. The rest of the phase
stays visible (the outline fades out and in rather than switching between two states), so the
square remains recognisable as one's own; `prefers-reduced-motion: reduce` stops the animation
and leaves both outlines standing.

**Two narrow columns between date and name mark a public gig.** `TerminTabelle.render_auftritt`
fills the first one with a microphone when `Termin.extern` is non-empty; `render_lieder` fills the
second with a `.badge` pill carrying the number of Ablauf entries when `repertoire` is set and
entries exist. They are two columns rather than one so that icon and pill line up down the list.
The microphone's criterion is the
**raw** field — the very one `home()` lists by (`OHNE_ANKUENDIGUNG` in `intern/models.py`) — and not
the display filter `extern_html`, which drops pure whitespace; a lone space therefore marks the
event, exactly as it lists it on the homepage. The count arrives as a `Count("konzert")` annotation
from `termin_list`, one query for the whole page, and is deliberately **not** filtered on `lied`
so that it equals the pill on the termin page's card „Lieder". The calendar chip carries the same
microphone (`cal-chip-icon`, so the offcanvas day list inherits it — it copies the cell's
`innerHTML`), but only on the first day of a multi-day event; the chip's `is-konzert` colour still
follows `repertoire` alone and is independent of the microphone.

The termin detail page repeats it larger as the wide card „Aufstellung" right above
„Anwesenheit" (`_termin_aufstellung_karte.html`, `gross=True` → `.aufst-gross`, which only
overrides the `--aufst-*` size variables). The card has to follow every change of the answers:
`termin_zusage` and `termin_anwesenheit_update` attach the aufstellung too, and
`_termin_zusage.html` sends the card with `hx-swap-oob` next to `#attendance-section`. The admin
drag-and-drop editor does not go through htmx, so `anwesenheit.js` swaps `#aufstellung-section`
from the same response by hand.

A slim banner is shown site-wide in `base.html` (`_termin_banner.html`), directly below the
top bar and — deliberately — *next to* `<main class="content">`, not inside it: `.content` is the
scroll container, and a page that fills it (`.table-view`, `.forum-layout`, `.article-editor`,
`.history-view`, `.diff-view` all carry `height: 100%`) would overflow it by exactly the banner's
height, giving the page a second scrollbar beside the scrolling table body. Sitting outside also
keeps it clear of the full-bleed map (`.karte-wrap` is `position: absolute; inset: 0` in
`.content`), which used to cover it. It highlights the next upcoming event (`banner_termin` /
`banner_my_option`, computed in `config/context_processors.py`'s `project_meta`) with a
countdown, location and — when `anwesenheit=True` — the same quick Zusage buttons
(governed by `ZUSAGE_TRANSITIONS`). The buttons POST to `termin_zusage` with a hidden
`source=banner` field, which makes that view render `_termin_banner.html` instead of the detail
widget (htmx swaps `#termin-banner`).

**All-day events are counted in calendar days, not hours.** An event entered without a time
sits at `00:00` (see `intern/forms.py`), so Django's `timeuntil` would both measure against
midnight — „3 Tage, 14 Stunden" where „4 Tage" is meant — and treat the event as past from
00:01 of its own day. The rules live in `intern/terminzeit.py`, pure and clock-free so they are
testable as `SimpleTestCase`:

- `countdown_text()` yields „heute" / „morgen" / „N Tage" for all-day events and falls back to
  `timeuntil` for events that carry a time, where hours are the useful answer. It keeps the
  non-breaking space `timeuntil` uses between number and unit.
- `kommende_q()` is the single definition of „upcoming" and feeds both `banner_termin` and the
  `offen_termine` badge — including the `answered` subquery, which would otherwise use a
  narrower definition and count an already-answered event as open forever. Besides the real
  future it admits today's all-day event (`datum` equals midnight of today) and an all-day
  event still running, up to and including `datum_bis` — the same reading as the month grid.
  Events *with* a time are unaffected and still leave the banner when they start.

The countdown is a template filter (`intern/templatetags/termin_tags.py`), not a value
precomputed in the context processor: `termin_zusage` re-renders the banner with its own
`banner_termin`, where a precomputed variable would still describe the event the context
processor picked. `zeitraum_bis` in the same module gives the date line the full span of a
multi-day all-day event, so „heute" is not paired with a start date in the past.

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
dismiss click handler and the same logic as a fallback.

Narrow screens only break the banner into rows where it has to: the three answer buttons get a
row of their own below ≤640px (`:has(.zusage-actions)`), and only then is the dismiss button
absolutely positioned in the top right corner. The answered state is a single „Zugesagt" pill
and stays on the first row; below ≤480px it drops its label (`.zusage-state-text`) and shows
the check alone, with the wording kept in `title`/`aria-label`. A second row for one pill would
make the banner tower over the page it only annotates.

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
`intern/static/intern/css/main.css`, the public homepage, is the one stylesheet outside this
rule — it has a single theme and its own token block; see „Public homepage" below.

The accent colour is the one exception worth calling out explicitly: never hardcode `#c14468`
or `rgba(193, 68, 104, …)` in component styles — always reference `var(--brand)`, one of its
derived tokens (`--brand-dark`, `--brand-light`, `--brand-ring`, `--brand-text`), or a fresh
`color-mix(in srgb, var(--brand) X%, transparent|white|black)` expression, so a `BRAND_FARBE`
override (see `_brand_boot.html`) reaches every surface that uses it.

`--brand-dark` and `--brand-text` are the same tone in the light theme and **differ in the dark
one** — the accent as a *surface* (a button fill carrying white text) and the accent as *text on a
card* pull in opposite directions: lightening the surface costs its white label, darkening the
letter loses it on the dark card. This is the same split the voice palette makes with
`--stimme-X` and `--stimme-X-text`. Use `--brand-text` for every brand-coloured letter on a
surface (`--brand-dark` there was 2.7:1 on `--bg-card`); `--brand-dark` stays for fills and for
lines, which may be quiet.

**Status ("Ampel") colours** — the green/yellow/red used by the attendance badges
(`.att-count`, `.aufst-{yes,maybe,no}`) and the Zusage widgets (`.zusage-state-*`, `.zusage-btn-*`)
come from one token family:
`--status-{success,warning,danger}-{bg,text,border,solid}`. `bg`/`text`/`border` are the soft
surface, `solid` the strong fill used on hover/active; the dark-mode block redefines the first
three, so those components need **no** `[data-theme="dark"]` rules of their own — only the
neutral "keine Angabe" state does. Destructive buttons use `--error-solid` /
`--error-solid-hover`; do **not** reach for `--error-bg` there, that is a pale surface colour
and carries no white text.

**Categorical palette** — the permission categories
(Artikel/Forum/Dateien/Orte/Termine/Repertoire/Mitglieder) use `--kat-1..6`, with the
dark-mode block redefining all six. The category „Termine" is the accent colour
(`var(--brand)`, not a `--kat-*`), so a `BRAND_FARBE` override reaches it too. Tints are
written inline as `color-mix(in srgb, var(--kat-N) X%, transparent)`; the permission column
tints (`.perm-col-cat-*`) keep their light/dark opacity difference (5 % light vs 8 % dark)
via explicit `[data-theme="dark"]` rules, while the `.perm-cat-*` colour bar needs none,
because it uses the full-tone token that the dark block already overrides.

**Voice palette** — `--stimme-{s,a,t,b}`, a family of its own. The voices used to share
`--kat-*`, which cost them both ways: three of the six tones sat inside a 40° arc of the hue
circle, so at the 7 % row-tint opacity Tenor and Musiker were 3.7 sRGB units apart — nothing —
and the shared tokens meant the voices could not be retuned without moving the permission
matrix with them. The replacement is built in OKLCH for two properties at once: even hue
spacing (smallest pair distance 100) **and** a lightness ladder falling monotonically from
Sopran to Bass (0.282 > 0.201 > 0.171 > 0.090), so the pitch order survives red-green
colour blindness, greyscale printing and a bad projector. Alt is deliberately *not* on
`var(--brand)` any more: against a full-tone bar a choir setting `BRAND_FARBE` to teal would
render Alt and Tenor identical. Chorleiter and Musiker are roles, not voice types, and get
the neutral `--t4` rather than a hue of their own — which also keeps the hue circle from
crowding again.

Each tone comes with a derived `--stimme-X-text` (`color-mix(… 80%, black)` in light, the
tone itself in dark, following `--brand-dark`), because a Sopran bright enough for the
lightness ladder is too bright to be text on white. All four text variants clear 4.5:1 in
both themes.

**The voices are carried by a bar, not a surface.** In the member list the row stays neutral
— `.mitglied-table` is back in the zebra striping — and `.row-stimme-*` sets a local
`--stimme-farbe` that `td:first-child` paints as `box-shadow: inset 4px 0 0`. A box-shadow
draws over the cell background, so zebra, hover and the row-fresh animation need no special
rules, and `.row-inactive` keeps winning for free because it simply never sets the variable.
When the list is sorted by voice, `tabelle.js` merges equal voices into the vertical
`.stimme-merged-cell`, which tints itself at 16 % of the same variable. The narrow permission
column in `aufgaben.html` keeps a surface tint (`.perm-stimme-*`): it is vertical and narrow,
where a bar would have nothing to delimit. Both palettes are domain-fixed
(soprano/alto/tenor/bass are not a per-choir setting) and not exposed in `Konfiguration`.

**The voice follows the member to their page.** The setter rows are the single place that maps a
voice to a tone, so they carry a second selector (`.row-stimme-s, .stimme-s`, and so on) rather
than a second table: one setter, four consumers — the list bar, the member page's edge, the
portrait ring and the topbar pill. That page is *not* a card: it follows the `.detail-page` /
`.detail-cards` pattern of its thirteen siblings, and its accent is the list bar one level up —
`.detail-page.member-voice` carries `border-left: 4px solid var(--stimme-farbe)`, damped to 55 %
in the dark theme, with the portrait wearing a 3 px ring in the full tone inside `.detail-icon`
(the one place with no text on it). No surface takes the tone: a full-tone *surface* fails
contrast (white on Sopran 3.2:1, on Alt 4.2:1; black on Tenor 4.4:1, on Bass 2.8:1), and tinting
sections would turn the accent into decoration.

The card went because of its *shape*, not its colour: a card claims four visible corners, and this
page is longer than the scroll area, so its top and bottom edge were never on screen at once — the
white block with its corners scrolled away read as broken, and its `margin: 20px auto` lived
*inside* the scroll area, so the gap above it vanished after one wheel turn. The page edge has
neither problem: it belongs to the container, so it scrolls with the content and never
re-establishes a gap. `padding-left: 20px` plus the 4 px edge keeps the first card on exactly the
same x as `mitglied_edit.html`'s. Its fallback is `transparent`, not `--border`: a 4 px grey page
margin would be a design element without a statement, and „no tone, no marker" is the rule the row
and the pill already follow. The grid is what makes the page short — halving the stack took it from
1256 px to 909 px (the map's own card uses the 250 px `min-height` of `.detail-map` instead of a
handed-down 400 px), but a grid row also stretches to its tallest member, so the two song lists are
`detail-card-wide`: 92 songs in half a column had doubled the height *and* stretched Personalien
into an 825 px box holding four rows.

The `(S)` that used to ride along inside `seitentitel` is now a `.stimme-pille` in the topbar's
`topbar_after` slot, beside the title instead of inside it — `.top-bar .title` has
`text-overflow: ellipsis`, so a long name used to eat exactly that letter. It wears the tone as
its surface and `--bg-card` as the letter, the reverse of what a pill would use on a coloured
bar: the topbar is `--bg-card` in both themes (`--tb-bg`), where a card-coloured pill would be
invisible. Contrast is direction-independent, so the documented 4.5:1 pair holds either way
(light 4.7–9.8:1, dark 7.4–10.2:1). The letter is template text rather than generated content,
so a stray legacy code (`"X"`) still prints one and screen readers keep it. Roles take `--t3`
where their text in the list takes `--t4` (2.2:1 on the tint of the merged strip): a line may be
quiet, a letter may not. `stimme = "N"` gets no pill at all — no tone, no marker — matching
`tables.py`, which gives such rows no class and is why there is no `.stimme-n`.

## Explanation tooltips

A small info icon whose bubble explains what an option means and what it does. Two rules make
it work:

- **The text lives as `help_text` on the model field, never in a template.** The form inherits
  it for free, and display-only pages read the same string. `Termin.repertoire`,
  `Termin.anwesenheit` and `Termin.extern` are the current users — each has effects a member cannot
  guess from the word alone: `repertoire` brings the card „Lieder", `anwesenheit` the Zusage
  buttons, and `extern` decides the entry on the public homepage *and* the gig-reminder mails
  (see „Public homepage"). `extern` is also the one field whose content is rendered as HTML —
  `extern_html` in `intern/templatetags/termin_tags.py` turns its line breaks into `<br>`, strips
  `style` attributes and rewrites `<h1>`–`<h3>` to `<strong>`, and is explicitly not a sanitizer
  („Trust boundary" in `docs/technical-debt.md`).
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

The same script applies the **font size**. Ctrl+mouse wheel has no counterpart on phones: the
app shell (`html, body { height: 100%; overflow: hidden }`) turns pinch-zoom into panning
without reflow, and the installed PWA (`display: standalone`) has no browser zoom menu. So
Einstellungen → Schrift in the sidebar offers 90 · 100 · 115 · 130 · 150 %
(`initSchriftgroesse` in `intern.js`). The factor is stored per device as
`localStorage["schriftgroesse"]` — the key is removed at 100 % — and set as `--schrift-faktor`
on `<html>`, where `intern.css` computes `font-size: calc(14px * var(--schrift-faktor, 1))`.

This only works because every font size hangs off that root: sizes are written as
`calc(Nrem / 14)` (identical to `Npx` at 100 %), never in `px`, in the stylesheets and in
template `<style>` blocks alike; mail templates are exempt. Only text scales — paddings and
icons stay in `px`. `--sb-width` and the submenu height grow along
(`min(calc(232rem / 14), 85vw)`). A fixed `px` width next to text that must fit, such as the
rotated column heads of the permission matrices, needs `rem` as well. Check new layouts at
150 % on a 390 px viewport.

Rejected alternative: CSS `zoom` on `<html>` would scale `100dvh` past the screen edge and put
Leaflet, SortableJS and the fixed popovers out of step with pointer coordinates.

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
`intern/static/intern/js/osm-map.js`. Both are pulled in by
`{% include "_leaflet_assets.html" %}` inside the `extra_js` block of the four templates that
show a map (`karte.html`, `mitglied.html`, `ort_detail.html`, `termin.html`) — **not** by
`base.html`: 147 KB of JavaScript plus a render-blocking stylesheet on every page, for four
pages. A new page with a map has to include that partial, otherwise `L` is undefined.

Leaflet, Dropzone and SortableJS are served from `intern/static/intern/vendor/` at a fixed
version rather than from unpkg/jsdelivr/cdnjs. The two CDN stylesheets used to block the first
paint of every page behind a foreign connection, `dropzone@5` and `sortablejs@latest` were
redirects with a short cache lifetime, and every visit handed a member's IP to a third party —
which the privacy policy now rules out in „Sichtbarkeit Deiner Daten im Portal". Under
`/static/` nginx serves them with a one-year `immutable` cache. To upgrade one, drop in the new
file; nothing else changes.

What `osm-map.js` does:

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

## Audio player: one engine, several displays

`initMiniPlayer` in `intern.js` owns **the** playback — one `HTMLMediaElement` at a time, in the
closure variables `audio`, `queue`, `queueIndex`, `aktuellerItem`. Everything else is a display:

- the floating `#mini-player` from `base.html`, present on every page;
- the `.wiki-player` video bars a wiki article embeds in its text (`docs/articles.md`). Audio
  in an article has no bar: its `.wiki-audio` figure only starts the queue, and the mini-player
  is its display.

The bars deliberately reuse the mini-player's `.mp-*` classes, which are defined **without** a
`.mini-player` ancestor — only the positioning lives on `.mini-player` itself. Keep it that way.

`leistenRendern()` walks `document.querySelectorAll(".wiki-player")` afresh on every render
rather than keeping a registry. That is what makes the bars survive htmx swaps without a hook,
and it means no state ever points at a removed node. Playing, progress, times and the enabled
state of prev/next all come from that one function; it is called from `loadTrack`, `stop` and the
`timeupdate` / `play` / `pause` handlers, so every path through the engine ends up there.

Video plays **in** the engine: `loadTrack` looks for the `<video>` of a matching bar
(`medienElement()`) and adopts it instead of building `new Audio()` — same API, so nothing below
changes, and video stays part of the same queue. While such an adopted `<video>` plays,
`loadTrack` hides the mini-player — the bar is already the controls, a second set would be
redundant; the next audio track in the queue opens it again. Because that element outlives the track, its
listeners are bound with an `AbortController` (`trackAbbruch`) and dropped on the next load;
`new Audio()` used to take its listeners with it.

Two exclusivity guards: `loadTrack` pauses the previous element, and a capture-phase `play`
listener on `document` silences the engine when anything else on the page starts — an
`<audio controls>` produced from an external URL in wikitext, say. `play` does not bubble, hence
capture.

Trigger paths are separate on purpose. `.audio-btn` (repertoire table, `titel.html`, the folder
context menu) plays a single track and clears the queue; the bars' own delegated listener and the
one on `.wiki-audio-start` call `artikelQueueStarten()`, which reads every bar and audio figure
in the `.wiki` container in document order and
starts `playQueue(items, false, index)` at the clicked one. Building the queue from the DOM
instead of a `json_script` mirrors exactly what the reader sees — old article versions included —
and spares the view a second pass over the wikitext.

## Uploads

Every page uploads through one Dropzone, `appMainDz` on `#app-main` (`intern.js`), fed two ways:
a file dropped anywhere on the page (the „Dateien ablegen" overlay) and the topbar icon
`#uploadBtn`, which opens a hidden `<input type="file" multiple>` and hands each chosen file to
`appMainDz.addFile()`. Phones have no drag and drop, so the icon is the only way there. Both paths
share the `sending` parameters, the progress card (`upload-progress.js`) and the reload on
`queuecomplete`.

The view decides target and visibility through its context: `upload_folder_id`,
`upload_folder_name` and the other `upload_*` keys read by `base.html`. **No dropzone may end up
filing at the root:** a page without a target (`upload_folder_id` and `upload_route_by_type`
both empty) gets no page dropzone at all — no overlay, no icon — unless the viewer holds
`intern.manage_folder_permissions` (`data-upload-wurzel`); then a drop lands at the root and the
upload card asks to move it. The folder browser follows `can_write_here`, at the root only with
that right. `upload_aus` switches the page dropzone off for everyone (the profile page, where
the avatar field is enough). `upload` in `views/files.py` enforces write access and the root
rule either way. **Icon and dropzone go together:** `base.html` renders `#uploadBtn` `hidden`
wherever an upload could happen, and the same `uploadGesperrt` rule in `intern.js` that
disables the dropzone decides whether it is shown — there is no second condition to keep in
step.

The field dropzones (`initFilerDropzones()`, which replace filer's widget for the avatar, the
forum picture and the song files) upload straight into their field's folder: the view passes
`feld_ordner = {field name: folder id}`, `base.html` prints it as `json_script` `#feld-ordner`.
They send `feld=1`, so the upload takes a free name („x (2).pdf“) instead of becoming a revision
of a file already there; „Speichern“ then renames it and merges via `systemablage()`. A field
dropzone is tappable and says so („Antippen oder Datei hierher ziehen“) — on a phone it is the
only way in; the picture fields (`avatar`, `bild`) accept `image/*`, which opens the gallery or
camera. Each upload is removed from Dropzone's count afterwards, so a second file replaces the
first instead of hitting `maxFiles: 1`.

## The list pages' script

`intern/static/intern/js/tabelle.js` carries what every list page needs: the infinite scroll,
„Neuer Ordner" in the folder browser, the merging of equal voices when sorting by `stimme`, and
the click that opens an image in the gallery. It used to sit in `table.html` as inline
`<script>` blocks — about 9 KB going over the wire with *every* list page; now it is fetched
once and served from `/static/` with the one-year cache. Each part checks for its own anchor
and returns when there is nothing to do, so loading it on a page without a table is harmless.

The two URLs that came from the template live on two empty elements, `#ordner-anlegen` and
`#galerie-link` (`data-url`), the same way `notify.js` reads its values off `<body>`. A new
part of the script needs its own anchor; do not put a `{% url %}` back into the JavaScript.

## Infinite scroll

List views load further rows through `views/_pagination.py`: `parse_offset(request)` reads
`?offset=` (never negative, never raises, capped at `_MAX_OFFSET`), `ist_nachladen(request)`
recognises the `X-Requested-With` fetch, and `nachlade_antwort(template, context, has_more,
next_offset, request=None, **extra)` renders the row fragment and returns the JSON the sentinel
script expects (`html`, `has_more`, `next_offset`, plus any `extra`). Pass `request` only when
the fragment really needs the context processors — otherwise they (and their termin-banner
queries) run on every scroll. `paginate_ordered()` applies `?sort=` before slicing.

The contract is not tied to tables: `/intern/changelog/` loads whole *release sections* through
it (`charge()` in `intern/auslieferungen.py`, two sections per batch), and `paginate_ordered()` is
simply not used there — the sections are a list, so the slice is a `liste[a:b]`.

## Release notes (Änderungen)

`/intern/changelog/` shows `CHANGELOG.md`, which travels inside the image. One card per release:
the version as the heading, the date as `d.m.Y` text — no month names, the house left those
behind in `replacements.format_datetime` — and below that the entries, **grouped by the kind of
change** (`### Hinzugefügt`, `### Geändert`, `### Behoben`, …) exactly as the file groups them.
The group heading is a small uppercase label; a group without a name — entries written before the
first `###` line, or a file without any — gets no heading, its list follows the card header
directly. A bullet may consist of several paragraphs: a blank line in the file separates the
paragraph, not the bullet.

The release that is running — `laufende_kennung(settings.VERSION, …)`, the **longest** section
token that the `git describe` string equals or starts with, so `v1.0.0-rc4-3-g7c8b717` finds
`v1.0.0-rc4` and not a `v1.0.0` — carries a 3 px `--brand` edge on the left and the badge
„Deine Version". Nothing else is marked: the list runs newest first, so everything above it is
newer by definition, and a second badge would only repeat the position. Without git (development,
`CantorHub v0.<n>`) there is no match, and therefore no marker rather than a wrong one.

The file is not Markdown in general: `intern/auslieferungen.py` decomposes exactly the constructs
it uses (`##` release headings, `###` change groups, `- ` items with hard-wrapped continuation
lines, inline `` `code` `` , `**bold**`, `*italic*`) and escapes first, then inserts its fixed
tags — the same order as `apply_replacements`. The change groups are three hashes, never two:
`## Added` would be read as a release heading, and the card would appear in the portal without a
date. `ChangelogTest` guards the same file for the `update` hook; `AuslieferungenDateiTest`
cross-checks the two decompositions and keeps every entry to three sentences, so neither the
duplicate patterns nor the writing rule can drift apart silently.

## The filter builder

The member list and the repertoire do not use a fixed field per criterion. Their filter is a
**chain of conditions**: any number of them, each with its own connector (`und`/`oder`) and its
own negation. That is what makes „in Gruppe A und in Gruppe B und nicht in Gruppe C" or „Hymne
und A cappella und nicht Aufnahme" expressible — a `ModelMultipleChoiceFilter` always ORs its
values and used to appear only once.

- **Machine and registries.** `intern/filterbau.py` is the machine and knows no field: the
  class `Baukasten` parses (`lese_bedingungen()`), builds the `Q` (`baue_q()`), applies both
  (`aus_daten()`) and prepares the topbar display (`kette()`), all without database access so a
  `SimpleTestCase` can pin them (like `verwendung.py` or `mitgliedschaft.py`). The fields live
  in two registries next to it, each a `Baukasten` instance: `MITGLIEDER` in
  `filterbau_mitglieder.py` and `TITEL` in `filterbau_titel.py`. The hooks where the pages
  differ are optional: `vorgabe` (the manager's access default), `alt_parameter` (the
  pre-builder parameters), `marker` (extra parameters when a condition goes away) and `traeger`
  (extra hidden form fields). Only names for foreign keys need the database; the view passes
  them in.
- **Evaluation: `und` binds tighter than `oder`**, as everywhere else. The chain is split at
  every `oder`, each segment is ANDed and the segments are ORed, so `A oder B und C` is
  `A oder (B und C)`. The topbar parenthesises a segment of more than one condition whenever
  there is more than one segment — the display must not lie. A single-segment chain stays free
  of parentheses.
- **Wire format: one repeated `f` parameter per condition**, `<connector>:<field>:<operator>:<values>`.
  One assembled value per condition rather than parallel lists: a multi-select emits one entry
  per value, which would knock a positional mapping out of alignment. **Every single value is
  percent-encoded** (`quote(w, safe="")`, the script's `encodeURIComponent`): comma and colon
  are the separators, and a typed name may contain both. Reading splits first and `unquote()`s
  each part, so the old unencoded values (`1,4`) stay valid.
  Without an `f`, `lese_bedingungen()` hands the query to the registry's `alt_parameter` hook,
  which translates the pre-builder parameters — `@tabellenzustand` keeps the query in a cookie
  for a year, and a view that no longer knows those names would show an **unfiltered** list that
  looks filtered. Members: `gruppen`, `gruppen_nicht`, `stimme`, `zugang`, `status`+`konzert`;
  the old third state `zugang=unknown` („Egal") suppresses the manager default just like the new
  `zugang=egal`. Repertoire: the names of the old **`FilterSet` attributes**, not the model
  fields — `titel` is the search, `sheet` is `pdf`, `notensatz` is `noten`, plus `tempo`,
  `tonart`, the eight `true`/`false`/`unknown` switches, `solist` and `dirigent`.
- **A registry is a `FELDER` dict**; a field is one entry — label, operators, `Q` builder, and
  `recht`. The member registry covers every column of the list (name, voice, e-mail, XMPP,
  birthday, last login, entry date, address and phone fields, fax, access) plus `gruppen` and
  `zusage` — a separate `termin` condition was dropped because `zusage` + „geantwortet" is
  exactly what it could say. The repertoire registry has the search (over title, composer
  *and* arranger), tempo, key, the four flags, the four „has a file" fields, soloist and
  conductor. A field's `art` picks the value widget, generically for both: `text`, `datum`,
  `ohne` (no values, the operator carries the statement, as with `Zugang` or `Hymne`),
  `auswahl` (one `<select>`), `mehrfach` (chip multi-select) and the member-only `zusage`
  (termin + answer). The entries of `auswahl`/`mehrfach` come from the registry's `eintraege`.
- **`konzert` is not part of the repertoire's chain.** The same parameter switches the running
  order mode and restricts the player's queues, so it stays a fixed field: `titel_list` and
  `titel_playlist` apply it next to the chain (`_mit_konzert`), and `table.html` takes its
  `<select>` through `filter_zusatz` (`_filter_konzert.html`) below the rows. The running order
  view (`?konzert=<id>&edit`) has no filter at all — both of its lists come from their own
  querysets — and shows a hint pointing to the repertoire list instead.
- **A condition over a multi-valued relation is an `EXISTS` subquery, never a join.** This is
  not a style choice: `Q(groups__pk__in=[A]) & ~Q(groups__pk__in=[B])` compiles to a plain
  join plus `NOT (…)` on the **link row**, and Django correlates the subquery it builds for the
  negation to that row instead of to the person — so a member who is in A *and* in B slipped
  through the exclusion. `_gruppen_q` and `_zusage_q` (members) and `_personen_q` (soloist and
  conductor) therefore ask `Exists(… objects.filter(… OuterRef("pk"), …))`. Since no condition joins any more, no
  condition can duplicate a row either, which is why the builder has no `.distinct()` and no
  `mehrfach` flag; a future field that *does* join has to handle that itself. The regression is
  pinned in `FilterbauQTest`.
- **Rights are part of a field, and the gate has two halves.** `Feld.recht` is `None` or
  `intern.change_user`; `felder_kontext()` hides the rest from the dropdown, and
  `lese_bedingungen()` drops them again while parsing — a hand-written URL must not slip past the
  form. What this protects is the **order of operations**: the filter runs on the raw queryset in
  the view, while `MitgliederTabelle.__init__` blanks hidden fields only when it renders. A filter
  on `email__icontains` would therefore betray through the *hit count* what the cell keeps quiet.
  `PRIVACY_FIELDS` and `zugang` are gated; groups and the attendance fields are not. No
  repertoire field carries a right. The `namen` map handed to the topbar is
  `{field_key: {pk: name}}` — groups and termin labels, or soloists, conductors, keys and tempi.
- **The editor** is `_filter_baukasten.html` + `_filter_zeile.html` + `_filter_wert.html`, in the
  filter offcanvas, driven by `filter-baukasten.js`. Neither list has a `FilterSet` left.
  Its visible controls carry **no** `name`; the script writes one hidden `<input name="f">` per
  row and disables it while the row has no values (except for `ohne` fields, where no values are
  the point). New rows are cloned from `<template>` elements, **one per field**, not per `art`:
  soloist and conductor share `mehrfach` but not their entries and labels, and keyed by `art`
  a row switched from one to the other kept the first one's list. Cloned markup arrives
  uninitialised, which is why `chip-multiselect.js` exposes `window.chipMultiSelectInitAlle`.
  The **choice lists come as one JSON bundle** (`filter-optionen`, `{field: [{wert, label}]}`,
  from `Baukasten.optionen()`), not as `<select>` markup: there are hundreds of termine and
  people, and they would otherwise be repeated in every row and every template.
- **Fixed switches.** A yes/no field without a value (`ist_fest()`: `ohne_wert` plus one
  yes/no pair — the repertoire's four flags and four „has a file" fields, the members'
  `Zugang`) is not in the field dropdown. Like `konzert` it is always there, as a compact grid
  of three-state switches below the chain, „egal" by default; each switch carries its own
  hidden `f` input. These conditions apply to the whole chain: `lese_bedingungen()` moves them
  to the front, `baue_q()` builds `fest und (Kette)`, and the topbar parenthesises the rest of
  the chain when it has more than one `oder` segment. An `oder` on them is deliberately not
  offered.
- **The three-state switch in a row** (✗ / · / ✓) replaces the operator `<select>` where a
  field has one yes/no pair (`hat_paar()`: two operators, the first affirmative, the second
  negating) **and a single value** — tempo, key, attendance (`hat_schalter()`). It sits right
  next to the value, which then collapses to its content width. A multi-select (groups, voice,
  soloist, conductor) keeps the „ist in / ist nicht in" list: an empty selection already says
  „egal". Text and date fields keep their word operators. The field and operator selects carry
  no caption, only an `aria-label`, and the row's ✕ always sits at the right. It reuses the
  `.tri-toggle*` classes but is
  driven by `filter-baukasten.js`, not `tri-toggle.js`, which bails out without a sibling
  `.tri-toggle-select`; the thumb offset is rendered inline for that reason. Two traps: the
  **operator `<select>` stays in the DOM**, hidden — `aktualisiere()` reads it unconditionally,
  and the switch only sets its value; and the **middle position („egal") silences the row**
  (`data-egal`, hidden input disabled) while field and values stay, so it can be switched back
  on. Without that an `ohne` field such as `Zugang` would keep sending its last operator.
  Segment clicks do not fire `change`, so the switch has its own `click` handler.
- **The manager's access default** is prepended as a `Zugang: hat` condition rather than injected
  as a URL parameter. It is a real row in the editor and a real chip in the topbar; removing that
  chip sets `?zugang=egal`, because an absence cannot be told from "never had one" otherwise.
  The form follows the same rule: `feste_kontext()` names each fixed switch's `marker`, and when
  the `Zugang` switch stands on „egal" at submit, the script adds `zugang=egal` as a hidden
  field.
- **The topbar is one chain, not a second bar.** `filter_kette` hands its elements to
  `filter_chips`, whose rows are either a chip, a connector word or a parenthesis; chips stay
  removable links. **A chip is a finished sentence**, never „Feld: Wert": the operator carries
  its wording in `Feld.operatoren` and fills `{w}`/`{feld}`, so it reads „ist in Gruppe A, B",
  „hat keinen Zugang", „hat geantwortet zu Konzert am 06.06.27". `satz_bauer` overrides that
  where the wording depends on the values — the answer brings its own verb, so the negation
  lands in the right place („hat nicht zugesagt", but „hat eine Angabe gemacht"). The sentence
  contains the „nicht" itself, so nothing prefixes a second one; `ist_verneinend` only paints the
  chip red. `filter_chips` also
  tolerates `filter_obj=None`, which is what the member list passes. `MAX_CHIPS` caps the chain at
  three conditions and collapses the rest into a „+n" that opens the filter. A capped chain drops
  its parentheses — half a bracket is noise — and carries the full sentence in its `title`.
- **Guards in `table.html`**: the column selector hangs on `column_choices` (matching its button
  in `base.html`), the filter panel on `filter or baukasten`, the chip line on `filter or kette`.

## Remembered list state

A list remembers its last sort and filters per device. `@tabellenzustand`
(`views/_decorators.py`, placed below `@login_required`) handles this on the server:

- A `GET` with query parameters stores them without `offset` in a cookie whose `Path` is the
  list's path. The name comes from `zustand_cookie(path)`, a hash, because `Path` matches as a
  prefix and a fixed name would be ambiguous (`/intern/ordner/1/` vs. `/intern/ordner/12/`).
  The cookie is only written on a 200.
- A `GET` without parameters answers with a 302 to the stored state **before the view runs**.
  It used to be a script at the end of `table.html`: the server rendered the unfiltered list
  first and the browser then loaded the filtered one, so the list jumped.
- A `GET` without parameters whose `Referer` path is the list itself („Zurücksetzen" `href="?"`,
  the last filter chip removed, a menu click on the open list) forgets the state.
  `SECURE_REFERRER_POLICY = "same-origin"` guarantees that header.
- Infinite-scroll fetches and `POST` (column selection) pass through untouched.

Every new view that renders `table.html` needs the decorator.

## Public homepage

`templates/index.html` + `intern/static/intern/css/main.css`. The public landing page does
**not** extend `base.html` and does **not** use `intern.css` — it is a standalone one-pager
with its own stylesheet and its own token block in `:root`. It is light mode only: no
`[data-theme="dark"]` block and no `_theme_boot.html`, because the photo hero, the white
`.is-solid` header state and the rose Kontakt band are a composed look, not a token swap. The
`--gold*` tokens are the one deliberate exception to the dark-value rule in `CLAUDE.md`: that
rule governs `intern.css`, where two themes share one set of component styles, while `main.css`
has only one. The page **does** include `_brand_boot.html`, directly after the `main.css` link,
so `--brand` follows `BRAND_FARBE`; `--brand-dark`, `--brand-soft` and `--band` are derived from
it with `color-mix()`, exactly as in `intern.css`. What does *not* follow is every logo: the
`JG-Frankfurt*.svg` files carry `#c14468`/`#000000` as literals, so a deployer with an unrelated
brand gets a rose logo (an open point in `docs/branding.md`).

Structure: fixed header over a full-bleed photo hero (a frosted-glass pill behind the navigation
at the top, `.is-solid` white after 60 px of scroll — set by a small inline script at the end of
the page), then Über uns (the club tagline as its eyebrow, then two cards), Konzerte
(date/title/place rows, each followed by the public announcement text when `Termin.extern` is set),
Galerie (single wide photo band), a Kontakt section on a warm rose band
and a light footer. The hero carries nothing but the wordmark and the two buttons: the tagline
went to the Über uns section first (it was the smallest type up there and pulled a scrim to the
top of the picture), and the subline followed it out of the picture entirely.

**The Konzerte list follows `Termin.extern`, not `Termin.repertoire`:** `home()` excludes only the
two empty forms of the announcement text, so an event without one stays off the page even when it
is a public gig. The gig-reminder mails follow the same set — `OHNE_ANKUENDIGUNG` in
`intern/models.py` (see `docs/mailinglist.md`). The
selection deliberately checks the raw field while the rendered block checks the filter result —
that is how a single space lists an event without producing an empty box. That is also why the
condition measures the field's *length* instead of comparing it to `""`: MariaDB's
`utf8mb4_general_ci` pads strings for comparison, so `' ' = ''` is true there and a `= ""` filter
dropped exactly the gigs the space was meant to lift onto the page — visible only on the
production database, never on SQLite.

The palette is warm — cream instead of white-grey, a warm dark instead of black. `--gold` is a
second colour standing for the invitation rather than the brand, and it appears in exactly two
places: the top border of the „Wir suchen Sängerinnen und Sänger" card (`.card-aufnahme`) and the
eyebrow plus link of the Kontakt section. (It was three until the hero eyebrow moved to the Über
uns section, where `.section-head .eyebrow` colours it in the brand rose like every other
section label.) It is a fixed value and deliberately **not** derived from `--brand`: a deployer
who sets an unrelated brand colour has to retune it by hand, which is the price of having a
counterweight to the brand at all. `--gold` itself carries only surfaces and rules (2.7:1 on
white); wherever it has to be read it is `--gold-text` or `--gold-band`.

**Nothing is laid over the hero photo any more.** The two scrims are gone. The top one
(`.hero-media::after`) is now a frosted-glass pill on the navigation itself
(`rgba(255, 255, 255, 0.75)` plus a 10 px `backdrop-filter`): the header crosses the dark roof
on the left and the bright vault, gable and organ pipes on the right, and no single type colour
survives both — white stood at 4.41:1 on the bright parts until the band was raised to 0.66/0.56,
dark ink drops to about 1.6:1 on the roof. Behind the glass the ground is bright and even, so ink
type holds on both, and the pill travels with the navigation instead of shading a band across the
whole picture. The text-zone gradient (`::before` with its `mask-image`) is gone as well: it
existed for the hero subline, and that subline was dropped. That also removed the reason for
`.hero-media`'s `z-index: 0` stacking context — with no pseudo-elements left there is nothing to
paint under the photo. `.is-solid` switches the pill off (`background: transparent`, no filter)
once the white header carries the type on its own. What is left on the picture is the wordmark,
which is a logotype and therefore **exempt** from the contrast requirement (WCAG 1.4.3) — its
drop shadow is decoration, not protection — and the two buttons, which carry their own surfaces:
`.btn-primary` is brand-filled, and `.btn-ghost` has a 42 % dark glass, because over the bright
wooden floor a white border on its own would vanish.

Nothing on the photo is measured in alphas any more, so the recipe that used to live here (hide
`.hero-inner`, keep the scrims, read the brightest pixel under each text element, solve for an
alpha that brings it under 0.18) is retired with the scrims. Its findings are worth keeping for
anyone who puts type back on the picture: the navigation links held 4.41:1 with a 0.55/0.46 band
and 5.8:1 at 0.66/0.56, the subline 6.9:1 and the ghost button 9.7:1. Two traps it caught: a
gradient ending at 58 % *looks* plausible but leaves the wordmark with no scrim at all, and dark
type is not an option anywhere in this frame — the choir's black clothing and the dark roof sit
behind the text band. The design this replaced flooded the whole picture at up to 0.9 alpha, over
a photo whose mean brightness is 0.343.

A note on the alternative: there is no position in this frame where type needs no scrim at all.
A 12 × 10 map of the brightest pixel per cell shows the only dark region (≤ 0.10) is 120 px wide
in the top-left, too narrow for the 480 px wordmark, and the text band is a *mix* — only 12–41 %
of its pixels are bright, the rest is the choir's black clothing — so dark type would need ~55 %
of lightening instead. The three real levers are the dimmed **area**, the required alpha via
type size (3:1 instead of 4.5:1 from 24 px up), and taking the text off the photo altogether.
This page has now taken the third one twice: the subline is gone, and the header moved its
protection off the picture and into a surface of its own.

**The Kontakt section is a brand band, not a dark surface.** `--band` is `--brand` at 90 %
towards black, and those 10 % are load-bearing: plain `--brand` carries white at only 4.89:1, so
not one character on it may be transparent, while 90 % gives 5.79:1 and leaves room. All type on
the band is full white; gold appears only as `--gold-band` (a pale gold, 4.6:1) for the eyebrow
and the link, and as `--gold-soft` (3.57:1, above the 3:1 bar for non-text) for their rules.
This is the one place where a pale `BRAND_FARBE` bites first, since `--band` follows it down — a
brand too light to carry white is broken elsewhere already: `intern.css` and `.btn-primary` have
put white on `--brand` all along.

**The footer is light** — cream background, warm ink, and the *black* wordmark
(`intern/brand/JG-Frankfurt.svg`); the light `JG-Frankfurt-transparent.svg` of the hero would be
invisible on it. `intern/images/JG-Frankfurt-wG-color.svg` is not an alternative there: its
white backing ellipse shows as a pale disc on cream. The copyright line uses `--muted` (5.2:1
on cream); the old `rgba(255, 255, 255, 0.45)` on near-black was 3.4:1 and missed AA.

Logo usage in the header is unchanged: the round mark
(`intern/images/JG-Frankfurt-wG-color.svg`) over the photo, swapped for the black wordmark
(`intern/brand/JG-Frankfurt.svg`) once the header turns white — below 460 px the mark stays. The
hero headline uses the light wordmark (`intern/brand/JG-Frankfurt-transparent.svg`) as an image
inside the `<h1>`; its font (Showcard Gothic) exists only as outlines in the SVG, so the
lettering can only be used as an asset, never as a webfont. The favicon redirect in
`config/urls.py` relies on the tracked source copy of `JG-Frankfurt-wG-color.svg` in
`intern/static/intern/images/`.

All copy comes from `Konfiguration` (`HOMEPAGE_UEBER_UNS`, `HOMEPAGE_AUFNAHME`, `VEREINSNAME*`,
`VEREINSADRESSE`, `DEFAULT_FROM_EMAIL`); `home()` in `views/auth.py` passes `HOMEPAGE_UEBER_UNS`
whole to the Über uns card. The
hero and gallery images are pre-scaled derivatives of the choir photo in
`intern/static/intern/img/` (`chor-{800,1400,2000}.jpg` for the hero `srcset`,
`chor-band-{1100,1800}.jpg` for the gallery band); regenerate them from the original with
ImageMagick when the photo changes. Assets are referenced via `{% static %}`, so
`collectstatic` covers them.

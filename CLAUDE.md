# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Language:** This file must be written strictly in English. Do not add German prose; code identifiers and string literals (e.g. filenames, variable names) may remain in their original form.

## Commands

**Fresh install — resets DB, imports avatars, starts server (DEV + Container):**
```bash
./migrate.sh              # DEBUG not set → nginx + gunicorn (prod/container)
DEBUG=1 ./migrate.sh      # DEV: runserver
```

**Start with existing DB (no wipe):**
```bash
./start.sh                # DEBUG not set → nginx + gunicorn (prod/container)
DEBUG=1 ./start.sh        # DEV: runserver
```

**Run dev server only (after migrate.sh has been run):**
```bash
python manage.py runserver 0.0.0.0:8000
```

**Create and apply migrations:**
```bash
python manage.py makemigrations intern --name <migration_name>
python manage.py migrate
```

**Build and run Docker container:**
```bash
docker build -t cantoreub .
docker run -p 8000:8000 cantoreub
```

**Management commands:**
| Command | Description |
|---|---|
| `ejabberd_admin sync` | Full startup sync (ensure bot, assign MUC JIDs, configure rooms); no-op if ejabberd is not configured (`is_ejabberd_configured()`) |
| `ejabberd_bot` | Run XMPP bot for MUC message forwarding; no-op if ejabberd is not configured |
| `ejabberd_admin <group> <verb>` | Admin ops grouped by noun: `bot ensure`; `room {list,assign-jids,configure,delete,avatar,members,occupants,options}`; `user {list,delete,vcard,password}`; `invite {add,remove,clear}`; `server users` |
| `send_reconfirmation --user USERNAME` | Send data-reconfirmation mail to one active member |
| `send_reconfirmation --all` | Send data-reconfirmation mail to all active members with an email address |
| `send_reconfirmation --user USERNAME --print-url` | Print the confirmation URL for one member without sending mail (for testing) |
| `send_reconfirmation --all --print-url` | Print confirmation URLs for all members (tab-separated `username<TAB>url`) without sending mail |
| `make_invite_url EMAIL` | Print a signed 7-day invite link for the Neuantrag form (`/intern/beitritt/<token>/`) without sending mail |
| `send_auftritt_erinnerungen [--loop] [--dry-run] [--now ISO] [--termin ID] [--force]` | Send the public gig reminders of the Auftritts-Mailingliste. **One pass is the default, `--loop` is the daemon** started by `start.sh`. `--now` overrides "now" so the timing can be tested without touching the clock; `--force` ignores existing `ErinnerungVersand` markers |
| `cleanup_changelog [--days N] [--dry-run]` | Delete `ChangeLog` entries older than the retention period (default 3 years = 1095 days), enforcing the privacy-policy §10 claim. Runs in the background on every `start.sh` |
| `cleanup_dateiversionen [--keep N] [--days N] [--dry-run]` | Prune `DateiVersion` rows **and their blobs** (plus the thumbnails generated next to them): everything older than `--days` (default 730 = 2 years) or beyond the newest `--keep` revisions per file (default 10). Runs in the background on every `start.sh`, but with `--keep 25 --days 36500` — see "Retention: what the cleanup jobs actually delete" |

## Architecture

CantorHub is a Django 6 member portal for "Just Gospel Frankfurt", a gospel choir. All application logic lives in the `intern/` app; `config/` holds only settings and URL routing. Views are split into domain modules under `intern/views/` (`auth.py`, `files.py`, `folders.py`, `forums.py`, `titel.py`, `termine.py`, `mitglieder.py`, `artikel.py`, `karte.py`, `orte.py`, `gallerie.py`, `auftritte.py`). The package's `__init__.py` re-exports all public views, so `urls.py` uses `views.forum_list` etc. unchanged.

Two underscore-prefixed modules hold what the view modules share:

- **`views/_pagination.py`** — everything the infinite-scroll lists need.
  `parse_offset(request)` reads `?offset=` (never negative, never raises, capped at
  `_MAX_OFFSET` — an offset beyond the DB's 64-bit range is an error, not an empty
  result, and the value comes from the URL). `ist_nachladen(request)` recognises the
  `X-Requested-With` fetch. `nachlade_antwort(template, context, has_more, next_offset,
  request=None, **extra)` renders the row fragment and returns the JSON the sentinel
  script expects (`html`, `has_more`, `next_offset`, plus any `extra` such as the
  permission matrix). Pass `request` only when the fragment really needs the context
  processors — otherwise they (and their termin-banner queries) run on every scroll.
  `paginate_ordered()` applies `?sort=` before slicing.
- **`views/_decorators.py`** — `perm_or_home(perm)` guards the three management pages
  (`aufgaben`, `gruppen`, `aenderungsprotokoll_list`): permission or superuser, else a
  silent redirect to „Aktuell" rather than a 403, because a member without the right
  never sees the menu entry. It includes `login_required`.

### Request flow

```
Browser → haproxy (TLS) → nginx (port 8000) → gunicorn (127.0.0.1:8001) → Django
```

Nginx serves `/static/`, `/media/`, and `/tiles/` directly; everything else is proxied to gunicorn. In development, `manage.py runserver` handles everything.

**Two things the front proxy has to get right**, because Django cannot detect either
of them going wrong:

- **The client IP.** `_client_ip()` (`views/auth.py`) takes the *last* entry of
  `X-Forwarded-For` — a client-supplied header always ends up further left and can
  therefore never win. That only holds because `nginx.conf` runs the realip module
  (`set_real_ip_from 10.88.0.0/16; real_ip_header X-Forwarded-For;`), which turns
  `$remote_addr` into the real client address before it is forwarded as the single
  XFF entry. Without it every visitor arrives as the proxy's address, which silently
  turns both rate limits (password reset, mailing-list sign-up) into *global* ones —
  one sender then locks out everybody — and makes `Auftrittsabo.bestaetigt_ip`
  worthless as Art. 7(1) evidence. The trusted CIDR is the podman network; adjust it
  if the deployment moves. Getting it wrong is fail-safe: realip simply does not
  engage and behaviour falls back to what it was.
- **`X-Forwarded-Proto: https`.** haproxy must set the literal string — `%[ssl_fc]`
  renders as `1`/`0` (it is a boolean), which never matches
  `SECURE_PROXY_SSL_HEADER`. When it does not match, `request.is_secure()` is
  permanently `False` and every `build_absolute_uri()` emits `http://` links: the
  password-reset mail, and via `_base_url()` the opt-in and unsubscribe links of
  every mailing-list mail. Use `set-header X-Forwarded-Proto https if { ssl_fc }`
  (or `%[ssl_fc,iif(https,http)]` from haproxy 2.3 on).

`X-Forwarded-Host` and `X-Forwarded-Port` are **deleted** by nginx (`proxy_set_header
… "";`) and correspondingly `USE_X_FORWARDED_HOST` / `USE_X_FORWARDED_PORT` are off:
no hop in this chain sets either header, so whatever arrives is the client's own
invention — and Django would feed it into `request.get_host()`/`get_port()` and hence
into every `build_absolute_uri()`. The real host travels in the `Host` header, which
nginx forwards. Do not switch those settings back on without a proxy that actually
writes the headers.

gunicorn binds to `127.0.0.1:8001` on purpose — nginx is in the same container, and
a wildcard bind would be reachable over the podman bridge, bypassing nginx and thus
realip. The dev branch (`runserver 0.0.0.0:8001`) stays open deliberately.

**Client IPs are logged in two of the three channels**, and the distinction matters for
the §10 retention promise (see `datenschutz.md`):

- The **access log is IP-free**: `log_format simple` in `nginx.conf` has no
  `$remote_addr`, gunicorn runs without an access log, and Django's `LOGGING` carries no
  request context. A normal request therefore leaves no address behind.
- The **error log does record it**: nginx writes `client: <IP>` on every error — a 404
  under `/static/` or `/media/`, a rejected `auth_request` subrequest. It goes to
  `/dev/stderr` and thus into journald / `podman logs`, the same stream as the access
  log. Before realip engaged this was the front proxy's own address and therefore
  worthless; **since it engages, it is the real visitor's address.** Nothing in this
  repository suppresses it, and a `client:` line is the simplest way to check what nginx
  actually resolved (see the deploy note below).
- The **haproxy log** (`%ci`) is the third place, one hop earlier.

**`nginx.conf` lives in the image, not in the mount.** The `Dockerfile` does `COPY
nginx.conf /etc/nginx/`, while the application code is deliberately *not* copied
(`#COPY --chown=appuser:appuser . .`) and is bind-mounted instead. Changes to
`nginx.conf` therefore take effect only after a **`podman build` plus a container
restart** — a `git pull` alone silently keeps the old config, which is exactly how the
realip lines above sat inert for a while after they were committed. Verify with:

```bash
podman exec <container> nginx -T | grep real_ip
```

and confirm the resolved address by requesting a file that does not exist (no login
needed, leaves nothing behind) and reading the `client:` field of the resulting error
line:

```bash
curl -s -o /dev/null https://<host>/static/proxy-check-gibtsnicht.css
journalctl -u <unit> -n 30 --no-pager | grep proxy-check
```

### URL structure

- `/` — public homepage (`templates/index.html`)
- `/datenschutz/` — public privacy policy (`templates/datenschutz.html`, no login required, `TemplateView` in `config/urls.py`)
- `/auftritte/`, `/auftritte/bestaetigen/<token>/`, `/auftritte/abmelden/<token>/` — public gig-reminder mailing list (no login; see "Auftritts-Mailingliste")
- `/tiles/<z>/<x>/<y>.png` — OSM tile proxy (no login required). In production nginx intercepts this and serves from its disk cache (`/app/tiles/`, 7-day TTL) without hitting Django. In dev, `tiles_proxy` in `karte.py` fetches from OSM server-side so the user's IP is never sent to OSM.
- `/admin/` — Django admin
- `/intern/*` — all authenticated views (`intern/urls.py`)
- `/intern/karte/geocode/` — Nominatim geocoding proxy (`geocode_proxy` in `karte.py`, login required); passes query params server-side so the user's IP is never sent to Nominatim.

### Detail pages

All list views use django-tables2 with clickable rows (`data-href` on `<tr>`). Each table row navigates to a detail page. Detail pages have an edit button in the top bar (via `edit`/`id` context variables rendered in `base.html`).

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

Detail pages use the `.detail-page` / `.detail-card` CSS layout (2-column card grid, single column on mobile). Edit pages use the `.wiki` container with `.form-grid`.

**Form fields are rendered via the `{% form_field %}` inclusion tag** (`intern/templatetags/form_tags.py` → `_form_field.html`): `{% form_field form.feld "Label" %}` emits the standard `form-group` (label, widget, `invalid-feedback` errors). Options: `req=True` shows the `*` marker when the field is required (join form), `privacy=form.priv_x` appends the "verbergen" checkbox when `can_set_privacy` is in the context (member edit), `hilfe=True` renders `help_text` (opt-in so Django's default help texts, e.g. on `username`, don't leak in). Without `label` the form field's own label is used. Non-standard groups (checkbox rows, label-less textareas, the search-select Ort widget, static read-only rows) stay hand-written.

**Deleting is confirmed by `_confirm_delete_dialog.html`** — one `<dialog id="delete-dialog">`
for `ort_edit.html`, `termin_edit.html` and `titel_edit.html`: `{% include
"_confirm_delete_dialog.html" with titel="Ort löschen" objekt=ort.name action=loeschen_url %}`
(resolve the URL with `{% url … as loeschen_url %}` first). `warnungen` takes a list of extra
lines naming what a delete would take with it — `termin_edit` passes `loesch_warnungen`, built
in the view so the pluralisation stays in Python. The opening button stays in each page's
`.form-actions`, because it is guarded differently per page (`titel_edit` renders it disabled
with a tooltip when the song is still referenced, and then omits the dialog entirely).

### Attendance (Zusage) options

`Zusage.option` values: `"1"` = Zusage, `"2"` = Absage, `"3"` = Eventuell, empty/missing = Keine Angabe. The attendance table on the termin detail page groups users by `Stimme` (S, A, T, B, C, M) and splits into two tables on mobile.

**Next-event banner:** a slim banner is shown site-wide at the top of `<main class="content">` in `base.html` (`_termin_banner.html`), highlighting the next upcoming event (`banner_termin` / `banner_my_option`, computed in `config/context_processors.py`'s `project_meta`) with a `timeuntil` countdown, location and — when `anwesenheit=True` — the same quick Zusage buttons (governed by `ZUSAGE_TRANSITIONS`). The buttons POST to `termin_zusage` with a hidden `source=banner` field, which makes that view render `_termin_banner.html` instead of the detail widget (htmx swaps `#termin-banner`). The banner is rendered with the `hidden` attribute and only revealed by a small inline script at the end of `_termin_banner.html` — the dismissed state lives in `localStorage` and is therefore not known server-side, so deciding before paint avoids a flash of a banner that is immediately removed. That script removes the banner on that termin's own detail page (avoids a duplicate widget) and when it was dismissed for the current login session: both the dismiss button and following the banner link to the termin store the session key `banner_login` (exposed as `data-login`) in `localStorage["termin-banner-dismissed"]`, so the banner reappears after the next login when that value changes. `banner_login` is `"<pk>-<last_login timestamp>"` and is computed in `project_meta` from `request.user` on purpose — reading `user.last_login` in the template would break on detail views such as `mitglied_view`/`mitglied_edit`, which shadow `user` with the member being looked at. The script sits *inside* `#termin-banner` so an htmx `outerHTML` swap replaces it along with the markup; `intern.js` (`initTerminBanner`) keeps the dismiss click handler and the same logic as a fallback. On mobile (≤640px) the dismiss button is absolutely positioned in the banner's top right corner.

### Calendar (month view)

`/intern/kalender/` (`termin_kalender` in `views/termine.py`, name `termin_kalender`, sidebar
entry right after "Termine") is a classic month grid (7 columns Mon–Sun) — not an agenda.
Month is chosen via `?jahr=&monat=` (defaults to the current month; invalid values fall back
to it). The grid is built with `calendar.Calendar(firstweekday=0).monthdatescalendar()`; the
leading/trailing days of neighbouring months are shown dimmed (`.is-outside`). Events are loaded
once with an **overlap** query (`datum__date <= grid_end AND (datum_bis >= grid_start OR
single-day in range)`) so multi-day events (`datum_bis`) that start before or end after the grid
are caught; each is expanded to one occurrence per covered day (a dict `{t, mehrtaegig, start,
ende}`), rendered as a connected band (`.is-span` chips bleed into the cell padding, clipped by
`.cal-day{overflow:hidden}`; only the start/end day is rounded, continuation days show a `‹`
marker) that wraps correctly across week and month boundaries. Birthdays are active members with
a set `geburtstag` **whose field is not hidden**
(`"geburtstag" not in user.private_fields`, no viewer/admin bonus — same for everyone) mapped by
`(month, day)`. Each event chip links to `termin_view`, each birthday chip to `mitglied_view`.
Prev/next/"Heute" navigate via htmx: the toolbar + grid live in the partial `_kalender_grid.html`
(wrapped in `#cal-view` by `kalender.html`); an `HX-Request` renders only the partial (swapped
into `#cal-view`, `hx-push-url` keeps the URL in sync). Clicking any day with entries opens a
large offcanvas detail panel (`#cal-day-panel`, sibling of `#cal-view` so it survives swaps):
`kalender.js` clones that day's `.cal-day-detail` into the panel and shows its German date label
(`d.label` → `data-datum`); Esc/overlay/close button dismiss it. On desktop the cells show the
chips inline; below 768px they collapse to coloured dots (`--brand` = event, `--cal-geb` =
birthday) and the panel is the readable view. The whole month grid fills the viewport height —
`.content:has(.cal-page)` becomes a flex column so the grid (with `grid-auto-rows: 1fr`) shares
the space with the next-event banner without a scrollbar. CSS lives under `/* === Kalender === */`
in `intern.css`; birthdays use the `--cal-geb` / `--cal-geb-bg` tokens (green, distinct from the
pink event colour) and weekend day numbers/headers use `--cal-weekend` (red) — all with dark-mode
values. Note `USE_TZ = False`, so `datum` is naive — group by `t.datum.date()` directly (do not
call `localtime()`).

The forum edit page (`/intern/forum/<id>/edit/`) and its XMPP behaviour — room-info card, invite flow, avatar sync (`_sync_forum_avatar`), MUC room invariants (`configure_room`), the Forum→MUC relay and the `_relay_cursor` restart gap — are documented in `xmpp.md`.

### Forum read permissions

Forums are open to every logged-in member by default. Holders of
`intern.manage_forum_permissions` can restrict a forum to specific groups via the
lock button on the forum detail page (`/intern/forum/<id>/zugriff/`,
`forum_permissions` view, `forum_zugriff.html`) — analogous to the article
permissions, but **read-only**: there is no separate write right. Whoever may read a
forum may also post; whoever may not read it doesn't see it at all.

Model `ForumPermission(forum, group)` (`intern/models.py`): the **presence** of any row
for a forum marks it restricted to the listed groups; no row = open. `_forum_access(user,
forum_id)` and `_hidden_forum_ids(user)` in `views/forums.py` mirror `_artikel_access` —
holders of `manage_forum_permissions` always have access. Enforcement covers the forum
list/search, detail/poll/more/send views (403 for non-readers), and the notification
bubbles in `views/notify.py` (restricted Forum/Mitteilung entries are dropped per user).

Because each forum is also an XMPP MUC room, the restriction is synced to ejabberd so it
can't be bypassed in an XMPP client: saving permissions runs `_reconcile_forum_muc`
(removes non-reader affiliations, ensures readers are `member`), the bot's
`_db_invite_missing_users` only invites permitted readers, and `forum_invite` refuses
non-readers. See `xmpp.md`.

Permission changes are recorded in the audit log: `_audit_forum_permissions`
(`views/forums.py`) writes a `ChangeLog` row under `model_name="Forum"` with a
`berechtigungen` change (group-name labels, or "Alle Mitglieder" when open), so it shows
up in `forum_aenderungen` next to the regular forum-field edits. The forum's audited
fields are `thema`, `aktiv`, `bild_id`, `xmpp_muc_jid` (`_AUDIT_FIELDS` in `signals.py`).

### Forum reactions

Members can react to individual forum messages with emoji (XEP-0444), synced both ways
with the linked MUC room. A reaction bar renders under each message bubble
(`_message.html` → `.reactions` container, populated by `forum.js`); a `+` opens a small
picker (fixed quick set **plus** a free-emoji input). `forum.js` polls
`forum_reactions` (JSON) every 5 s and re-renders all bars, so XMPP-originated reactions
appear too; clicks POST to `forum_react` (`X-CSRFToken` via `getCsrfToken()`). Both views
(`views/forums.py`) are gated by `_forum_access` — whoever may read a forum may react.

Model `Reaktion` stores one row per (message, reactor, emoji) with `origin`
(`"web"`/`"xmpp"`). XEP-0444 replace semantics (a reactor's stanza restates their full
set) are implemented as delete-then-insert per reactor. The Forum↔MUC relay, the
bot-attribution limitation (web reactions appear in XMPP clients bundled under
`CantorBot`), and the origin-id stanza-id capture are documented in `xmpp.md`.

### Article editor & versioning

`Artikel` rows are immutable versions keyed by `(name, version)` — articles are addressed by `name`, not `id`. Saving an edit at `/intern/artikel/<name>/edit/` creates a new `Artikel` row with `version + 1` rather than mutating the existing one. The editor (`artikel.html`, edit branch) renders the `.article-editor` shell: an identity bar, a collapsible `.ae-help` syntax cheat-sheet, the textarea inside a `.wiki` container (kept so `abstimmung.js`'s `{abstimmung:...}` helper still binds), and a footer action bar.

`article_view` shows the latest version by default, or a specific one via `?version=<n>`. When viewing an outdated version it renders the `.version-banner` — a warning plus a version stepper with previous/next links (`prev_version` / `next_version`, computed via DB queries so gaps in the version sequence are skipped) and an "Aktuelle Version" button. History and unified/side-by-side diffs live at `/intern/artikel/<name>/history/` and `/diff/`.

New articles are created from the `+` in the article-list topbar (`article_list` sets `add`/`add_panel_include`). It opens the off-canvas panel `templates/artikel_add_panel.html`, which has **no** server form — a small vanilla script reads the entered page name and navigates client-side to `/intern/artikel/<name>/edit/` (built from the panel's `data-edit-url` `__NAME__` placeholder + `encodeURIComponent`), where the first save creates version 1. Shown to every logged-in member, matching the open-wiki default (`article_edit` has no permission check for a new name).

### Automated e-mails

Every automated mail carries its **entire** visible body in a `MAIL_*` key of the
`Konfiguration` table — no sentence lives in a template. The templates only supply the
branded frame: `templates/emails/base.html` (card, logo header, footer text from
`MAIL_FOOTER`), `generic.html` (renders `body_html`) and
`mitglied_benachrichtigung.html` (round mail, adds the signature block via the
`after_body` block). Subjects remain in Python.

`intern/mail_markup.py` renders one config text into **both** MIME parts (HTML with
inline styles, plain text) using the wiki syntax of the article editor — `'''fett'''`,
`''kursiv''`, `== Titel ==`, `*`/`#` lists, `% grauer Hinweis`, `@ Hinweisbox`,
`: Einrückung`, `[https://… Name]`, `$roh$` — plus the mail-only directive
`{button:Label}` (links to `{link}`) / `{button:Label:URL}`. A button without a URL
renders nothing. Placeholder values are HTML-escaped; unknown `{placeholders}` stay
verbatim. `/intern/konfiguration/` shows a syntax legend while a `MAIL_*` row is edited.

Call sites use `mail.send_config_mail(subject, to, key, user=…, link=…, extra_keys=…,
attachments=…, template=…, context=…, **placeholders)`; `render_config_mail()` /
`render_mail_text()` return the `(html, plain)` pair for callers that need it.
`extra_keys` holds conditional add-on texts (the minor/supporting-member notes of the
application admin mail) and is rendered at `{hinweise}`. See `configuration.md` for the
full markup table, the placeholder list and the recipe for adding a new mail.

### Member application flow (Mitglieds-Beitritt)

Two ways to add a member, both behind the `+` in `/intern/mitglied/` (perm `intern.add_user`).
The off-canvas panel (`templates/mitglied_add_panel.html`, included via the
`add_panel_include` context var in `table.html`) is two-step:

1. **Invite** (default step): an admin enters only an e-mail and submits to
   `mitglied_invite` (`views/mitglieder.py`). This sends a branded e-mail with a
   non-guessable link to the public join form. No user is created yet. The link
   carries the e-mail in a `TimestampSigner` token (salt `intern.mitglied_invite`,
   **7-day** validity) — `make_invite_token()` / `_read_invite_token()` in
   `views/auth.py`. Stateless: no DB model, no placeholder user.
2. **Manuell anlegen** (JS-revealed): the existing `MitgliedAddForm` posting to
   `mitglied_add`, which creates an **active** member immediately (unchanged).

The public join form lives at `/intern/beitritt/<token>/` (`mitglied_beitritt` in
`views/auth.py`, **no** `login_required`). `MitgliedBeitrittForm` (`forms.py`) validates
all member fields — required: first/last name, all address fields, `geburtstag`,
`username` (regex `^[A-Za-z0-9._-]{3,30}$` + case-insensitive uniqueness via
`username__iexact`), two matching passwords (`validate_password`),
five mandatory consent checkboxes (Richtigkeit der Angaben; Datenschutz — links to `/datenschutz/`; Datenverarbeitung; Satzung — links to the PDF configured via `SATZUNG_FILE_ID`; Beitragsordnung — links to the PDF configured via `BEITRAGSORDNUNG_FILE_ID`), and two optional fields (`einwilligung_fotos` for photo consent at public events, `foerdermitglied` for supporting membership). On success the member is created with `is_active=False`, a PDF of the completed
application is saved to the filer folder **„Verwaltung/Mitglieder"** (Vorstand-only,
via `_save_antrag_pdf` in `views/auth.py` using reportlab; best-effort, never blocks
registration), a confirmation mail goes to the applicant, and a notification mail goes to the address configured via `ANTRAG_EMAIL` (falls back to members with `intern.change_user` via `_member_managers()` if empty). If the applicant is a minor at submission time, the admin notification contains a warning. If `foerdermitglied` is checked, the user is immediately added to the `"Fördermitglied"` group (created by `0003_import.py`). The public
pages (`mitglied_beitritt.html`, `_success.html`, `_invalid.html`) extend the standalone
`mitglied_public_base.html` shell (no sidebar), not `base.html`.

The application is logged in the ChangeLog as a distinct action
`ChangeLog.ACTION_APPLICATION` (`"apply"` → "Neuer Mitgliedsantrag"): the view sets
`user._audit_application = True` before saving and `signals._write_audit_log` maps that
to the application action (the action code is ≤8 chars to fit `action`'s `max_length`).

All e-mails in this flow (invite, applicant confirmation, admin notification) and the
password-reset mail go through `intern.mail.send_config_mail()` — their whole body comes
from the matching `MAIL_*` key (see "Automated e-mails").

**Applicants are created with `date_joined=None`** (the field is overridden on `User` to be
nullable). This is the discriminator for the activation mail: when an admin later sets
`is_active=True`, `signals._send_activation_mail()` checks `user.date_joined is None` →
first-time activation → sends the `MAIL_WILLKOMMEN` text and stamps `date_joined`
via `User.objects.filter(pk=...).update(date_joined=timezone.now())` (avoids recursive
signal). If `date_joined` is already set → reactivation → sends `MAIL_REAKTIVIERT`.
Both texts get `{link}` = the login URL derived from `VEREINS_URL`; without it the
`{button:…}` in the text renders nothing. No mail is sent if the user has no email address.

### Member re-confirmation flow (Datenbestätigung)

Allows the board to request that existing members re-confirm their stored data and
re-acknowledge the privacy policy, bylaws, and membership fee schedule.

**Trigger:** `manage.py send_reconfirmation --user <username>|--all` (uses `VEREINS_URL` from config; override with `--base-url URL`)
(e.g. `--base-url https://portal.example.com`). The command calls
`send_bestaetigung_mail(user, base_url)` in `views/auth.py`, which:
1. Creates a `TimestampSigner` token (salt `"intern.mitglied_bestaetigung"`, **30-day** validity) encoding the user PK.
2. Reads the email body from the `Konfiguration` key **`MAIL_BESTAETIGUNG`** —
   editable via `/intern/konfiguration/` without code changes. All standard placeholders
   available plus `{link}`; an empty key means an empty mail body.
3. Sends it via `send_config_mail()` (branded frame `emails/generic.html`).

**Public form:** `/intern/bestaetigung/<token>/` (`mitglied_bestaetigung` in `views/auth.py`,
no `login_required`). Shows the member's current data (read-only) plus three mandatory
checkboxes (`MitgliedBestaetigungForm` in `forms.py`): data correct, Datenschutz, Satzung.

**On submit:** `_save_bestaetigung_pdf(user)` generates a PDF (reportlab) with all stored
data + confirmed checkboxes, saves it to **„Verwaltung/Mitglieder"** in filer, and attaches it
to the quittance mail sent to the member. The quittance mail body is configurable via
`MAIL_BESTAETIGUNG_BESTAETIGT` in `Konfiguration`.
No Vorstand notification. Three public templates extend `mitglied_public_base.html`:
`mitglied_bestaetigung.html`, `_success.html`, `_invalid.html`.

`MAIL_BESTAETIGUNG` and `MAIL_ANTRAG` are seeded by `_CONFIG_DEFAULTS` in `intern/apps.py` on `post_migrate`, like all other `MAIL_*` keys.

### Auftritts-Mailingliste (public gig reminders)

A public, membership-independent mailing list: visitors sign up at `/auftritte/` and are
reminded before each public gig. The triggering events are `Termin.objects.filter(
repertoire=True)` — exactly the ones `home()` already shows publicly; no model change on
`Termin`. Linked from the homepage in `#concerts` (`.concert-cta`) and as a third
`.contact-card` in `#contact`.

**Layers:** domain logic in `intern/mailingliste.py` (tokens, URLs, due-date arithmetic,
placeholders, sending), views in `intern/views/auftritte.py`, the daemon in
`intern/management/commands/send_auftritt_erinnerungen.py`. The time-dependent functions take
`jetzt` as an argument and never call the clock themselves — that is what makes `--now` and
the unit tests in `intern/tests.py` possible.

Those tests are **all `SimpleTestCase`, and they have to be**: a `TestCase` makes Django build a
test database, which runs the data migration `0003_import` — and that one talks to the legacy
MySQL server and expects imported filer files, so it blows up anywhere that environment is
absent. Every piece of logic worth testing is therefore kept free of DB access and the DB half
is isolated in a thin wrapper (`lese_abmelde_token()` vs `read_abmelde_token()`). Keep it that
way until `0003_import` learns to no-op without the legacy DB.

**Double opt-in.** `auftritte_anmeldung` does `get_or_create` and always renders the *same*
status page, whether the address was new, unconfirmed or already subscribed — anything else
would be an address oracle (same reasoning as `register()`). Only the mail differs. Two
brakes: an IP throttle via `cache` (LocMemCache, so per gunicorn worker — weak, same caveat as
the existing pwreset throttle) and the DB-backed cooldown on `optin_gesendet_am`
(`OPTIN_COOLDOWN_MIN`), which is the one that actually stops mail-bombing a foreign address.
A honeypot field `webseite` (off-screen via `.hp-feld`, **not** `type="hidden"`) short-circuits
to the success page.

**Confirmation and unsubscribe are POST-only** — GET renders a page with a button. Outlook
SafeLinks and virus scanners fetch links ahead of the human and would otherwise document a
consent nobody gave. Unsubscribing **deletes** the row (a stored address without consent is
itself a processing operation); an unknown token renders a friendly page with status 200,
because that is the normal second click.

**Due dates.** `faelligkeit()` = event time minus N weeks, i.e. automatically the same weekday
and hour; `MAILINGLISTE_VERSANDZEIT` is only a fallback for events with no time of day (00:00).
`faellige_erinnerungen()` fires within `faellig <= jetzt <= faellig + KULANZ_STUNDEN` (24 h), so
a long outage does not produce absurdly late mail. `USE_TZ = False` — everything is naive local
wall-clock time, never call `localtime()`.

**Idempotence.** `ErinnerungVersand.get_or_create()` runs **before** sending and its
`UniqueConstraint(termin, wochen)` is the only guard against parallel processes (daemon +
manual call + a test system on the same DB); there is no process lock and deliberately no
`transaction.atomic()` around the batch — the marker must be visible to others immediately, and
SMTP has no business inside an open transaction. Side effect worth keeping: whoever subscribes
after a reminder was due does not get it retro-fitted. Known gap: a crash mid-batch leaves the
marker standing and the remaining recipients unserved — recover with `--termin <id> --force`.

**The unsubscribe token is signed, not stored.** `make_abmelde_token()` signs
`<pk>-<fingerprint>` with a plain `Signer` (no timestamp — the link sits in every mail and must
stay valid forever). The fingerprint is a short SHA-256 of the address and is **not optional**:
primary keys get reused after a delete (SQLite hands out `max(rowid)+1` without AUTOINCREMENT),
so without it an old link from a long-sent mail could unsubscribe a *different* person who
later inherited that pk. The address itself deliberately stays out of the URL — it would
otherwise land in server logs, referrers and browser history. `lese_abmelde_token()` is the
DB-free half, which is what makes it unit-testable (see below).

**The unsubscribe link cannot be configured away.** `send_mailingliste_mail()` welds it into
the `List-Unsubscribe` header, appends it to the plain-text part *above* the `-- ` signature
separator, and `emails/mailingliste.html` renders it structurally in the HTML part. Emptying
`MAIL_MAILINGLISTE_ERINNERUNG` does not remove it. `List-Unsubscribe-Post` is deliberately
**not** set: providers then send an unauthenticated POST that the CSRF middleware rejects.

**No `{beschreibung}` placeholder** — see `configuration.md`; `mail_markup` substitutes before
parsing, so a multi-line `Termin.lang` could smuggle a `{button:…:URL}` into a mail to the
general public.

Without `VEREINS_URL` or `EMAIL_HOST` the daemon **warns and writes no marker** rather than
sending — a mail with a relative, i.e. dead, unsubscribe link is not defensible. Both are
re-read every iteration, so fixing the config takes effect without restarting the loop.
Privacy-policy coverage is §15 in `datenschutz.html`; open operational points (no bounce
handling) are recorded in `datenschutz.md`.

### Key models (`intern/models.py`)

| Model | Purpose |
|---|---|
| `User` | Extended `AbstractUser` — adds voice type, address, XMPP JID, coordinates |
| `Artikel` | Versioned articles/news items |
| `Forum` | Discussion threads; `bild` (FilerFileField), `aktiv` (Boolean), `xmpp_muc_jid` for XMPP bridge |
| `ForumPermission` | Read restriction `(forum, group)`; presence of rows = forum restricted to those groups, no row = open (see "Forum read permissions") |
| `Mitteilung` | Forum messages; adds `xmpp_stanza_id` for bridge deduplication and `reactions_dirty` (web-reaction relay flag). Display helpers `sender_name()` / `sender_avatar_url()` / `is_from_bot()` fall back to "Unbekannt"+`kein_photo.png` for `sender=None` and to nick `CantorBot`+`bot.png` for the bot JID |
| `Reaktion` | Emoji reaction (XEP-0444) on a `Mitteilung`; `origin` (`"web"`/`"xmpp"`), `sender` for display, `reactor_jid` for XMPP-origin. Per-reactor uniqueness is enforced in code (delete-then-insert), not a DB constraint. See "Forum reactions" and `xmpp.md` |
| `Termin` / `Ort` | Events and locations |
| `Lied` | Songs in the repertoire |
| `Konzert` | Ordered song list for a specific event (links `Lied` ↔ `Termin`) |
| `Zusage` | Per-member attendance response to an event |
| `Abstimmung` | Voting records |
| `TabellenPreferenzen` | Per-user table column visibility preferences |
| `Auftrittsabo` | Subscriber of the public gig-reminder list — **not** a member, no FK to `User`. Carries the Art. 7(1) evidence: `bestaetigt_am`, `bestaetigt_ip` and a snapshot of the consent wording. Deliberately has **no** `bestaetigt` flag (`bestaetigt` is a property over `bestaetigt_am`; filter with `bestaetigt_am__isnull`), no sign-up IP and no stored unsubscribe token |
| `ErinnerungVersand` | One marker per `(termin, wochen)`; the `UniqueConstraint` is the only protection against double sending |

### File management

Uses `django-filer`. Folder IDs are hard-coded constants in `settings.py` (e.g. `FOLDER_AVATARE = 1`, `FOLDER_MUSIK = 5`). The `import_files` management command imports avatars from the `Avatare/` directory into filer on first setup. `intern` overrides the filer-built-in `import_files` command (`intern/management/commands/import_files.py`) to set `_migrating.active = True` during the import, suppressing per-file index/thumbnail threads — otherwise importing a large directory would exhaust MySQL's connection limit. Indexing and thumbnailing are handled by the subsequent batch jobs instead.

`Avatare/` also holds the superseded pictures as `<legacy_id>_<md5-prefix>.jpg`. `import_avatars`
in `0003_import.py` hangs those off the member's current avatar as `DateiVersion` rows
(see "Files as links, and file versions"): candidates whose `sha1` equals the current
picture's are dropped (the legacy system stored the running revision under its hash name
too), the rest are ordered by **file mtime** — the name carries no chronology — and get
that mtime as `datum` (written after the fact, `datum` is `auto_now_add`). Their `File`
rows are then removed with a *queryset* `delete()`, which bypasses `File.delete()` and so
leaves the blob in place; this has to happen before the `owner is None` sweep, which would
take the blobs with it. Versions of members who were not imported fall to that sweep.

`index_files` and `thumbnail_files` run as background jobs after a fresh install in `migrate.sh`, building the search index and pre-generating thumbnails for all files. They are intentionally absent from `start.sh` (existing DB) — files are already indexed there. Files uploaded through the app are indexed and thumbnailed immediately via a `post_save` signal on `filer.File` (`on_filer_file_saved` in `signals.py`): a daemon thread calls `index_file()` and pre-generates all three thumbnail sizes so the upload response is not delayed. A semaphore caps concurrent thumbnail threads at 4 to prevent MySQL connection exhaustion; each thread closes its DB connection when done. The signal is suppressed (`_migrating.active`) during management commands that bulk-import files; file-creating functions in `0003_import.py` also set the flag explicitly as a backstop.

### Files as links, and file versions

**A file's identity is its storage path.** Two `filer.File` rows pointing at the same
`file` path are the *same file in two folders* — folders work like tags (one invoice under
Haus, Versicherung and Finanzamt). This is filer's own semantics: `File.delete()` drops the
blob only when no other row references that path. Every operation that changes a file's
path or name therefore has to carry all its rows along, which is what the helpers in
`views/files.py` are for — use them instead of touching `File.file`/`name` directly:

| Helper | Purpose |
|---|---|
| `verknuepfte_dateien(f, inklusive_selbst=True)` | all rows sharing `f`'s blob |
| `datei_umbenennen(f, name)` | rename everywhere — one file, one name |
| `version_anlegen(f, autor)` | archive the current revision before it is replaced |
| `geschwister_nachziehen(alter_pfad, quelle)` | point all rows at the new blob, move the version chain over |
| `versionen_loeschen(f)` | drop the archived blobs (when the last occurrence goes) |

**Overwriting** an upload with the same name in the same folder (`upload` in
`views/files.py`) keeps the `File` PK — so `Lied`/`Artikel`/`Forum` references survive —
archives the old revision as a `DateiVersion` and moves every linked row onto the new blob.
The update thus appears in *all* folders the file sits in, and nothing is deleted. The
search index follows by itself (`ensure_indexed` spots a changed `file_size`); the sibling
rows' `DateiIndex` entries are dropped so a same-size replacement is re-indexed too.

**`DateiVersion`** (`models.py`) records the path and metadata of a superseded revision;
the blob itself simply stays where it is. `aktuell` holds the path of the *live* revision
and chains the history — it is rewritten whenever the file moves to a new blob.
`/intern/datei/<pk>/` (`datei_view`, `datei.html`) shows the places a file is linked into
(filtered by `visible_folder_ids` — never reveal folders the member cannot see) plus its
version list; `datei_restore` makes an old revision current again, mirroring the overwrite
path. Reached from the `#id` badge in the folder listing. `cleanup_dateiversionen`
(command defaults `--keep 10 --days 730`; `start.sh` calls it with `--keep 25 --days 36500`
so the imported avatar history below survives) prunes old revisions, blobs included.

### Avatars are write-protected against other members

The `Avatare` folder has no `FolderPermission` rows, so by the rule in `folder_access.py`
every logged-in member has **write** access to it. Without a second check that means anyone
could overwrite, rename or `datei_restore` someone else's profile picture — and the imported
avatar history reaches back to 2012. Folder permissions cannot fix this: restricting the
folder would also block the self-service upload in `mitglied_edit`, which goes through
`upload()` and is checked against `folder_access()`.

`intern/avatar_access.py` is therefore a second access axis, orthogonal to folder
permissions:

- `avatar_mitglied(f)` — the member whose profile picture `f` is, resolved via the
  **`User.avatar` FK, not the `<id>.jpg` naming convention**, and across *all* linked rows
  (`verknuepfte_dateien`): a sibling row in another folder shares the blob and the version
  chain, so acting on it would swap the avatar just the same.
- `darf_avatar_aendern(user, f)` — `False` when `f` is another member's avatar. Holders of
  `intern.change_user` (the permission `mitglied_edit` already requires for foreign
  profiles) and superusers always pass. A file in `Avatare` with no resolvable owner (a
  leftover `<id>.jpg` of a member who has since cleared their avatar) is administration-only.
  Everything that is not an avatar returns `True` — normal files are unaffected.

**Every write path on files must call `darf_avatar_aendern()`.** Current call sites:
`datei_restore` and `upload` (overwrite branch — checked *before* `version_anlegen`, plus
the `rename_to`/`avatar_user_id` parameters, checked before the `File` row is created so a
rejection leaves no orphan) in `views/files.py`; `folder_rename`, `folder_move` and
`folder_delete` in `views/folders.py`. `folder_link`/`folder_duplicate` need no guard — they
do not change the avatar, and reading is open anyway.

`datei_view` passes `darf_wiederherstellen` (= `darf_schreiben` **and**
`darf_avatar_aendern`) to `datei.html`, which hides only the restore button. The version
list itself stays visible to everyone — a deliberate choice, not an oversight.

A version blob has **no `File` row** — that is the whole point, and it makes the blob an
orphan by filer's reckoning. Never run `filer_check --delete-orphans` on this project: it
walks `filer_public/` and deletes every blob without a matching row, i.e. the entire
version history. `migrate.sh` therefore only runs `thumbnail_files`.

Every row of the version table carries a preview (`_vorschau()` in `views/files.py`,
96×96 crop, `.v-vorschau` in `intern.css`); versions are addressed by path, which
`get_thumbnailer()` takes as readily as a `FieldFile`. Because a bare path carries none of
filer's storage config, those thumbnails land *next to the source blob* inside
`filer_public/` instead of under `filer_public_thumbnails/` — harmless, and
`versionen_loeschen()` / `cleanup_dateiversionen` already clean them up via
`get_thumbnailer(v.pfad).delete_thumbnails()`. They are one more reason not to run
`--delete-orphans`. Files with no usable preview (audio, spreadsheets) simply get an empty
cell; `thumbnail_files` never pre-generates any of this, so the first view of a detail page
builds them.

### Retention: what the cleanup jobs actually delete

Two scheduled jobs enforce retention, both started in the background by `start.sh`
(**not** by `migrate.sh` — that path wipes the DB anyway):

| Job | Deletes | Never touches |
|---|---|---|
| `cleanup_changelog` | `ChangeLog` rows older than 3 years (`timestamp__lt`), a plain queryset `delete()`. Backs the §10 promise in `datenschutz.html` | Any file, any content — only the audit trail |
| `cleanup_dateiversionen` | `DateiVersion` rows **plus** the blob at `v.pfad` via `storage.delete()` and the thumbnails at that path via `get_thumbnailer(v.pfad).delete_thumbnails()` | Live files: a `DateiVersion` blob has no `filer.File` row by construction, so nothing a member can see in a folder is ever a candidate |

`cleanup_dateiversionen` selects by two independent rules, unioned (`_veraltet`):
`datum__lt=now-days` **or** everything past the newest `--keep` per `aktuell` group
(`Meta.ordering = ["-nummer"]`, so `[keep:]` is the oldest tail). A row hit by either rule
goes. `aktuell` is the path of the *live* revision, so grouping by it is grouping by file.

**The defaults are not what runs.** `start.sh` calls it with `--keep 25 --days 36500`
(≈100 years), which switches the age rule off entirely: in production only the count rule
bites, i.e. each file keeps its newest 25 revisions forever. That is deliberate — the avatar
history imported from the legacy system (2012 ff., see `import_avatars`) would otherwise
vanish on the next server start, since those `DateiVersion` rows carry the original file
mtime as `datum`. Consequence to keep in mind: **there is currently no time-based deletion
of superseded file revisions in production.** A revision only disappears when 25 newer ones
exist, when the last `filer.File` occurrence is deleted (`_datei_loeschen` →
`versionen_loeschen`), or on an explicit erasure request. If a real time limit is ever
wanted, the imported avatar versions have to be exempted first — a blanket `--days` would
take them with it.

Not covered by either job, and worth knowing when answering an Art. 17 request: **deleting a
file removes one occurrence, not the blob** — the blob survives as long as another `File` row
points at the same path (see "Files as links, and file versions"). Erasure therefore means
deleting *every* linked row, which is exactly what `datei_verwendungen` shows in the
confirmation dialog.

Server logs are the third retention item in §10 (90 days), but they are not this codebase's
job: nginx logs to stdout (`nginx.conf`) and Django's `LOGGING` uses a `StreamHandler`, so
both land in journald/`podman logs` and their rotation is a host-side setting.

### Breaking references: warn before deleting or renaming

Two kinds of references point at a file, and they break differently:

- **Wiki links** (`[[Datei:name.pdf]]`) address a file by **name**
  (`replacements.internal_links`). They break on **rename**, and on **delete** only when
  the *last* row goes — while another folder still links the file, the name resolves.
  Note `internal_links` must use `filter().first()`, not `get()`: a file linked into
  several folders has several rows, and `get()` would report a live file as broken.
- **Everything else** — `Lied` (original/aufnahme/pdf/noten), `Forum.bild`, `User.avatar`
  and `Konfiguration` keys ending in `_FILE_ID` (Satzung, Beitragsordnung — linked from the
  public join form) — hangs off the **PK**. Those break when that row is deleted, even if
  the file survives elsewhere, and are unaffected by a rename.

`intern/verwendung.py` (`datei_verwendungen(dateien, user, beim_loeschen=True)`) collects
both, honouring that distinction; `Artikel.aktuelle_datei_verweise()` maps file name →
articles over each article's newest version only. Article names the user may not read
(`_artikel_access`) are counted, not named. The endpoint `datei_verwendung`
(`datei/verwendung/`) feeds the confirmation dialogs in `intern.js`
(`verwendungenAbfragen` / `verwendungsDialog`, a native `<dialog>`), which the folder
browser opens before deleting and before renaming. The file detail page shows the same
list under „Verwendet in".

On rename the dialog offers **„Links mitziehen"**: `folder_rename` with
`links_mitziehen=1` calls `_wiki_links_umschreiben`, which writes a **new article version**
per affected article (articles are immutable versions, same path as `article_edit`) with
the comment „Dateiname geändert: alt → neu". Articles the user may not edit are skipped and
reported back in `links_uebersprungen`.

**Copy vs. duplicate:** `folder_link` (button „Verknüpfen") adds a row sharing the blob —
the tag case above. `folder_duplicate` („Duplizieren") copies the blob, giving an
independent file. Both share `_copy_action` / `_copy_folder_deep(…, blob_kopieren)` in
`views/folders.py`. Deleting goes through `_datei_loeschen`, which removes one occurrence
and only cleans up versions when it was the last one — pass it a **freshly loaded**
instance, a stale one would have filer delete a blob that is still in use.

**Folder permissions:** access is governed by `FolderPermission(folder, group)` rows —
`folder_access()` in `intern/folder_access.py` treats a folder *without* rows as open for
read/write. Any code that creates a folder must therefore set rows explicitly, or the new
folder is world-readable. `folder_create` copies the parent's rows; `_copy_folder_deep`
(used by both `folder_link` and `folder_duplicate`)
gives each copied folder its source folder's own rows and, if the source was unrestricted,
the rows of its new parent (`_perm_specs` / `_apply_perm_specs`) — otherwise copying a
protected folder into an open one would expose its contents.

### External integrations

**XMPP/ejabberd** (active when `EJABBERD_HOST` + `EJABBERD_BOT_JID` are set): Bidirectional bridge between Forum MUC rooms and ejabberd. Messages sync in both directions. Uses REST API for admin operations and a long-running slixmpp bot for message relay.

See `xmpp.md` for detailed implementation notes.

### Frontend design system (`intern/static/intern/css/intern.css`)

All colors use CSS custom properties defined in `:root` (light mode). Dark mode is a `[data-theme="dark"]` block that overrides all color tokens. Theme is toggled via a button in the sidebar footer; persisted to `localStorage`; falls back to `prefers-color-scheme`.

When adding new colors, always use CSS variables and add dark-mode values to `[data-theme="dark"]`. Avoid hardcoded hex colors in component styles.

**Status ("Ampel") colours** — the green/yellow/red used by the attendance badges
(`.att-count-*`, `.att-inline-*`) and the Zusage widgets (`.zusage-state-*`,
`.zusage-btn-*`) come from one token family: `--status-{success,warning,danger}-{bg,text,border,solid}`.
`bg`/`text`/`border` are the soft surface, `solid` the strong fill used on hover/active;
the dark-mode block redefines the first three, so those components need **no**
`[data-theme="dark"]` rules of their own — only the neutral "keine Angabe" state does.
Destructive buttons use `--error-solid` / `--error-solid-hover`; do **not** reach for
`--error-bg` there, that is a pale surface colour and carries no white text.

**Theme boot script.** The inline `<script>` that sets `data-theme` before paint lives in
exactly one place: `intern/templates/_theme_boot.html`. Every standalone page includes it
right after its `intern.css` link and before any visible markup — `base.html`,
`dialog.html`, `mitglied_public_base.html`, `datenschutz.html` and the five error pages.
Put it anywhere later and the flash of the wrong theme comes back. The script only
**reads** `localStorage["theme"]`, falling back to `prefers-color-scheme`; it never writes.

Writing is the toggle's job alone (`initTheme` in `intern.js`, `apply(theme, persist)`):
the initial call passes `persist = false`, only a click persists. That distinction matters
— persisting on load would freeze whatever the system happened to prefer on the first
visit, and a later OS switch would have no effect. While nothing is stored, a
`prefers-color-scheme` change listener follows the system live.

**Auth pages** (`dialog.html` → `login.html`, `register.html`, `register_success.html`,
`reset_confirm.html`) are themed like everything else: they load `intern.css`, carry
`class="join-page"` on `<html>`/`<body>` and reuse the `.join-wrap`/`.join-card`/
`.join-header` shell of the public join pages. `login-style.css` loads *after* it and holds
only what `intern.css` does not cover (narrower card, the `<h1>` that sits outside
`.join-header`, full-width submit button, `helptext` sizing for `{{ form.as_div }}`) —
tokens only, no hex values. Form fields, labels, buttons, error boxes (`.error`,
`ul.errorlist`) and the password-strength meter all come from `intern.css`.

The only page deliberately left light-only is the public homepage — see below.

Map pages use Leaflet, and everything they share lives in
`intern/static/intern/js/osm-map.js`, loaded once in `base.html` right after Leaflet:

- It patches `L.TileLayer.prototype.createTile` to set `referrerPolicy = "origin"` —
  OpenStreetMap's tile servers reject requests without a `Referer` header. Per-page
  map code must not re-add this patch.
- `window.CantorMap` holds the pieces every map needs: `tiles(map, opts)` (the
  `/tiles/…` layer plus attribution — never call `L.tileLayer` directly, or a server
  change misses one map), `pin("ort"|"mitglied")` (the `.karte-pin` divIcons, colour
  and SVG defined once), `esc(s)`, and `init(el)`/`initAll()`.
- **Detail-page maps are declarative.** `{% include "_leaflet_map.html" with lat=… lng=…
  popup=… %}` renders only a `[data-osm-map]` container; `initAll()` builds the map from
  its data attributes on load. Parameters: `lat`, `lng`, `zoom` (default 15), `popup`
  (first line), `popup_ort` (an `Ort` whose address is appended as further lines), `pin`,
  `map_id`, `hoehe`. Popup text travels as plain text with `&#10;` line breaks and is
  escaped in JS — no `escapejs` in a template, no HTML from the DB. Used by
  `ort_detail.html`, `termin.html` and `mitglied.html`.
- `karte.html` keeps its own init (layer groups, live locations, search) but takes the
  tile layer and both pin icons from `CantorMap`.

### Public homepage (`templates/index.html`, `intern/static/intern/css/main.css`)

The public landing page does **not** extend `base.html` and does **not** use
`intern.css` — it is a standalone one-pager with its own stylesheet (`main.css`, light
mode only, own token block in `:root`). Structure: fixed header over a full-bleed photo
hero (transparent at the top, `.is-solid` white after 60 px of scroll — set by a small
inline script at the end of the page), then Über uns (cards), Konzerte (date/title/place
rows), Galerie (single wide photo band) and a dark Kontakt section plus footer.

It is the one page that stays **light only** on purpose, and therefore the one page that
does *not* include `_theme_boot.html`: the photo hero, the white `.is-solid` header state
and the already-dark Kontakt section are a composed look, not a token swap. Do not bolt a
`[data-theme="dark"]` block onto `main.css` without redesigning those three.

Logo usage: the header shows the round mark
(`intern/images/JG-Frankfurt-wG-color.svg`) over the photo and swaps to the black
wordmark (`intern/brand/JG-Frankfurt.svg`) once the header turns white — below 460 px the
mark stays. Hero headline and footer use the light wordmark
(`intern/brand/JG-Frankfurt-transparent.svg`) as an image inside the `<h1>`; its font
(Showcard Gothic) exists only as outlines in the SVG, so the lettering can only be used as
an asset, never as a webfont. `JG-Frankfurt-wG-color.svg` previously existed **only** in
the gitignored `static/` (STATIC_ROOT) — it now has a tracked source copy in
`intern/static/intern/images/`, which the favicon redirect in `config/urls.py` also relies
on.

All copy comes from `Konfiguration` (`HOMEPAGE_UEBER_UNS`, `HOMEPAGE_AUFNAHME`,
`VEREINSNAME*`, `VEREINSADRESSE`, `DEFAULT_FROM_EMAIL`) — `home()` in `views/auth.py`
additionally passes `homepage_intro`, the first sentence of `HOMEPAGE_UEBER_UNS`, used as
the hero subline. The hero and gallery images are pre-scaled derivatives of the choir
photo in `intern/static/intern/img/` (`chor-{800,1400,2000}.jpg` for the hero `srcset`,
`chor-band-{1100,1800}.jpg` for the gallery band); regenerate them from the original with
ImageMagick when the photo changes. Assets are referenced via `{% static %}`, so
`collectstatic` covers them.

### Known technical debt

Tracked in separate files: general code/UX debt (branding, risk-ranked items) in
`technical-debt.md`; privacy-policy compliance items in `datenschutz.md`.

### Logging

`settings.py` defines a `LOGGING` dict. The `intern` logger hierarchy is set to `INFO`; root and `django` loggers to `WARNING`. All output goes to stdout via `StreamHandler` (`stream: ext://sys.stdout`), which appears in `podman logs` and `journalctl`. Using stdout ensures systemd assigns the correct `PRIORITY` based on the Python log level, so INFO/WARNING entries are not colored red in journalctl. Custom loggers use `logging.getLogger(__name__)` — they all fall under `intern.*` and are therefore visible.

### Notable utilities (`intern/`)

- `pdf.py` — `new_letterhead_pdf(title, subtitle, vereinsname, vereinsname_lang, vereinsadresse)` returns `(buf, canvas, content_y)`; draws branded letterhead (logo from `intern/brand/JG-Frankfurt-transparent.png`, thin `#c14468` accent lines) and footer. Helper functions `draw_section`, `draw_field`, `draw_checkbox`, `draw_signature` build the content area. Used by `_save_antrag_pdf` and `_save_bestaetigung_pdf` in `views/auth.py`.
- `mail.py` — `send_branded_mail(subject, to, template, context, text_body=None, attachments=None, headers=None)`: renders an HTML template into a branded mail with the embedded logo (`cid:logo`) and a plain-text fallback (both get the `MAIL_FOOTER` line); resolves the sender via `get_from_email()`; never raises and returns `True`/`False` so callers can tell whether the message reached the backend. `attachments` is an optional list of `(filename, bytes, content_type)` tuples — when present the outer MIME type is `multipart/mixed`. `headers` adds extra MIME headers (used for `List-Unsubscribe`). The function builds the MIME message itself and hands it to Django through a `_Msg` subclass whose `message()` is overridden; that override must apply `_SMTP_POLICY` (compat32 with CRLF line endings), otherwise `as_bytes()` emits bare LF and strict SMTP servers reject the whole mail as one over-long line (RFC 5321). Callers normally use the wrapper `send_config_mail()`, which renders a `MAIL_*` config text (see "Automated e-mails"); `build_mail_placeholders()` builds the placeholder dict.
- `mail_markup.py` — `render_mail_markup(raw, placeholders, link)` → `(html, plain)`: wiki-style markup renderer for mail texts, including the `{button:Label}` directive.
- `replacements.py` — wiki-like markup processor (lists, code blocks, `[[Datei:...]]` file links)
- `php_pbkdf2_hasher.py` — legacy password hasher for migrating users from a prior PHP system; listed in `PASSWORD_HASHERS` in settings
- `fuzzy.py` — fuzzy song title matching used in article references
- `context_processors.py` — injects global template context (`VERSION`, `upload_max_mb`, notify poll/dismiss intervals)
- `app_settings.py` — runtime config helpers (`get_config`, `get_config_bool`, `get_config_int`, `get_from_email`, `get_map_center`, `get_document_url`, `get_base_url`) backed by the `Konfiguration` table; see "Runtime configuration" below. `get_document_url(key)` resolves a Filer file ID stored in `Konfiguration` to a public HMAC token URL (`/intern/datei/<pk>/<token>/<filename>`), returning `"#"` when unconfigured. `get_base_url(override=None, fallback="")` is the one way to build the portal's base URL outside a request (mails, management commands): `VEREINS_URL`, trimmed of any trailing slash. **Its default `fallback` is deliberately empty** — for mail an unset `VEREINS_URL` is an abort condition (a relative unsubscribe link is a dead one), and a silent `http://localhost` would hide that. Only the two commands that merely print a URL pass one.

**External integrations:**
- `ejabberd.py` — REST API client for ejabberd admin API (room config, affiliations, invitations, vCards). Message sending is done by the bot over its live session, not here.

**Management commands:**
- `ejabberd_bot` — slixmpp XMPP bot for MUC message forwarding
- `ejabberd_admin` — operator CLI for all ejabberd admin ops; `ejabberd_admin sync` runs the startup user/room sync (was the separate `ejabberd_sync` command, now merged)

### Migration quirks

`migrate.sh` / `start.sh` delete `intern/migrations/0002_add_filer.py` and temporarily move `0003_import.py` out before regenerating migrations. This is intentional — `0002` is always regenerated fresh and `0003` depends on it being newly created. Do not check `0002_add_filer.py` into git.

### Database

SQLite in development (`db.sqlite3`, excluded from git). MySQL-compatible for production via `pymysql`.

**Note on DB reset:** The full DB wipe in `migrate.sh` exists only during the current **test phase**. After the final migration it will be removed — the test system will simply receive a copy of the prod DB, and prod and test will have separate start strategies (no more destructive reset on start). Until then: every `migrate.sh` run discards all data.

### Cache

`CACHES` uses `DatabaseCache` (table `cache_table`), and it carries exactly one thing: the
two IP rate limits — password reset (`views/auth.py`) and mailing-list sign-up
(`views/auftritte.py`). Nothing else in the project uses the Django cache; the
`_nick_jid_cache` in `ejabberd_bot.py` is a plain dict.

The backend has to be shared, not per-process: with the default LocMemCache each of the
three gunicorn workers counts on its own, so the effective limit is 3× the configured
value and which worker a request lands on is luck. `OPTIONS.MAX_ENTRIES` is raised to
10000 for the same reason the limits exist — Django's default of 300 makes
`DatabaseCache` cull a third of all rows on overflow (`CULL_FREQUENCY` 3), which an
attacker could use to evict the very counters that throttle them.

The table is created by `python manage.py createcachetable` in **both** `start.sh` and
`migrate.sh`. That is plain DDL, **not** a migration, so it does not collide with the rule
that all model changes go into the regenerated `0002`. It is idempotent. If the table is
missing the throttles fail loudly rather than silently switching themselves off — that is
deliberate, hence no `try/except` around the cache calls.

Unaffected by all of this: the DB-backed cooldown on `Auftrittsabo.optin_gesendet_am`,
which is the brake that actually prevents mail-bombing a foreign address.

### Environment variables

Only bootstrap settings (needed before the DB is available) are real env vars:

- `DEBUG` — set to `1` for development mode
- `SECRET_KEY` — hardcoded in `settings.py` (development only; override for production)
- `DB_HOST`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_PORT` — MySQL connection (unset → SQLite)

### Runtime configuration (`Konfiguration` table)

Operational settings are stored in the `intern.Konfiguration` key/value table, not
env vars, so they can be changed at runtime (admin or `/intern/konfiguration/`)
without a redeploy. **Read them via `intern.app_settings` helpers** (`get_config`,
`get_config_bool`, `get_config_int`) — never `os.environ`/`settings` for these —
and never call the helpers at settings/import time (the DB may not be ready).

Environment variables take priority over DB values in `get_config()`, **and are also
persisted to the DB during `post_migrate`** (`_seed_config` in `intern/apps.py` calls
`update_or_create` for every key that has a matching ENV var). This means a container
started with `-e EJABBERD_BOT_JID=...` writes the value into the DB — on subsequent
starts the ENV var can be dropped and the DB value is used. Use
`is_ejabberd_configured()` (not a flag) to check whether the XMPP integration is active.

Defaults are seeded on `post_migrate` from `_CONFIG_DEFAULTS` in `intern/apps.py`;
**add new keys there** (with a German `description`) so fresh installs get them.
Choir-specific initial values (e.g. `VEREINSNAME`, `VEREINSNAME_KURZ`, `HOMEPAGE_UEBER_UNS`,
`HOMEPAGE_AUFNAHME`) live in `seed_konfiguration` in `intern/migrations/0003_import.py` — those
keys carry an empty-string default in `apps.py` and get their real content only via the data
migration, so the codebase stays deployable for other organisations without pre-filled choir text.
The full key catalog and the mail-placeholder reference (`format_config_mail` /
`format_config_text`, the standard `{vorname}`/`{vereinsname}`/… placeholders, and the
"to add a new automated email" recipe) live in `configuration.md`.

`VEREINSNAME` is exposed via `get_vereinsname()` in `app_settings.py`, injected into
every template context by `config/context_processors.py` (`{{ vereinsname }}`), and
into every email render in `mail.py`.

For outgoing mail always pass `get_from_email()` as the sender (resolves
`DEFAULT_FROM_EMAIL` from the DB, falling back to `settings.DEFAULT_FROM_EMAIL`).
Frontend-facing values (`NOTIFY_POLL_MS`, `NOTIFY_DISMISS_MS`) reach JS via
`context_processors.project_meta` → `data-*` attributes on `<body>` → `notify.js`.

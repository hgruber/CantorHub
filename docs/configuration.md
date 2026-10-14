# Runtime configuration reference (`Konfiguration` keys)

How the `Konfiguration` key/value table works — env priority, seeding via `post_migrate`,
reading via `intern.app_settings` helpers — is documented in `architecture.md` ("Runtime
configuration"). This file is the **full key catalog** and the **mail-placeholder reference**.

## Current keys

Defaults are seeded on `post_migrate` from `_CONFIG_DEFAULTS` in `intern/apps.py`;
**add new keys there** (with a German `description`) so fresh installs get them.

- `EJABBERD_API_URL`, `EJABBERD_HOST`, `EJABBERD_MUC_SERVICE`, `EJABBERD_BOT_JID`,
  `EJABBERD_BOT_PASSWORD`, `EJABBERD_BOT_PORT`
- `EJABBERD_API_TIMEOUT` (timeout of ejabberd REST API calls in seconds, default `10`)
- `EJABBERD_BOT_RESCAN_SECONDS` (interval at which the bot rescans for new forums, default `60`)
- `EJABBERD_BOT_RELAY_SECONDS` (interval at which the bot relays forum→MUC and reactions, default `3`)
- `ICAL_SECRET`
- the `EMAIL_*` set, `DEFAULT_FROM_EMAIL`
- `UPLOAD_MAX_MB` (max upload size in MB, default `50`)
- `MAP_CENTER_ID` (id of the `Ort` used as the map centre)
- `MAP_DEFAULT_ZOOM` (default zoom of the overview map, default `12`)
- `MAP_CENTER_LAT` / `MAP_CENTER_LNG` (fallback map centre when `MAP_CENTER_ID` has no
  coordinates or does not exist; defaults `50.1109` / `8.6821`)
- `OSM_TILE_URL` (base URL of the tile server, default `https://tile.openstreetmap.org`; the
  proxy appends `/{z}/{x}/{y}.png`)
- `OSM_NOMINATIM_URL` (base URL of the Nominatim geocoder, default
  `https://nominatim.openstreetmap.org`; the proxy appends `/search`)
- `FILE_PREFIX` (prefix for the alternative filenames in the song archive, default `JG`;
  both `JG-Titel` and `JG - Titel` spellings are derived from it)
- `PWRESET_MAX_PER_HOUR` (max password-reset requests per IP per hour, default `5`)
- `CARDDAV_AKTIV` (`1`/`0`, **default `0`**) — master switch of the read-only CardDAV address
  book. While off, every CardDAV URL answers `404`, not `401`: the service simply does not
  exist. Turn it on only after the members have been informed (privacy policy, section
  „Sichtbarkeit Deiner Daten im Portal")
- `CARDDAV_ADRESSBUCH_NAME` (display name of the collection on the device; empty →
  `"<VEREINSNAME_LANG> – Mitglieder"`)
- `CARDDAV_ORGANISATION` (value of the vCard `ORG` property; empty → `VEREINSNAME_LANG`)
- `CARDDAV_FOTO` (`1`/`0`) — embed the 200×200 avatar thumbnail as `PHOTO`. Roughly 13 kB per
  card; switch off if the sync volume matters more than the pictures
- `CARDDAV_AUTH_TTL` (seconds a successful password check is cached, default `300`). Skips
  **only** the PBKDF2 call — measured 620 ms cold vs. 10 ms warm — never an authorisation
  decision: `is_active` and the stored password hash are re-checked on every hit, so a password
  change or a deactivation takes effect on the very next request
- `CARDDAV_MAX_FEHLVERSUCHE_PRO_STUNDE` (failed CardDAV logins per IP per hour, default `30`).
  Deliberately generous — a member with a stale password on two devices behind one NAT must not
  lock out the whole household — and answers `401`, not `429`, so the client retries later
  instead of giving up
- `CALDAV_AKTIV` (`1`/`0`, **default `0`**) — master switch of the read-only CalDAV calendar,
  behaving exactly like `CARDDAV_AKTIV` (404 while off, same privacy-policy section). The two switches
  are independent, but turning **both** on is what lets a phone find calendar *and* address
  book from the bare base URL: each service only advertises the other's home-set while that
  other one is active
- `CALDAV_KALENDER_NAME` (display name of the event calendar on the device; empty →
  `"<VEREINSNAME_LANG> – Termine"`)
- `CALDAV_GEBURTSTAGE` (`1`/`0`, default `1`) — deliver the birthdays as a second calendar.
  Contains only active members who have **not** hidden `geburtstag`; while off, the collection
  does not exist at all (404), it is not merely empty
- `CALDAV_GEBURTSTAGE_NAME` (empty → `"<VEREINSNAME_LANG> – Geburtstage"`)
- `CALDAV_TAGE_RUECKWIRKEND` (how many days of past events are delivered, default `365`). There
  is no limit towards the future — a calendar that stops in a year would be a surprise
- `CALDAV_STANDARDDAUER_STUNDEN` (default duration in hours of an event without an end time,
  default `2`; applies to the CalDAV time-range filter, the CalDAV serialisation and the
  public iCal feed alike)
- `ICAL_TAGE_RUECKWIRKEND` (how many days of past events the public iCal feed delivers, default
  `180`; the CalDAV mirror of `CALDAV_TAGE_RUECKWIRKEND`)
- `CALDAV_AUTH_TTL`, `CALDAV_MAX_FEHLVERSUCHE_PRO_STUNDE` — the CalDAV counterparts of the two
  `CARDDAV_*` keys above, same meaning and same defaults. Note the throttle counts per service,
  so a client failing on both endpoints has two budgets
- `NOTIFY_POLL_MS`, `NOTIFY_DISMISS_MS`
- `TERMIN_BANNER_AKTIV` (1/0, default `1`; global switch for the upcoming-event banner below the
  topbar — read in `config/context_processors.py`, which leaves `banner_termin` unset while off,
  so `base.html` never includes `_termin_banner.html`. Independent of the per-member,
  per-login-dismissible state kept in `localStorage` — that dismissal only works while this key
  is on)
- `VEREINSNAME` (choir display name / tagline, default `"Join us singing the Gospel e.V."`)
- `VEREINSNAME_LANG` (formal long name with location, default `"Just Gospel! Frankfurt"` — used in email headers, page titles, join form)
- `VEREINSNAME_KURZ` (short name for compact contexts, default `"Just Gospel"` — used in sidebar, alt texts, browser title)
- `BRAND_FARBE` (accent colour, hex, default `#c14468`) — overrides the `--brand` CSS custom
  property (`intern/templates/_brand_boot.html`, included right after the `intern.css` link on
  every portal page that loads it; the public homepage uses the tag `{% markenfarbe %}` after its
  `main.css`); `--brand-dark`/`--brand-light`/`--brand-ring` are derived
  from `--brand` via `color-mix()` in `intern.css` and follow automatically, as do
  `--brand-dark`, `--brand-soft` and `--band` on the public homepage. Also colours mail buttons
  and links (`intern/mail_markup.py`), the mail header background (`emails/base.html`), the
  PDF letterhead rule (`intern/pdf.py`) and the CalDAV `ICAL:calendar-color` handed to devices
  (`intern/caldav/daten.py:farbe()`). Edited on the configuration page via the generic
  text-plus-native-picker component (`feldtyp` `"color"`, see `docs/frontend.md`). **It has to
  carry white text**: `--brand` is the background of primary buttons and of the homepage's
  Kontakt band, all of them white-on-brand. A very pale colour breaks those long before it looks
  wrong anywhere else. The `JG-Frankfurt*.svg` logos keep their own hardcoded rose either way
  (see `docs/branding.md`)
- `VEREINSADRESSE` (ladungsfähige Kontaktanschrift of the Verein, shown in the privacy policy's „Verantwortliche" section; multi-line, empty → only board member names are listed, no addresses)
- `HOMEPAGE_UEBER_UNS` (body text for the "Über uns" card on the public homepage; multi-line allowed)
- `HOMEPAGE_AUFNAHME` (body text for the "Wir suchen" card on the public homepage; multi-line allowed; hidden when empty)
- `MAILINGLISTE_WOCHEN` (lead times of the public gig reminders in weeks, comma-separated; default `4,1`. Parsed by `parse_wochen()` in `intern/mailingliste.py`, which drops anything unparsable — a hand-edited nonsense value must not kill the daemon)
- `MAILINGLISTE_VERSANDZEIT` (`HH:MM`; **fallback only**, used when a `Termin` has no time of day (00:00). Otherwise the reminder goes out at the event's own time, hence on the same weekday)
- `MAILINGLISTE_INTERVALL_MIN` (poll interval of the reminder daemon, re-read every iteration)
- `MAILINGLISTE_OPTIN_TAGE` (validity of the confirmation link **and** the deletion deadline for unconfirmed sign-ups — one number, two values would drift apart. Clamped to ≥ 1: a `0` would invalidate every link instantly)
- `MAILINGLISTE_TEXT` (intro text of the public form at `/auftritte/`; plain text, rendered with `linebreaksbr` — **not** through `mail_markup`, whose inline hex colors would break dark mode)
- `MAILINGLISTE_EINWILLIGUNG` (label of the consent checkbox; stored as a snapshot on every sign-up, see `Auftrittsabo.einwilligungstext`)
- `MAIL_MAILINGLISTE_OPTIN` (double-opt-in confirmation mail; `{link}` = the confirmation URL)
- `MAIL_MAILINGLISTE_WILLKOMMEN` (mail after a confirmed sign-up)
- `MAIL_MAILINGLISTE_BEREITS_ANGEMELDET` (reply when an already-confirmed address signs up again)
- `MAIL_MAILINGLISTE_ERINNERUNG` (the reminder itself; placeholders below)
- `MAIL_ANTRAG` (applicant confirmation email)
- `MAIL_ANTRAG_ADMIN` (admin notification on new application; `{vorname}`, `{nachname}`, `{email}`, `{link}`, `{hinweise}`)
- `MAIL_ANTRAG_ADMIN_MINDERJAEHRIG` / `MAIL_ANTRAG_ADMIN_FOERDER` (conditional notes appended to the admin mail; rendered at `{hinweise}`)
- `MAIL_BEI_AKTIVIERUNG` (`1`/`0` — set to `0` to suppress welcome/reactivation mails during testing; a switch, not a text)
- `MAIL_BESTAETIGUNG` (re-confirmation invitation email)
- `MAIL_BESTAETIGUNG_BESTAETIGT` (quittance mail after member confirms data)
- `MAIL_EINLADUNG` (invite email sent to an email address before registration; no user object → only `{link}` and the `{vereinsname*}` placeholders)
- `MAIL_FOOTER` (footer line of **every** email; empty → no footer)
- `MAIL_NEUES_PASSWORT` (password reset email)
- `MAIL_REAKTIVIERT` (email on reactivation of a previously active member; `{link}` = login URL, empty if `VEREINS_URL` not set → the button is dropped)
- `MAIL_RUNDMAIL` (frame around the member round mail; `{text}` = the text entered in the form)
- `MAIL_WILLKOMMEN` (welcome email on first activation; `{link}` = login URL, empty if `VEREINS_URL` not set → the button is dropped)
- `SATZUNG_FILE_ID` (Filer file ID of the current Satzung PDF; empty → `href="#"` in public forms)
- `BEITRAGSORDNUNG_FILE_ID` (Filer file ID of the current Beitragsordnung PDF; same rules as `SATZUNG_FILE_ID`)
- `ANTRAG_EMAIL` (where membership applications are sent; empty → all active users with `intern.change_user`)
- `MITGLIED_EINLADUNG_TAGE` (validity of the signed invite link to the join form, in days; default `7`)
- `MITGLIED_BESTAETIGUNG_TAGE` (validity of the re-confirmation link, in days; default `30`)
- `VEREINS_URL` (base URL of the portal, e.g. `https://portal.example.com`; supplies `{link}` in
  the activation mails **and** `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` — one portal has one
  address, and maintaining it twice only means one of the two is eventually wrong. On the very
  first start it has to arrive as an environment variable, because `settings.py` is loaded
  before there is a database; `InternConfig.ready()` reads it from here afterwards. Empty means
  only `localhost` is accepted and every other request gets "Bad Request (400)" — the startup
  log says so)
- `ZEITZONE` (IANA time zone of the portal, default `Europe/Berlin`; a `select` of curated
  European + common world zones. Drives the iCal/CalDAV UTC conversion via
  `intern.caldav.daten.zeitzone()` and is synced into `settings.TIME_ZONE` **and the process
  time zone** (`TZ` + `time.tzset()`) at app start, so the legacy iCal feed, Django template
  formatting and `datetime.now()` all follow the same zone. CalDAV picks up a change
  immediately; the rest follows on the next process restart)
- `SPRACHE` (language of the portal, default `de-de`; a `select` of the languages Django ships
  translations for. Governs Django's own texts — admin, form errors — and the date and number
  formats. **The portal's own texts are German and are not translated**, so this is not a
  language switch for the site. Applied in `InternConfig.ready()` via `translation.activate()`,
  because the project runs without `LocaleMiddleware`; takes effect on the next restart)

### Datenschutz-Texte

Defaults are the original Just-Gospel values — overwrite on first setup.

- `HOSTING_ANBIETER_NAME` (name of the hoster in the privacy policy's „Hosting und technischer Betrieb" section; multi-line allowed)
- `HOSTING_ANBIETER_ANSCHRIFT` (address of the hoster in the same section; multi-line allowed)
- `DSB_NAME` (name of the supervisory data-protection authority in „Beschwerderecht bei der Aufsichtsbehörde"; multi-line allowed)
- `DSB_ANSCHRIFT` (address of the authority in the same section; multi-line allowed)
- `DSB_URL` (URL of the authority in the same section)

### Aufbewahrung & Bereinigung

The cleanup jobs read these as their default; each has a `--days` (or `--keep`) CLI override.

- `AENDERUNGSPROTOKOLL_AUFBEWAHRUNG_TAGE` (retention of the change log in days; default `1095` = 3 years, privacy policy section „Speicherdauer")
- `DATEIVERSION_AUFBEWAHRUNG_TAGE` (retention of superseded file revisions in days; default `730` = 2 years — a convenience feature, not an archive)
- `DATEIVERSION_AUFBEWAHRUNG_ANZAHL` (number of revisions kept per file regardless of age; default `10`)
- `FORUM_ANZEIGE_AB` (cutoff date `YYYY-MM-DD`; forum messages before it are not shown anywhere, nothing is deleted; default `2026-06-01`, an invalid value falls back to it — see `forum.md`)
- `ERINNERUNG_VERSAND_AUFBEWAHRUNG_TAGE` (retention of the `ErinnerungVersand` send markers in days; default `365`. The markers only guard against double sends, so after the event they are no longer needed)

## Completeness: what the settings page flags

`/intern/konfiguration/` carries a banner above the groups. It reports three things, all
computed in `intern/konfig_gruppen.py` and therefore DB-free and testable
(`KonfigVollstaendigkeitTest`). The first two are defects and colour the banner with the
`--warn-*` tokens; the third is not, and renders it in neutral greys
(`.kf-mangel--hinweis`):

- **empty required key** — a key that must carry a value but whose row is blank. The list of
  keys where blank is *legitimate* is the explicit exception set `OPTIONAL_LEER`; everything
  else in the catalog counts as required. A blank required key is not an error — the code
  falls back to its own default — it just means that default is in force, and for
  `VEREINSNAME` and friends that default is another choir's name.
- **missing key** — a catalog key with no row at all. Normally impossible (`_seed_config`
  creates every key on `post_migrate`); it shows up only after a row was deleted by hand, and
  the next restart re-creates it. These are named in the banner because the page has no field
  for them.
- **disabled service** — a feature that cannot run because its keys are blank. Listed in
  `DIENSTE`, today `EMAIL_HOST` (no mail at all) and `EJABBERD_HOST` + `EJABBERD_BOT_JID`
  (no forum bridge). This is deliberately **not** a defect: the same keys are in
  `OPTIONAL_LEER`, because running without mail or without XMPP is a legitimate setup. But
  the consequences are large enough — no activation, no password reset, no re-confirmation,
  no gig reminder — that an operator should not have to discover them in production. The
  conditions mirror `app_settings.is_email_configured()` and `is_ejabberd_configured()`
  exactly, including that XMPP needs *both* keys; two tests hold the two definitions
  together, and a third forbids a key from being a defect and a notice at once.

A key belongs in `OPTIONAL_LEER` when the code has a working substitute
(`CARDDAV_ADRESSBUCH_NAME` → `VEREINSNAME_LANG`) or when blank is an intended off-switch
(`EMAIL_HOST` → no mail at all, `EJABBERD_HOST` → no XMPP bridge). The set is an exception
list rather than a required list so that a **new** key counts as required by default and gets
noticed instead of staying silently blank.

After a fresh install the banner names exactly the five keys the operator has to supply:
`VEREINS_URL`, `VEREINSNAME`, `VEREINSNAME_KURZ`, `HOMEPAGE_UEBER_UNS`, `HOMEPAGE_AUFNAHME`.

The banner is **server-rendered only** — no JavaScript, no per-group or per-field markers. Its
number describes the state that was loaded, which is the state that matters: saving goes
through „Änderungen anwenden", and that reloads the page.

## Mail texts: markup and placeholders

`MAIL_*` texts carry the **complete** visible mail body — greeting, buttons, notes, closing.
Nothing but the branded frame (logo header, footer line from `MAIL_FOOTER`) comes from the
templates. `intern/mail_markup.py` renders one text into **both** MIME parts, using the same
wiki syntax as the article editor (`intern/replacements.py`):

| Markup | Result |
|---|---|
| blank line | new paragraph |
| `== Titel ==` … `======` | heading (5 levels) |
| `'''fett'''` / `''kursiv''` / `''''beides''''` | bold / italic / both |
| `* Punkt` / `# Punkt` | bullet / numbered list (nestable via `**`, `##`) |
| `% Zeile` | small grey note block |
| `@ Zeile` | highlighted note box |
| `: Zeile` | indented paragraph |
| `[https://… Name]` | named link (bare URLs are linked automatically) |
| `$Text$` | no formatting inside |
| `{button:Label}` | button linking to `{link}` |
| `{button:Label:URL}` | button linking to an explicit URL |

A button whose URL is empty renders **nothing** (no dead link). In the plain-text part a
button becomes `Label: URL`.

Placeholders via `mail.render_config_mail(key, user=…, link=…)`: `{vorname}`, `{nachname}`,
`{email}`, `{xmpp}`, `{user}` (username), `{username}` (alias), `{stimme}` (voice type written
out), `{vereinsname}`, `{vereinsname_lang}`, `{vereinsname_kurz}`, `{link}`, plus mail-specific
extras. Without a `user` only the `{vereinsname*}` set and the extras are available. Unknown
placeholders are left as-is; placeholder values are HTML-escaped.

### Auftritts-Mailingliste placeholders

The four `MAIL_MAILINGLISTE_*` texts go through `send_mailingliste_mail()`
(`intern/mailingliste.py`) rather than `send_config_mail()`, because the unsubscribe link
must not be removable by editing the text. They all get `{name}` (may be empty),
`{name_anrede}` (`" Vorname"` or empty, so `Hallo{name_anrede},` reads correctly either way),
`{email}` and `{abmelden}`. `MAIL_MAILINGLISTE_OPTIN` additionally gets `{link}` = the
confirmation URL; in the other three `{link}` falls back to the unsubscribe URL.

`MAIL_MAILINGLISTE_ERINNERUNG` additionally gets: `{titel}` (`Termin.kurz`), `{datum}`,
`{wochentag}`, `{uhrzeit}` (empty at 00:00), `{uhrzeit_text}` (`" um 20:00 Uhr"` or empty),
`{ort}`, `{ort_adresse}`, `{extern}`, `{wochen}`, `{wochen_text}` (`"vier Wochen"` / `"einer Woche"`).

There is deliberately **no `{beschreibung}`** (`Termin.lang`): `mail_markup._substitute()` runs
*before* the line parser, so substituted values are HTML-escaped but not markup-neutralised. A
multi-line `Termin.lang` containing a `{button:…:URL}` line would render as a real button in a
mail sent to the general public. `Termin.kurz` (single line, max 64) and `Ort.name` are safe.

`{extern}` is the same kind of field — multi-line, HTML — and is allowed only because
`mailingliste._ankuendigung_als_text()` flattens it to one directive-free paragraph *before* the
substitution: tags become gaps, whitespace collapsed, `{}` and `[]` removed. Neither a button nor
a named link can be smuggled in. Bare URLs survive and are auto-linked (the ticket link in an
announcement); an `<a>` link keeps only its text, the target is dropped.

**`MAIL_MAILINGLISTE_ERINNERUNG` carries an empty default on purpose.** Its text is
choir-specific, so it is seeded by `seed_konfiguration` in `migrations/0003_import.py` — the same
rule as `VEREINSNAME` and `HOMEPAGE_UEBER_UNS`, and the reason those keys have `""` in
`_CONFIG_DEFAULTS`. The key stays in the catalogue and stays required; the migration disappears
once the migration is done, and a new installation writes its own text.

**To add a new automated email:** add the key to `_CONFIG_DEFAULTS` in `apps.py` (description
mentioning the placeholders), then call `mail.send_config_mail(subject, to, key, user=…,
link=…)` — it renders the text and sends it through `emails/generic.html`. Changing an existing
default text: also list the previous text in `_LEGACY_MAIL_DEFAULTS` (`apps.py`) so untouched
installations are lifted to the new wording on the next `migrate`.

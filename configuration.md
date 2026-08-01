# Runtime configuration reference (`Konfiguration` keys)

How the `Konfiguration` key/value table works — env priority, seeding via `post_migrate`,
reading via `intern.app_settings` helpers — is documented in `CLAUDE.md` ("Runtime
configuration"). This file is the **full key catalog** and the **mail-placeholder reference**.

## Current keys

Defaults are seeded on `post_migrate` from `_CONFIG_DEFAULTS` in `intern/apps.py`;
**add new keys there** (with a German `description`) so fresh installs get them.

- `EJABBERD_API_URL`, `EJABBERD_HOST`, `EJABBERD_MUC_SERVICE`, `EJABBERD_BOT_JID`,
  `EJABBERD_BOT_PASSWORD`, `EJABBERD_BOT_PORT`
- `ICAL_SECRET`
- the `EMAIL_*` set, `DEFAULT_FROM_EMAIL`
- `UPLOAD_MAX_MB`
- `MAP_CENTER_ID`, `MAP_DEFAULT_ZOOM`
- `PWRESET_MAX_PER_HOUR`
- `NOTIFY_POLL_MS`, `NOTIFY_DISMISS_MS`
- `VEREINSNAME` (choir display name / tagline, default `"Join us singing the Gospel"`)
- `VEREINSNAME_LANG` (formal long name with location, default `"Just Gospel! Frankfurt"` — used in email headers, page titles, join form)
- `VEREINSNAME_KURZ` (short name for compact contexts, default `"Just Gospel"` — used in sidebar, alt texts, browser title)
- `VEREINSADRESSE` (ladungsfähige Kontaktanschrift of the Verein, shown in privacy-policy §1; multi-line, empty → only board member names are listed, no addresses)
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
- `VEREINS_URL` (base URL of the portal, e.g. `https://portal.example.com`; supplies `{link}` in the activation mails)

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
`{ort}`, `{ort_adresse}`, `{wochen}`, `{wochen_text}` (`"vier Wochen"` / `"einer Woche"`).

There is deliberately **no `{beschreibung}`**: `mail_markup._substitute()` runs *before* the
line parser, so substituted values are HTML-escaped but not markup-neutralised. A multi-line
`Termin.lang` containing a `{button:…:URL}` line would render as a real button in a mail sent
to the general public. `Termin.kurz` (single line, max 64) and `Ort.name` are safe.

**To add a new automated email:** add the key to `_CONFIG_DEFAULTS` in `apps.py` (description
mentioning the placeholders), then call `mail.send_config_mail(subject, to, key, user=…,
link=…)` — it renders the text and sends it through `emails/generic.html`. Changing an existing
default text: also list the previous text in `_LEGACY_MAIL_DEFAULTS` (`apps.py`) so untouched
installations are lifted to the new wording on the next `migrate`.

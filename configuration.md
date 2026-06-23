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
- `MAIL_ANTRAG` (applicant confirmation email body)
- `MAIL_ANTRAG_ADMIN` (admin notification on new application; `{vorname}`, `{nachname}`, `{email}`, `{link}`)
- `MAIL_BEI_AKTIVIERUNG` (`1`/`0` — set to `0` to suppress welcome/reactivation mails during testing)
- `MAIL_BESTAETIGUNG` (re-confirmation invitation email body)
- `MAIL_BESTAETIGUNG_BESTAETIGT` (quittance mail after member confirms data; `{vorname}`, `{vereinsname}`)
- `MAIL_EINLADUNG` (invite email sent to an email address before registration; `{link}`, `{vereinsname}`, `{vereinsname_lang}` — no user object, use `format_config_text()`)
- `MAIL_NEUES_PASSWORT` (password reset email body)
- `MAIL_REAKTIVIERT` (email on reactivation of a previously active member; `{link}` = login URL, empty string if `VEREINS_URL` not set)
- `MAIL_WILLKOMMEN` (welcome email on first activation; `{link}` = login URL, empty string if `VEREINS_URL` not set)
- `SATZUNG_FILE_ID` (Filer file ID of the current Satzung PDF; empty → `href="#"` in public forms)
- `VEREINS_URL` (base URL of the portal, e.g. `https://portal.example.com`; when set, a login button is added to activation mails; empty → no button)

## Mail placeholders

All `MAIL_*` body texts are rendered in both the HTML email body and the plain-text fallback
via `send_branded_mail()` (which passes `text_body` into the template context). Standard
placeholders via `mail.format_config_mail(key, user, ...)`: `{vorname}`, `{nachname}`,
`{email}`, `{xmpp}`, `{user}` (username), `{username}` (alias), `{stimme}` (voice type written
out), `{vereinsname}`, plus mail-specific ones like `{link}`. Unknown placeholders are left
as-is.

For mails **without** a user object (e.g. invite), use `mail.format_config_text(key, **kwargs)`
instead — only `{vereinsname}`, `{vereinsname_lang}`, and explicit kwargs are available.

**To add a new automated email:** add the key to `_CONFIG_DEFAULTS` in `apps.py`, then call
the appropriate formatter as `text_body`.

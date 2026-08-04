# Automated e-mails

**Every automated mail carries its entire visible body in a `MAIL_*` key of the `Konfiguration`
table — no sentence lives in a template.** The templates only supply the branded frame. Subjects
remain in Python. That is the rule to keep in mind before adding a mail: if you find yourself
writing prose into an HTML file, you are on the wrong path.

## Templates

There are four, and there is no per-mail template:

| Template | Role |
|---|---|
| `emails/base.html` | the frame — card, logo header, footer text from `MAIL_FOOTER` |
| `emails/generic.html` | renders `body_html`; the default for everything |
| `emails/mitglied_benachrichtigung.html` | round mail; adds the signature block via the `after_body` block |
| `emails/mailingliste.html` | gig reminders; renders the unsubscribe link structurally |

## The mails

| Purpose | Config key | Recipient | Trigger |
|---|---|---|---|
| Password reset | `MAIL_NEUES_PASSWORT` | `user.email` | POST `/intern/passwort/` (only for active accounts) |
| Invitation to the join form | `MAIL_EINLADUNG` | the entered address | POST `/intern/mitglied/einladen/` (perm `intern.add_user`) |
| Application — applicant's copy | `MAIL_ANTRAG` | address from the join form | POST `/intern/beitritt/<token>/`; attaches the application PDF |
| Application — admin notification | `MAIL_ANTRAG_ADMIN` | `ANTRAG_EMAIL`, else everyone with `intern.change_user` | same POST |
| First activation | `MAIL_WILLKOMMEN` | `user.email` | `post_save`: `is_active` → `True` and `date_joined is None` |
| Reactivation | `MAIL_REAKTIVIERT` | `user.email` | `post_save`: `is_active` → `True`, `date_joined` already set |
| Re-confirmation request | `MAIL_BESTAETIGUNG` | `user.email` | `manage.py send_reconfirmation` |
| Re-confirmation receipt | `MAIL_BESTAETIGUNG_BESTAETIGT` | `user.email` | POST `/intern/bestaetigung/<token>/`; attaches the confirmation PDF |
| Round mail to members | `MAIL_RUNDMAIL` | the selected members | POST `/intern/mitglied/benachrichtigen/` (perm `intern.notify_users`); optional filer attachments |
| Gig list: opt-in, welcome, already subscribed, reminder | `MAIL_MAILINGLISTE_OPTIN` / `_WILLKOMMEN` / `_BEREITS_ANGEMELDET` / `_ERINNERUNG` | the subscriber | see `mailinglist.md` |

Two switches worth knowing: **`MAIL_BEI_AKTIVIERUNG`** (`1`/`0`) governs the activation *and*
reactivation mail together — useful while testing — and an empty `MAIL_*` key produces a mail
with an empty body, not an error.

The admin notification composes conditional add-on texts through `extra_keys`:
`MAIL_ANTRAG_ADMIN_MINDERJAEHRIG` when the applicant is a minor at submission time and
`MAIL_ANTRAG_ADMIN_FOERDER` for a supporting membership. They are rendered at the `{hinweise}`
placeholder of the main text.

## Markup

`intern/mail_markup.py` renders one config text into **both** MIME parts (HTML with inline
styles, plain text) using the wiki syntax of the article editor — `'''fett'''`, `''kursiv''`,
`== Titel ==`, `*`/`#` lists, `% grauer Hinweis`, `@ Hinweisbox`, `: Einrückung`,
`[https://… Name]`, `$roh$` — plus the mail-only directive `{button:Label}` (links to `{link}`)
/ `{button:Label:URL}`. A button without a URL renders nothing. Placeholder values are
HTML-escaped; unknown `{placeholders}` stay verbatim. `/intern/konfiguration/` shows a syntax
legend while a `MAIL_*` field is focused.

`render_mail_markup(raw, placeholders, link)` returns the `(html, plain)` pair.

## Sending

Call sites use
`mail.send_config_mail(subject, to, key, user=…, link=…, extra_keys=…, attachments=…,
template=…, context=…, **placeholders)`; `render_config_mail()` / `render_mail_text()` return
the `(html, plain)` pair for callers that need it, and `build_mail_placeholders()` builds the
placeholder dict.

Underneath sits `send_branded_mail(subject, to, template, context, text_body=None,
attachments=None, headers=None)`: it renders the HTML template into a branded mail with the
embedded logo (`cid:logo`) and a plain-text fallback (both get the `MAIL_FOOTER` line), resolves
the sender via `get_from_email()` (the `DEFAULT_FROM_EMAIL` config key, falling back to
`settings.DEFAULT_FROM_EMAIL`), and **never raises** — it returns `True`/`False` so callers
can tell whether the message reached the backend. `attachments` is a list of `(filename, bytes,
content_type)` tuples; when present the outer MIME type is `multipart/mixed`. `headers` adds
extra MIME headers (used for `List-Unsubscribe`).

The function builds the MIME message itself and hands it to Django through a `_Msg` subclass
whose `message()` is overridden. **That override must apply `_SMTP_POLICY`** (compat32 with CRLF
line endings), otherwise `as_bytes()` emits bare LF and strict SMTP servers reject the whole mail
as one over-long line (RFC 5321).

Two mails carry a PDF: the application copy (`_save_antrag_pdf()`) and the re-confirmation
receipt (`_save_bestaetigung_pdf()`), both in `views/auth.py`, built with reportlab on top of
`intern/pdf.py`. Both PDFs are additionally filed under „Verwaltung/Mitglieder" in filer
(Vorstand-only).

The full placeholder list and the recipe for adding a new mail are in `configuration.md`.

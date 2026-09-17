# Members: joining, re-confirmation, leaving

## Member application flow (Mitglieds-Beitritt)

Two ways to add a member, both behind the `+` in `/intern/mitglied/` (perm `intern.add_user`).
The off-canvas panel (`templates/mitglied_add_panel.html`, included via the `add_panel_include`
context var in `table.html`) is two-step:

1. **Invite** (default step): an admin enters only an e-mail and submits to `mitglied_invite`
   (`views/mitglieder.py`). This sends a branded e-mail with a non-guessable link to the public
   join form. No user is created yet. The link carries the e-mail in a `TimestampSigner` token
   (salt `intern.mitglied_invite`, **7-day** validity) — `make_invite_token()` /
   `_read_invite_token()` in `views/auth.py`. Stateless: no DB model, no placeholder user.
2. **Manuell anlegen** (JS-revealed): `MitgliedAddForm` posting to `mitglied_add`, which creates
   an **active** member immediately.

The public join form lives at `/intern/beitritt/<token>/` (`mitglied_beitritt` in
`views/auth.py`, **no** `login_required`). `MitgliedBeitrittForm` (`forms.py`) validates all
member fields — required: first/last name, all address fields, `geburtstag`, `username` (regex
`^[A-Za-z0-9._-]{3,30}$` + case-insensitive uniqueness via `username__iexact`), two matching
passwords (`validate_password`), and five mandatory consent checkboxes (Richtigkeit der
Angaben; Datenschutz — links to `/datenschutz/`; Datenverarbeitung; Satzung — links to the PDF
configured via `SATZUNG_FILE_ID`; Beitragsordnung — via `BEITRAGSORDNUNG_FILE_ID`). Two
optional fields: `einwilligung_fotos` (photo consent at public events) and `foerdermitglied`
(supporting membership).

On success:

- the member is created with `is_active=False`;
- a PDF of the completed application is saved to the filer folder **„Mitglieder-Verwaltung"**
  (Vorstand-only, via `_save_antrag_pdf` in `views/auth.py` using reportlab; best-effort, never
  blocks registration);
- a confirmation mail goes to the applicant;
- a notification mail goes to the address configured via `ANTRAG_EMAIL` (falls back to members
  with `intern.change_user` via `_member_managers()` if empty). If the applicant is a minor at
  submission time, that mail contains a warning;
- if `foerdermitglied` is checked, the user is added to the `"Fördermitglied"` group
  immediately.

The public pages (`mitglied_beitritt.html`, `_success.html`, `_invalid.html`) extend the
standalone `mitglied_public_base.html` shell (no sidebar), not `base.html`.

The application is logged in the ChangeLog as a distinct action `ChangeLog.ACTION_APPLICATION`
(`"apply"` → "Neuer Mitgliedsantrag"): the view sets `user._audit_application = True` before
saving and `signals._write_audit_log` maps that to the application action (the action code is
≤8 chars to fit `action`'s `max_length`).

**Applicants are created with `date_joined=None`** (the field is overridden on `User` to be
nullable). This is the discriminator for the activation mail: when an admin later sets
`is_active=True`, `signals._send_activation_mail()` checks `user.date_joined is None` →
first-time activation → sends the `MAIL_WILLKOMMEN` text and stamps `date_joined` via
`User.objects.filter(pk=...).update(date_joined=timezone.now())` (avoids a recursive signal). If
`date_joined` is already set → reactivation → `MAIL_REAKTIVIERT`. Both texts get `{link}` = the
login URL derived from `VEREINS_URL`; without it the `{button:…}` in the text renders nothing.
No mail is sent if the user has no email address.

## Re-confirmation flow (Datenbestätigung)

Lets the board ask existing members to re-confirm their stored data and re-acknowledge the
privacy policy, bylaws and fee schedule.

**Trigger:** `manage.py send_reconfirmation --user <username>|--all` (uses `VEREINS_URL`;
override with `--base-url URL`). The command calls `send_bestaetigung_mail(user, base_url)` in
`views/auth.py`, which:

1. creates a `TimestampSigner` token (salt `"intern.mitglied_bestaetigung"`, **30-day**
   validity) encoding the user PK;
2. reads the mail body from the `Konfiguration` key **`MAIL_BESTAETIGUNG`** — all standard
   placeholders plus `{link}`; an empty key means an empty mail body;
3. sends it via `send_config_mail()`.

**Public form:** `/intern/bestaetigung/<token>/` (`mitglied_bestaetigung` in `views/auth.py`, no
`login_required`). Shows the member's current data (read-only) plus three mandatory checkboxes
(`MitgliedBestaetigungForm`): data correct, Datenschutz, Satzung.

**On submit:** `_save_bestaetigung_pdf(user)` generates a PDF (reportlab) with all stored data +
confirmed checkboxes, saves it to „Mitglieder-Verwaltung" in filer, and attaches it to the
quittance mail sent to the member (`MAIL_BESTAETIGUNG_BESTAETIGT`). No Vorstand notification.
Three public templates extend `mitglied_public_base.html`: `mitglied_bestaetigung.html`,
`_success.html`, `_invalid.html`.

## Leaving: anonymise or delete

`mitglied_delete` (`views/mitglieder.py`) first hands the member's files and folders to a new
owner (`besitz_uebertragen`, see `files.md`), then decides: a member who left content behind
(`Mitteilung`, `Artikel`, `Abstimmung`) is anonymised to `geloescht_<id>`, everyone else is
really deleted. `UserAdmin.delete_model`/`delete_queryset` (`intern/admin.py`) take the same
route so the admin path cannot bypass the ownership transfer.

## Field-level privacy and the address-book opt-out

`User.private_fields` holds the fields a member has hidden. `User.field_visible_to()` grants
holders of `intern.change_user` a view of hidden fields inside the portal — but **that admin
bonus stops at the portal boundary**: the CardDAV cards, the CalDAV birthdays and the birthday
chips in the month grid consult `private_fields` alone (see `dav.md`).

`User.adressbuch_verborgen` goes one step further: it keeps the **whole** record out of the
CardDAV address book, not just single fields. Both are set by the member alone — `mitglied_edit`
passes `with_privacy` / `mit_adressbuch` only when `request.user.id == id`, so an admin editing a
foreign profile never sees either control. The address-book checkbox additionally requires
`CARDDAV_AKTIV`; when the service is off the field is not built at all, which is what makes a
stored `True` survive the service being switched off and on again. It is deliberately **not** in
`UserEditForm.Meta.fields` — a checkbox that was never rendered is absent from the POST, and
`BooleanField` would turn that into a `False` that silently overwrites the member's wish.
`mitglied_delete` leaves the flag alone when anonymising, for the same reason.

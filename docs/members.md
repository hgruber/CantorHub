# Members: joining, re-confirmation, leaving

## Membership and portal access: two axes

`is_active` and the group **„Mitglied"** answer two different questions, and
`intern/mitgliedschaft.py` is the one place that spells them out:

| | meaning |
|---|---|
| `is_active` | actively taking part — and therefore allowed into the portal. Nothing else. |
| group „Mitglied" | club membership. It survives a dormant membership: whoever pauses loses the access (`is_active=False`) but keeps the tag. |

The two combine freely. A dormant member is „tag, no access"; the conductor's account from the
legacy portal is „access, no tag" (`legacy_id=232`, see `migration.md`); „Fördermitglied"
(supporting member) is a member who does not take part, so tag without access.

The tag carries **no permissions** — like „Gründer", „Fördermitglied" and „Kassenprüfer" it is a
bare label in `GROUPS` (`0003_import.py`). „Gründer" has lost its function entirely: it steers
the import and nothing else, and may be deleted later.

**Admission** is its own action, „Mitgliedschaft genehmigen" in `mitglied_edit`
(`action="aufnehmen"`, perm `intern.change_user`). `mitgliedschaft.nimm_auf()` adds the tag,
writes a `ChangeLog` row for it (`changes={"gruppe": …}`) and — unless the account carries
„Fördermitglied" — switches `is_active` on in the same step. The tag is set **before** the save,
because the signal below reads it. The dormant/reactivate switch next to it never touches tags,
which is what makes a dormant membership stay one.

**First admission vs. reactivation.** `signals._send_activation_mail()` asks
`ist_erstaufnahme(user.date_joined, ist_mitglied(user))`: only a member (tag) without an
Eintrittsdatum yet is a first admission and gets `MAIL_WILLKOMMEN` plus the stamp. A missing
`date_joined` alone is not enough — an account without the tag never had one, and would
otherwise be greeted as a newcomer every time it is switched back on. Such accounts take the
`MAIL_REAKTIVIERT` path and keep an empty „Mitglied seit", which is correct for a non-member.

Because a dormant account keeps its tags, the group matrix `/intern/aufgaben/` lists dormant
accounts too (marked „ruhend"); only anonymised ones (`geloescht_*`) stay out. Otherwise a
dormant member's tag could be neither seen nor corrected.

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
   an **active** member immediately — the shortcut for an application already approved, so it
   also sets the tag „Mitglied" (`nimm_auf()`) and stamps `date_joined` with that day. Without
   the stamp „Mitglied seit" would stay empty for good: the welcome mail hangs on `is_active`
   *changing*, which never happens for an account that starts out active.

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
nullable) and **without** the tag „Mitglied" — an application is not yet a membership. The
approval is the „Mitgliedschaft genehmigen" action above: it sets the tag and `is_active`
together, and only that combination makes `signals._send_activation_mail()` treat the change as
a first admission → sends the `MAIL_WILLKOMMEN` text and stamps `date_joined` via
`User.objects.filter(pk=...).update(date_joined=timezone.now())` (avoids a recursive signal).
With a `date_joined` already set, or without the tag, it is a reactivation →
`MAIL_REAKTIVIERT`. Both texts get `{link}` = the login URL derived from `VEREINS_URL`; without
it the `{button:…}` in the text renders nothing. No mail is sent if the user has no email
address — and then no `date_joined` is stamped either, since the whole branch hangs on the mail.

An application marked `foerdermitglied` is approved by the same action: the account gets the tag
„Mitglied" beside „Fördermitglied" and stays inactive, so no mail and no Eintrittsdatum.

Applicants are not the only source of that `None`: the legacy import brings **every** member in
without an Eintrittsdatum, gives the tag „Mitglied" to the founding members alone and
deactivates everyone outside „Gründer" (`migration.md`, „What `0003_import.py` does"). The
accounts admitted later therefore take exactly this path — „Mitgliedschaft genehmigen" gives
them tag and access, they receive the welcome mail, and the day of their admission becomes their
Eintrittsdatum. Until then „Mitglied seit" is empty on their card (`mitglied.html`) and the
CardDAV note omits the line (`carddav/vcard.py`; both handle the `None`).

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
3. sends it via `send_config_mail()`;
4. switches `is_active` off once the mail went out — the member cannot log in (portal,
   CardDAV/CalDAV; open sessions end) until the form is submitted. A failed send leaves the
   account alone, and `--print-url` never locks.

`--user` also finds an account that is already locked, so an expired link can be re-sent; `--all`
covers active members only. The lock is `is_active` alone, without a marker: a dormant member
holding a still valid link could unlock themselves through it.

**Login hint:** `CantorAuthenticationForm` (`forms.py`) sets `zugang_gesperrt` when the password
is right but the account is inactive, and `login.html` then asks the member to confirm through
the mail link instead of claiming a wrong password. It cannot tell a pending confirmation from a
dormant account, so the wording covers both. `LoginSperrhinweisTest` guards it.

**Public form:** `/intern/bestaetigung/<token>/` (`mitglied_bestaetigung` in `views/auth.py`, no
`login_required`, inactive accounts accepted, anonymised `geloescht_*` ones not). Shows the member's current data (read-only) plus three mandatory checkboxes
(`MitgliedBestaetigungForm`): data correct, Datenschutz, Satzung.

**On submit:** an inactive account is switched back on first, flagged `_ohne_aktivierungsmail`
so that `signals._send_activation_mail()` stays out: no welcome or reactivation mail and **no
Eintrittsdatum** — the legacy import left most members with tag „Mitglied" and
`date_joined=None`, which the signal would otherwise take for a first admission. Then
`_save_bestaetigung_pdf(user)` generates a PDF (reportlab) with all stored data +
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

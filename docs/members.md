# Members: joining, re-confirmation, leaving

## Membership and portal access: two axes

`is_active` and the group **„Mitglied"** answer two different questions, and
`intern/mitgliedschaft.py` is the one place that spells them out:

| | meaning |
|---|---|
| `is_active` | actively taking part — and therefore allowed into the portal. Nothing else. |
| group „Mitglied" | club membership. Ending it („Mitgliedschaft beenden") removes the tag and the access together. |

The two combine freely. The conductor's account from the
legacy portal is „access, no tag" (`legacy_id=232`, see `migration.md`); „Fördermitglied"
(supporting member) is a member who does not take part, so tag without access.

The tag also carries the permissions every member has — initially „Mitglieder: benachrichtigen"
and all of „Orte" (`GROUPS` in `0003_import.py`); ending the membership takes them away with it.
„Gründer", „Fördermitglied" and „Kassenprüfer" are bare labels. „Gründer" has lost its function
entirely: it steers the import and nothing else, and may be deleted later.

**Admission** is its own action, „Mitgliedschaft genehmigen" in `mitglied_edit`
(`action="aufnehmen"`, perm `intern.change_user`). `mitgliedschaft.nimm_auf()` adds the tag,
writes a `ChangeLog` row for it (`changes={"gruppe": …}`) and — unless the account carries
„Fördermitglied" — switches `is_active` on in the same step. The tag is set **before** the save,
because the signal below reads it.

The page offers exactly one membership action, chosen by
`mitgliedschafts_aktion(ist_mitglied, date_joined)`, and the view accepts only that one:

| state | action | button | perms |
|---|---|---|---|
| tag | `beenden` | „Mitgliedschaft beenden" | `change_user` **and** `manage_user_permissions` |
| no tag, `date_joined` set | `wieder_aufnehmen` | „Mitgliedschaft wieder aufnehmen" | `change_user` **and** `manage_user_permissions` |
| no tag, no `date_joined` | `aufnehmen` | „Mitgliedschaft genehmigen" | `change_user` |

`mitgliedschaft.beende()` removes the tag (with its `ChangeLog` row) and switches `is_active`
off; `date_joined` stays, which is what marks the former member. „Wieder aufnehmen" runs
`nimm_auf()`, so a Fördermitglied stays without access, and the kept `date_joined` sends
`MAIL_REAKTIVIERT` instead of the welcome mail.

An account **without** the tag (the conductor, a guest) additionally gets „Zugang sperren" /
„Zugang freischalten" (`action="zugang"`, same two perms). It flips `is_active` alone and is
refused for an account with the tag; unlocking sends `MAIL_REAKTIVIERT`, because without the
tag it never counts as a first admission.

**First admission vs. reactivation.** `signals._send_activation_mail()` asks
`ist_erstaufnahme(user.date_joined, ist_mitglied(user))`: only a member (tag) without an
Eintrittsdatum yet is a first admission and gets `MAIL_WILLKOMMEN` plus the stamp. A missing
`date_joined` alone is not enough — an account without the tag never had one, and would
otherwise be greeted as a newcomer every time it is switched back on. Such accounts take the
`MAIL_REAKTIVIERT` path and keep an empty „Mitglied seit", which is correct for a non-member.

Because a Fördermitglied carries the tag without access, the group matrix `/intern/aufgaben/`
lists inactive accounts too (marked „kein Zugang"); only anonymised ones (`geloescht_*`) stay out.
Otherwise such a member's tag could be neither seen nor corrected.

## Member application flow (Mitglieds-Beitritt)

Two ways to add a member, both behind the `+` in `/intern/mitglied/` (perm `intern.add_user`).
The off-canvas panel (`templates/mitglied_add_panel.html`, included via the `add_panel_include`
context var in `table.html`) is two-step:

1. **Invite** (default step): an admin enters only an e-mail and submits to `mitglied_invite`
   (`views/mitglieder.py`). This sends a branded e-mail with a non-guessable link to the public
   join form. No user is created yet. The link carries the e-mail in a `TimestampSigner` token
   (salt `intern.mitglied_invite`, **7-day** validity) — `make_invite_token()` /
   `_read_invite_token()` in `views/auth.py`. Stateless: no DB model, no placeholder user.
   An address that already belongs to an account (case-insensitive) is refused, here and in
   `make_invite_url`: the join form would create a second account for the same person, and
   `User.email` is not unique. Such an account applies through `send_antragslink` (see
   „Application for an existing account" below).
2. **Manuell anlegen** (JS-revealed; button, form and view additionally require
   `intern.manage_user_permissions`, which a superuser holds implicitly):
   `MitgliedAddForm` posting to `mitglied_add`, which creates
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
(supporting membership). Without the photo consent the new account gets the tag „kein Bild"
(see below).

On success:

- the member is created with `is_active=False`;
- a PDF of the completed application is saved to the filer folder **„Verein/Vorstand/Mitgliedsanträge"**
  (Vorstand-only, via `_save_antrag_pdf` in `views/auth.py` using reportlab; best-effort, never
  blocks registration);
- a confirmation mail goes to the applicant;
- a notification mail goes to the address configured via `ANTRAG_EMAIL` (falls back to members
  with `intern.change_user` via `_member_managers()` if empty). If the applicant is a minor at
  submission time, that mail contains a warning;
- if `foerdermitglied` is checked, the user is added to the `"Fördermitglied"` group
  immediately. The checkbox (with its card, dialog and PDF section) is only offered while
  `FOERDERMITGLIED_IM_ANTRAG` in `intern/mitgliedschaft.py` is `True`; it is currently off.

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

### Application for an existing account

Those legacy accounts — inactive, no tag — already have a username and a password, so the join
form above would refuse them (username taken). `manage.py send_antragslink --user <username>`
sends them `MAIL_EINLADUNG` with a link to `/intern/beitritt/konto/<token>/`
(`mitglied_antrag_bestand` in `views/auth.py`). The token carries the user PK (salt
`intern.mitglied_antrag_bestand`, validity `MITGLIED_EINLADUNG_TAGE` like an invitation);
`--print-url` prints the link instead of mailing it.

`MitgliedAntragBestandForm` is the join form without `username` and the two password fields,
pre-filled from the account; username and password stay as they are. Submitting saves the data
and then runs the same tail as a new application (`_antrag_abschliessen()`: photo tag, PDF,
`MAIL_ANTRAG`, `MAIL_ANTRAG_ADMIN`). The account stays inactive and untagged; the board admits it
with „Mitgliedschaft genehmigen" (or „wieder aufnehmen" if it carries an Eintrittsdatum). The
ChangeLog shows the submission as an ordinary update, not as „Neuer Mitgliedsantrag", because
that action is tied to creating the row.

Whether a link still shows the form is decided by the account — `antragslink_gilt()` in
`mitgliedschaft.py`, guarded by `MitgliedschaftTest`: only without access and without tag. Once
admitted, the link shows „Kein Antrag nötig". Until then it can be submitted again, which files
another PDF and sends the two mails again. The command refuses an account the link would reject.

## Re-confirmation flow (Datenbestätigung)

Lets the board ask existing members to re-confirm their stored data and re-acknowledge the
privacy policy, bylaws and fee schedule.

**Trigger:** `manage.py send_reconfirmation --user <username>|--all` (uses `VEREINS_URL`;
override with `--base-url URL`). The command calls `send_bestaetigung_mail(user, base_url)` in
`views/auth.py`, which:

1. creates a `TimestampSigner` token (salt `"intern.mitglied_bestaetigung"`, validity
   `MITGLIED_BESTAETIGUNG_TAGE` days, default 30) encoding the user PK;
2. reads the mail body from the `Konfiguration` key **`MAIL_BESTAETIGUNG`** — all standard
   placeholders plus `{link}`; an empty key means an empty mail body;
3. sends it via `send_config_mail()`;
4. switches `is_active` off once the mail went out (`sperre_bis_bestaetigung()`) — the member
   cannot log in (portal, CardDAV/CalDAV; open sessions end) until the form is submitted. A
   failed send leaves the account alone. `--print-url` locks as well: without the lock the
   printed link would be refused (see below).

Only accounts tagged „Mitglied" are addressed: `--all` covers active ones with the tag, `--user`
refuses an account without it and neither sends nor locks. `--user` also finds an account that is
already locked, so an expired link can be re-sent.

**What a link still does** is decided by the account, not the token —
`bestaetigungslink_zustand(is_active, ist_mitglied)` in `mitgliedschaft.py`, guarded by
`MitgliedschaftTest`: active → already confirmed, the link is spent (a friendly „Bereits
bestätigt" page); locked with tag → the form; locked without tag → invalid, so a link still
running after „Mitgliedschaft beenden" cannot reopen the account. The remaining gap: an account
the board merely deactivated, tag kept, can still be unlocked by a valid link.

**Login hint:** `CantorAuthenticationForm` (`forms.py`) sets `zugang_gesperrt` when the password
is right but the account is inactive, and `login.html` then asks the member to confirm through
the mail link instead of claiming a wrong password. It cannot tell a pending confirmation from a
dormant account, so the wording covers both. `LoginSperrhinweisTest` guards it.

**Public form:** `/intern/bestaetigung/<token>/` (`mitglied_bestaetigung` in `views/auth.py`, no
`login_required`, only in the state „locked with tag" above, anonymised `geloescht_*` accounts
never). Shows the member's current data (read-only) plus three mandatory checkboxes
(`MitgliedBestaetigungForm`): data correct, Datenschutz, Beitragsordnung — plus the optional photo
consent, pre-ticked unless the member carries „kein Bild". Submitting sets or removes the tag
according to that box and prints it into the PDF.

**On submit:** an inactive account is switched back on first, flagged `_ohne_aktivierungsmail`
so that `signals._send_activation_mail()` stays out: no welcome or reactivation mail and **no
Eintrittsdatum** — the legacy import left most members with tag „Mitglied" and
`date_joined=None`, which the signal would otherwise take for a first admission. Then
`_save_bestaetigung_pdf(user)` generates a PDF (reportlab) with all stored data +
confirmed checkboxes, saves it to „Verein/Vorstand/Mitgliedsanträge" in filer, and attaches it to the
quittance mail sent to the member (`MAIL_BESTAETIGUNG_BESTAETIGT`). No Vorstand notification.
Three public templates extend `mitglied_public_base.html`: `mitglied_bestaetigung.html`,
`_success.html`, `_invalid.html`.

## Photo consent: the tag „kein Bild"

The group „kein Bild" (`GRUPPE_KEIN_BILD` in `mitgliedschaft.py`) marks members who have not
consented to the publication of their photos. It is set or removed only from the photo checkbox
of the application and of the re-confirmation form; the portal has no button for it, and the
member's own profile form has no group field. Every change goes through
`setze_kein_bild()` and leaves a `ChangeLog` entry. Existing members start without the tag;
their consent is unrecorded until they re-confirm.

## Privacy confirmation without membership

Accounts with access but without the tag „Mitglied" (conductor, guests) never see the
application or the re-confirmation, so the portal asks them itself. `DatenschutzPruefung`
(`middleware.py`, right after `SitzungAuffrischen`) redirects every request under `/intern/` to
`/intern/datenschutz-bestaetigen/` while `braucht_datenschutzbestaetigung(is_active,
ist_mitglied, hat_bestaetigt)` in `mitgliedschaft.py` says so — active, no „Mitglied", no
„DSGVO". GET requests keep their target in `next` (checked with
`url_has_allowed_host_and_scheme`), htmx requests get `HX-Redirect`. `DATENSCHUTZ_FREI` lists
the exempt prefixes: the page itself, login/logout, password reset, the public forms and
`/media-auth/` (a redirect there would fail every image behind nginx' `auth_request`).
`DatenschutzPruefungTest` checks that they match real URLs. Outside `/intern/` nothing is gated,
so CardDAV/CalDAV keep working until the confirmation.

The page (`datenschutz_bestaetigen` in `views/auth.py`) shows name, username and e-mail
read-only, the mandatory Datenschutz checkbox and the photo consent pre-filled from „kein Bild".
Submitting sets the group „DSGVO" (`GRUPPE_DATENSCHUTZ_BESTAETIGT`, via
`setze_datenschutz_bestaetigt()`, logged), sets or removes „kein Bild", files a PDF under
„Verein/Vorstand/Mitgliedsanträge" and mails it with the `MAIL_BESTAETIGUNG_BESTAETIGT` text.

The tag says *that*, not *when* or *which version*; the date is in the PDF and the ChangeLog.
To ask again (e.g. after the policy changed) remove it: `manage.py datenschutz_zuruecksetzen
--all|--user NAME`. Members never carry it — the gate looks at „Mitglied" first.

## Leaving: anonymise or delete

`mitglied_delete` (`views/mitglieder.py`) first hands the member's files and folders to a new
owner (`besitz_uebertragen`, see `files.md`), then decides: a member who left content behind
(`Mitteilung`, `Artikel`, `Abstimmung`) is anonymised to `geloescht_<id>`, everyone else is
really deleted. `UserAdmin.delete_model`/`delete_queryset` (`intern/admin.py`) take the same
route so the admin path cannot bypass the ownership transfer.

## Name references (Namensverweise)

The import brings back people from the legacy portal who only remain as the sender of old forum
messages or the author of old article versions: username `verweis_<legacy id>`, first name
only, **`last_name` NULL**, no access, unusable password, no groups. NULL is the marker
(`models.NAMENSVERWEIS`): no form ever writes it, and it avoids MariaDB's PAD SPACE comparison.
No view lists them — the member list (also for managers with „Aktiv: Egal"), the rights grid in
`aufgaben`, the admin changelist exclude `NAMENSVERWEIS`, `mitglied_view`/`mitglied_edit`
answer 404, and every other member selection already filters `is_active=True`. The forum shows
their first name without a profile link.

## Field-level privacy and the address-book opt-out

`User.private_fields` holds the fields a member has hidden. `User.field_visible_to()` grants
holders of `intern.change_user` a view of hidden fields inside the portal — but **that admin
bonus stops at the portal boundary**: the CardDAV cards, the CalDAV birthdays and the birthday
chips in the month grid consult `private_fields` alone (see `dav.md`).

A hidden field is hidden from the filters too. The member list's filter builder offers the
`PRIVACY_FIELDS` — and the access switch — only to `intern.change_user`
(`filterbau.py` · `erlaubte_felder`); everyone else never sees them in the dropdown, and a
hand-written URL naming one is discarded while parsing. That second half matters: the filter runs
on the raw queryset, while the table blanks hidden values only as it renders, so filtering on one
would betray through the *hit count* what the cell keeps quiet.

`User.adressbuch_verborgen` goes one step further: it keeps the **whole** record out of the
CardDAV address book, not just single fields. Both are set by the member alone — `mitglied_edit`
passes `with_privacy` / `mit_adressbuch` only when `request.user.id == id`, so an admin editing a
foreign profile never sees either control. The address-book checkbox additionally requires
`CARDDAV_AKTIV`; when the service is off the field is not built at all, which is what makes a
stored `True` survive the service being switched off and on again. It is deliberately **not** in
`UserEditForm.Meta.fields` — a checkbox that was never rendered is absent from the POST, and
`BooleanField` would turn that into a `False` that silently overwrites the member's wish.
`mitglied_delete` leaves the flag alone when anonymising, for the same reason.

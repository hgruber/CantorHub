# Permissions

Where each right that `/intern/gruppen/` offers is checked, at which URL, and what it unlocks
there — plus the access rules that page does **not** show. Membership itself (`is_active` vs. the
group „Mitglied") is `docs/members.md`; folder rights in detail are `docs/files.md`, forum read
rights `docs/forum.md`, article rights `docs/articles.md`.

## How a check is made

The page `/intern/gruppen/` lists exactly the rights in `PERMISSION_DEFS`
(`intern/views/gruppen.py`); its tooltips come from `PERMISSION_DESCRIPTIONS` in the same file.
A click on a column header opens a help dialog built from `PERMISSION_DETAILS` — the tables below
in user-facing words, a third element naming a second right a place also needs — and lists who
holds the right, per group, direct grant or admin status (`rechte_inhaber()`, active accounts
only). The same dialog (`_rechte_hilfe_dialog.html`, `rechte-hilfe.js`) serves the card „Meine
Rechte" on one's own profile, which lists the rights one holds and, instead of all holders, only
the sources one holds each through (`eigene_rechte()`); other profiles do not show it, since who
holds which right is otherwise visible on `/intern/gruppen/` alone. A change to a check belongs in
both lists; `RechteHilfeTest` only guards that every right
has an entry and that a second right exists.
A right is granted to a group there (or to a single account in `/admin/`). Four forms of check
occur in the code:

| Form | Effect without the right |
|---|---|
| `@permission_required(…, raise_exception=True)` | 403 |
| `@perm_or_home(…)` (`views/_decorators.py`) | silent redirect to „Aktuell" — for pages whose menu entry the member never sees |
| `request.user.has_perm(…)` in a view | the button, link or form is not offered; for a write it answers 403 or redirects |
| `{% if perms.intern.… %}` in a template | the element is not rendered |

A superuser passes every `has_perm()` check. The one exception is `view_forum_archiv`, which
`darf_forum_archiv()` reads from the permission table so that it must be granted explicitly.

The tables below name the code location as module and function rather than a line number, so
they survive edits. Module paths are relative to `intern/`.

## Mitglieder

| Right | Code location | URL | Purpose |
|---|---|---|---|
| `add_user` | `views/mitglieder.py` · `mitglied_list` | `/intern/mitglied/` | offers the „+" button with the invitation panel |
| `add_user` | `views/mitglieder.py` · `mitglied_invite` | `/intern/mitglied/invite/` | send an invitation link |
| `add_user` **and** `manage_user_permissions` | `views/mitglieder.py` · `mitglied_add`; `templates/mitglied_add_panel.html` | `/intern/mitglied/add/` | create an account manually, without invitation; the panel shows „manuell anlegen" only with `manage_user_permissions` |
| `change_user` | `views/mitglieder.py` · `mitglied_list`, `mitglied_emails`, `mitglied_benachrichtigen` | `/intern/mitglied/`, `/intern/mitglied/emails/`, `/intern/mitglied/benachrichtigen/` | the lists include accounts without portal access; otherwise only active ones |
| `change_user` | `filterbau_mitglieder.py` · `Feld.recht`; `filterbau.py` · `erlaubte_felder`, `lese_bedingungen` | `/intern/mitglied/` | which filter criteria the builder offers — e-mail, XMPP, phone, fax, address, birthday and the access switch are for managers. The list itself needs no right. The gate must sit in the reading code, not only in the dropdown: the filter runs **before** `MitgliederTabelle` blanks hidden fields, so a filter on one would reveal its value through the hit count. See `docs/frontend.md` |
| `change_user` | `views/mitglieder.py` · `mitglied_view` | `/intern/mitglied/<id>/` | edit and history links on another member's profile (one's own profile is always editable) |
| `change_user` | `views/mitglieder.py` · `mitglied_edit`; `templates/mitglied_edit.html` | `/intern/mitglied/<id>/edit/` | edit another member's data (otherwise redirect to the profile) and „Mitgliedschaft genehmigen" |
| `change_user` | `views/aenderungen.py` · `mitglied_aenderungen` | `/intern/mitglied/<id>/aenderungen/` | a member's change history |
| `change_user` | `models.py` · `User.field_visible_to` | every member view | see fields a member hid (`private_fields`) — in the portal only, never in CardDAV/CalDAV |
| `change_user` | `views/karte.py` · `karte_view` | `/intern/karte/` | show the markers of members who hid their address |
| `change_user` (or superuser) | `avatar_access.py` · `darf_avatar_aendern`; `views/files.py` · `upload` | `/intern/upload/`, `/intern/mitglied/<id>/edit/` | replace another member's profile picture |
| `change_user` (or superuser) | `views/auth.py` · `_member_managers` | — (mail) | recipients of the notice about a new membership application; read by codename, so group and direct grants both count |
| `delete_user` | `views/mitglieder.py` · `mitglied_delete`; `templates/mitglied_edit.html` | `/intern/mitglied/<id>/delete/` | delete an account; never offered for one's own |
| `manage_user_permissions` | `views/gruppen.py` · `gruppen` | `/intern/gruppen/` | this page: grant and revoke rights per group |
| `manage_user_permissions` | `views/aufgaben.py` · `aufgaben` | `/intern/aufgaben/` | put members into groups (the admin-status column only for superusers) |
| `manage_user_permissions` | `views/aenderungen.py` · `aenderungsprotokoll_list` | `/intern/aenderungsprotokoll/` | the audit log |
| `manage_user_permissions` | `views/auslieferungen.py` · `auslieferungen`; `templates/sidebar.html` | `/intern/changelog/` | release notes and the version link under the sidebar |
| `manage_user_permissions` | `templates/sidebar.html` | every page | the admin menu (Aufgaben, Gruppen, Änderungsprotokoll) |
| `manage_user_permissions` **and** `change_user` | `views/mitglieder.py` · `mitglied_edit`; `templates/mitglied_edit.html` | `/intern/mitglied/<id>/edit/` | „Mitgliedschaft beenden" / „wieder aufnehmen", and „Zugang sperren/freischalten" for accounts without the tag „Mitglied" |
| `notify_user` | `views/mitglieder.py` · `mitglied_list` | `/intern/mitglied/` | the „benachrichtigen" button |
| `notify_user` | `views/mitglieder.py` · `mitglied_benachrichtigen`, `mitglied_benachrichtigen_files` | `/intern/mitglied/benachrichtigen/`, `…/dateien/` | mail the members of the active filter, with attachments |

## Dateien

| Right | Code location | URL | Purpose |
|---|---|---|---|
| `delete_folder` | `views/folders.py` · `folder_view` | `/intern/ordner/<pk>/` | offers delete in every folder, beyond the folder's own `FolderPermission` delete flag |
| `delete_folder` | `views/folders.py` · `folder_delete` | `/intern/ordner/loeschen/` | delete folders and files regardless of `FolderPermission` |
| `delete_folder` | `views/files.py` · `datei_aktionen`; `views/artikel.py` · `article_datei_loeschen` | `/intern/datei/<pk>/aktionen/`, `/intern/artikel/<name>/datei-loeschen/` | „Datei löschen" in an article's thumbnail menu regardless of `FolderPermission`; the article's edit right is still required |
| `manage_folder_permissions` | `views/folders.py` · `folder_view` | `/intern/ordner/<pk>/` | the „Berechtigungen" link |
| `manage_folder_permissions` | `views/folders.py` · `folder_view` | `/intern/ordner/0/` | lists „Backstage" at the root (hidden, not locked, for everyone else) |
| `manage_folder_permissions` | `views/files.py` · `upload`; `base.html` (`data-upload-wurzel`) | `/intern/upload/`, every page | upload to the root: the page dropzone on pages without an upload target and on the browser's root (everyone else gets none, and a 403) |
| `manage_folder_permissions` | `views/folders.py` · `folder_view`, `folder_move`, `_copy_action`; `views/files.py` · `datei_aktionen` | `/intern/ordner/<pk>/`, `/intern/ordner/verschieben/` …, `/intern/datei/<pk>/aktionen/` | offers and accepts Backstage and its subfolders as a move, link or copy target (`_sieht_backstage`) |
| `manage_folder_permissions` | `views/aufgaben.py` · `folder_permissions` | `/intern/ordner/<pk>/berechtigungen/` | edit the folder's `FolderPermission` rows |

## Termine

| Right | Code location | URL | Purpose |
|---|---|---|---|
| `add_termin` | `views/termine.py` · `termin_list`, `termin_kalender` | `/intern/termin/`, `/intern/kalender/` | the „+" button and the add form |
| `add_termin` | `views/termine.py` · `termin_add` | `/intern/termin/add/` | create an event |
| `change_termin` | `views/termine.py` · `termin_view` | `/intern/termin/<id>/` | edit and history links |
| `change_termin` | `views/termine.py` · `termin_edit` | `/intern/termin/<id>/edit/` | edit an event |
| `change_termin` | `views/termine.py` · `termin_view` | `/intern/termin/<id>/` | card „Dateien“: drop area and unlink buttons; without the right the page has no upload at all |
| `change_termin` | `views/files.py` · `upload` | `/intern/upload/` | `termin_id`: link the upload to the event, checked before the file is stored |
| `change_termin` | `views/termine.py` · `termin_datei_entfernen` | `/intern/termin/<id>/dateien/<file>/entfernen/` | unlink a file from the event (the file stays) |
| `change_termin` | `views/aenderungen.py` · `termin_aenderungen` | `/intern/termin/<id>/aenderungen/` | an event's change history |
| `delete_termin` | `views/termine.py` · `termin_edit`, `termin_delete` | `/intern/termin/<id>/edit/`, `…/delete/` | the delete card and the deletion |
| `change_zusage` | `templates/termin.html`, `templates/_termin_zusage.html` | `/intern/termin/<id>/` | edit mode of the attendance table (move other members' chips) |
| `change_zusage` | `views/termine.py` · `termin_anwesenheit_update` | `/intern/termin/<id>/anwesenheit/` | save other members' attendance; one's own answer needs no right |

## Repertoire

| Right | Code location | URL | Purpose |
|---|---|---|---|
| `add_lied` | `views/titel.py` · `titel_list` | `/intern/titel/` | the „+" button and the add form |
| `add_lied` | `views/titel.py` · `titel_add` | `/intern/titel/add/` | add a song |
| `change_lied` | `views/titel.py` · `titel_list` | `/intern/titel/?konzert=<id>` | the link to edit an event's running order |
| `change_lied` | `views/titel.py` · `update_order` | `/intern/update-order/` | save the running order |
| `change_lied` | `views/titel.py` · `titel_view` | `/intern/titel/<id>/` | edit and history links |
| `change_lied` | `views/titel.py` · `titel_edit` | `/intern/titel/<id>/edit/` | edit a song |
| `change_lied` | `views/aenderungen.py` · `titel_aenderungen` | `/intern/titel/<id>/aenderungen/` | a song's change history |
| `change_lied` | `views/files.py` · `upload` | `/intern/upload/` | file an upload to a song (`lied_id`, e.g. a drop on the song page) |
| `delete_lied` | `views/titel.py` · `titel_delete` | `/intern/titel/<id>/delete/` | delete a song |

The repertoire's filter builder has no gate: the right sits on the field (`Feld.recht`), and no
field in `filterbau_titel.py` carries one — whoever is logged in sees and filters every
criterion.

## Artikel

| Right | Code location | URL | Purpose |
|---|---|---|---|
| `delete_artikel` | `views/artikel.py` · `article_view`, `article_delete` | `/intern/artikel/<name>/`, `…/loeschen/` | the delete action and the deletion of all versions |
| `manage_artikel_permissions` | `views/artikel.py` · `article_list` | `/intern/artikel/` | lists read-restricted articles too |
| `manage_artikel_permissions` | `views/artikel.py` · `article_view` | `/intern/artikel/<name>/` | the „Berechtigungen" link |
| `manage_artikel_permissions` | `views/artikel.py` · `article_permissions` | `/intern/artikel/<name>/berechtigungen/` | edit the article's `ArtikelPermission` rows |

Reading and editing an article are decided by `ArtikelPermission` groups alone
(`_artikel_access`), and so is creating one — there is no right for either, and neither
`manage_artikel_permissions` nor superuser status lifts a restriction on the article page itself.
The edit right also gates uploading on the article view and the writing entries of the
thumbnail menu (see „Files in an article" in `articles.md`).

## Forum

| Right | Code location | URL | Purpose |
|---|---|---|---|
| `add_forum` | `views/forums.py` · `forum_list`, `forum_add` | `/intern/forum/`, `/intern/forum/add/` | the „+" button and creating a forum |
| `change_forum` | `views/forums.py` · `forum_view` | `/intern/forum/<id>/` | edit and history links |
| `change_forum` | `views/forums.py` · `forum_edit` | `/intern/forum/<id>/edit/` | edit title, image and linked XMPP room |
| `change_forum` | `views/forums.py` · `forum_invite` | `/intern/forum/<id>/invite/<user_id>/` | invite a member into the linked MUC room |
| `change_forum` | `views/forums.py` · `forum_deaktivieren` | `/intern/forum/<id>/deaktivieren/` | archive a forum |
| `change_forum` | `views/aenderungen.py` · `forum_aenderungen` | `/intern/forum/<id>/aenderungen/` | a forum's change history |
| `delete_forum` | `views/forums.py` · `forum_delete`; `templates/forum_edit.html` | `/intern/forum/<id>/delete/` | the delete card and the deletion with all messages |
| `manage_forum_permissions` | `views/forums.py` · `_forum_access`, `_hidden_forum_ids` | forum list and view, unread markers (`forum_gelesen.py`), the notification poll (`views/notify.py`) | read a group-restricted forum without being in the group |
| `manage_forum_permissions` | `views/forums.py` · `forum_view`, `forum_permissions` | `/intern/forum/<id>/`, `/intern/forum/<id>/zugriff/` | the „Zugriff" link and editing the `ForumPermission` rows |
| `view_forum_archiv` | `views/forums.py` · `darf_forum_archiv` (via `_forum_access`, `_hidden_forum_ids`) | forum list and view, unread markers, notification poll | see and read archived forums — explicit grant only, superusers included |
| `view_forum_archiv` | `views/forums.py` · `forum_edit`, `forum_reaktivieren` | `/intern/forum/<id>/edit/`, `…/reaktivieren/` | „Reaktivieren" instead of „Forum deaktivieren" |

## Orte

| Right | Code location | URL | Purpose |
|---|---|---|---|
| `add_ort` | `views/orte.py` · `ort_list`, `ort_add` | `/intern/ort/`, `/intern/ort/add/` | the „+" button and creating a location |
| `add_ort` | `views/karte.py` · `karte_ort_create` | `/intern/karte/ort/` | create a location from the map |
| `change_ort` | `views/orte.py` · `ort_view`, `ort_edit` | `/intern/ort/<id>/`, `…/edit/` | edit and history links, editing |
| `change_ort` | `views/aenderungen.py` · `ort_aenderungen` | `/intern/ort/<id>/aenderungen/` | a location's change history |
| `change_ort` | `views/karte.py` · `karte_ort_detail` | `/intern/karte/ort/<pk>/` (POST) | edit a location from the map |
| `delete_ort` | `views/orte.py` · `ort_edit`, `ort_delete` | `/intern/ort/<id>/edit/`, `…/delete/` | the delete card and the deletion |
| `delete_ort` | `views/karte.py` · `karte_ort_detail` | `/intern/karte/ort/<pk>/` (POST `delete`) | delete a location from the map |

## What `/intern/gruppen/` does not show

Every right the code checks with `has_perm()` is in `PERMISSION_DEFS` — no checked right is
missing from the page. The Django default rights that are not listed (e.g. `add_artikel`,
`view_termin`) are checked nowhere and have no effect. These access rules live elsewhere:

| Rule | Where it is set | What it decides |
|---|---|---|
| Superuser („Admin-Status") | `/intern/aufgaben/`, by superusers only (`views/aufgaben.py`) | passes every right above except `view_forum_archiv`; alone opens `/intern/konfiguration/` (`views/konfiguration.py`, sidebar entry); bypasses `FolderPermission` (`folder_access.py`) and sees „Backstage" in breadcrumbs (`views/folders.py` · `_folder_breadcrumb`) |
| `is_staff` | `/admin/` only | access to the Django admin at `/admin/` |
| `FolderPermission` (per folder and group) | `/intern/ordner/<pk>/berechtigungen/` | read, write and delete in that folder and, per axis without an own rule, in its subfolders; with no rule at all read and write are open, delete closed — see `docs/files.md` |
| Standard folders (`folders.PFADE`) | code only | nobody renames, moves or deletes them in the portal, superusers included — nor a folder holding one (`views/folders.py` · `_enthaelt_standardordner`); `/admin/` still can — see `docs/files.md` |
| `ForumPermission` (per forum and group) | `/intern/forum/<id>/zugriff/` | who may read a forum and its MUC room; no rows means open — see `docs/forum.md` |
| `ArtikelPermission` (per article and group) | `/intern/artikel/<name>/berechtigungen/` | who may read and edit an article — see `docs/articles.md` |
| Tags „Mitglied" and „DSGVO" | admission, `/intern/aufgaben/` | the privacy gate for access without membership (`middleware.py`) — see `docs/members.md` |
| Group „Vorstand" (by name) | `/intern/aufgaben/` | the contact list on `/datenschutz/` (`views/auth.py` · `datenschutz`) |
| Own record | — | every member edits their own profile and answers their own `Zusage` without any right |

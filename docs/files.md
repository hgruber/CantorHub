# Files: identity, versions, permissions, retention

Everything about `django-filer` in this project. Two rules dominate and are easy to violate:
a file's identity is its **storage path**, not its row, and the `Profilbilder` folder needs a
second permission axis on top of the folder permissions.

## Files as links

**A file's identity is its storage path.** Two `filer.File` rows pointing at the same `file`
path are the *same file in two folders* — folders work like tags (one invoice under Haus,
Versicherung and Finanzamt). This is filer's own semantics: `File.delete()` drops the blob
only when no other row references that path. Every operation that puts a file into a folder,
or changes its path or name, therefore goes through **`intern/dateiablage.py`** — never touch
`File.file`/`name`/`folder` directly, and never `File.objects.create()` a file into a folder:

| Helper | Purpose |
|---|---|
| `verknuepfte_dateien(f, inklusive_selbst=True)` | all rows sharing `f`'s blob |
| `datei_umbenennen(f, name)` | rename everywhere, no conflict check — the ablage paths call it |
| `datei_loeschen(f)` | remove one occurrence; versions go with the last one |
| `versionen_loeschen(f)` | drop the archived blobs (when the last occurrence goes) |
| `zusammenfuehren(ziel, eingehend, vorne, …)` | merge two chains into one — behind every new revision |
| `hochladen` · `kopieren` · `verknuepfen` · `verschieben` · `umbenennen` · `systemablage(_inhalt)` | the ablage paths, see „One name per folder" |
| `datei_url(pfad)` (`views/files.py`) | the public URL of a storage path, without loading the `File` |
| `besitz_uebertragen(member, fallback)` (`views/files.py`) | hand a departing member's files **and** folders to the owner of the folder above them |

**Copy vs. duplicate:** `folder_link` (button „Verknüpfen") adds a row sharing the blob — the
tag case above. `folder_duplicate` („Duplizieren") copies the blob, giving an independent
file. Both share `_copy_action` / `_copy_folder_deep(…, blob_kopieren)` in `views/folders.py`
and end in `dateiablage.verknuepfen` / `kopieren`. `datei_loeschen` wants a **freshly loaded**
instance — a stale one would have filer delete a blob that is still in use.

## One name per folder

A folder holds **one file per name and one subfolder per name**, compared without regard to
case (MariaDB's `utf8mb4_general_ci` does so anyway; `dateiablage` makes SQLite agree with
`__iexact`/`casefold`). Placing a file on a taken name never adds a second row — the incoming
file becomes a **revision** of the one already there:

| Path | Same name in the target | Same content (any revision of the target) |
|---|---|---|
| Upload (`hochladen`) | new front revision, no question | not stored, the upload card says so |
| Duplicate (`kopieren`) | new front revision dated now, no question | not stored, listed as a hint |
| Link (`verknuepfen`) | ask: merge / cancel | ask: merge without a new revision / cancel |
| Move (`verschieben`) | ask: merge / cancel | ask: delete here / cancel |
| Rename (`umbenennen`, every folder of the file) | ask per folder: becomes a revision / cancel | as for the name, no new revision |
| System (`systemablage`: avatar `<id>.ext`, song files, forum picture, application PDF, `rename_to`, unzip) | new front revision, no question | the existing row is used |
| Folder move, create, rename | refused; a move into the folder itself or one of its subfolders is refused too (`_is_descendant_or_self`, as copying already did) | — |
| Folder copy, unzip | `Name (2)`, as before | — |

**Merging** (`zusammenfuehren`) makes the two files one: both chains become one chain, every
row of both blobs points at the front revision, the row already in the target folder stays and
the incoming one — if it exists — hands its PK references (`verwendung.verweise_umhaengen`,
from the table `DATEI_PK_VERWEISE`) to it and goes.

**The chain is ordered by „Geändert"** (`modified_at` in front, `DateiVersion.datum` behind),
and **the youngest revision is the one in front** — `kette_bilden` sorts, nothing else decides.
An incoming revision that is younger therefore goes in front; when the target is younger the
dialog asks a third question — **date it now** (it gets today's date and goes in front) or
**sort it in** by its date. **Of identical revisions only the oldest stays**: a younger copy
disappears even if it stood in front, and the youngest remaining revision moves up. „Hochgeladen"
(`uploaded_at`) is the moment the row was created and is never rewritten, so a file can show
the oldest upload date and still be in front. A blob nothing points at any more is deleted
after commit.

The decision logic is pure and tested without a database (`kette_bilden`, `konflikt_art`,
`OPTIONEN`, `wahl`, `name_frei`). The browser asks first
(`/intern/ordner/konflikte/` → `window.ablageKlaeren` in `intern.js`, one dialog per conflict
with „für alle übernehmen"); the action then sends `entscheidung=File:<pk>@<ordner>=<wahl>`.
The server re-checks and **skips every conflict without a valid choice** — nothing is merged
silently. Rename answers 409 with the conflicts and is sent again with the choices.

Avatars follow the same rule through `vorschau_url(pfad)` (`models.py`), which builds the
square preview from a storage path. Going through the `File` row costs **two** queries per
row — the file row plus, because filer stores polymorphically, its `Image` row: measured over
50 members, 63 queries and 52.5 ms against 1 query and 8.8 ms, for the same URLs. The member
list therefore annotates `avatar_pfad` and its `avatar` column accesses nothing else; the
preview keeps filer's own `filer_public_thumbnails/` location, because a thumbnailer built
from a bare path would write a second copy next to the source.

`datei_url()` is the one to reach for in a list: a table needs the URL, not the object, and
each `File` filer instantiates brings a `MultiStorageFieldFile` and an easy-thumbnails object
with it. The repertoire list therefore annotates the four song files as paths
(`original_pfad` … in `views/titel.py`) instead of `select_related`, and builds its playlists
from `values_list`. Measured over 206 songs: 72.7 ms with objects, 2.9 ms with paths, the same
URLs; the page went from 228 ms to 110 ms. It applies to public files — which in this portal
is all of them, access is `media_auth`'s job — while a row with `is_public=False` would still
need `File.url`.

## File versions

A new revision (see the table above) keeps the target's `File` PK — so `Lied`/`Artikel`/
`Forum` references survive — and moves every linked row onto the front blob. The update thus
appears in *all* folders the file sits in. The search index follows: the rows' `DateiIndex`
entries are dropped so a same-size replacement is re-indexed too.

**`DateiVersion`** (`models.py`) records the path and metadata of a revision that is not in
front; the blob itself simply stays where it is. `aktuell` holds the path of the front
revision and chains the history. `datum` is the revision's **own date** (the `modified_at` it
carried), not the moment it was archived — the chain is ordered by it and `nummer` follows that
order; only `zusammenfuehren` writes these rows. A revision has **no name of its own**:
`original_filename` is still recorded but nothing reads it. `/intern/datei/<pk>/`
(`datei_view`, `datei.html`) shows the places a file is linked into (filtered by
`visible_folder_ids` — never reveal folders the member cannot see) plus its version list;
`datei_restore` (`dateiablage.wiederherstellen`) brings a revision to the front by dating it
now — under the ordering rule nothing else would put it there; „Hochgeladen" and the name
stay. Reached from the `#id` badge in the folder listing.

A version blob has **no `File` row** — that is the whole point, and it makes the blob an
orphan by filer's reckoning. **Never run `filer_check --delete-orphans` on this project:** it
walks `filer_public/` and deletes every blob without a matching row, i.e. the entire version
history. When blobs really do need collecting, `cleanup_verwaiste_blobs` is the command that
may: it reads `DateiVersion.pfad` alongside `File.file` (see „Orphaned blobs" below).

Every row of the version table carries a preview (`_vorschau()` in `views/files.py`, 96×96
crop, `.v-vorschau` in `intern.css`); versions are addressed by path, which
`get_thumbnailer()` takes as readily as a `FieldFile`. Because a bare path carries none of
filer's storage config, those thumbnails land *next to the source blob* inside `filer_public/`
instead of under `filer_public_thumbnails/` — harmless, and `versionen_loeschen()` /
`cleanup_dateiversionen` already clean them up via
`get_thumbnailer(v.pfad).delete_thumbnails()`. They are one more reason not to run
`--delete-orphans`. Files with no usable preview (audio, spreadsheets) simply get an empty
cell; `thumbnail_files` never pre-generates any of this, so the first view of a detail page
builds them.

## When a member goes, their files stay — under a new owner

`mitglied_delete` (`views/mitglieder.py`) calls `besitz_uebertragen(member,
fallback=request.user)` before it decides between anonymising and hard-deleting: every
`filer.File` and `filer.Folder` owned by that member is handed to the owner of the folder
above it, walking further up whenever an ancestor belongs to the same member, and falling back
to the deleting person at the root (or for an unfiled file). Without it filer's
`on_delete=SET_NULL` would leave `owner` empty — no name in the listing, and filer's own
permission check (`elif user == self.owner`) loses its owner branch — while an anonymised
member would go on owning files as `geloescht_<id>`.

Two consequences worth knowing:

- **File ownership does not force anonymisation.** It is deliberately no longer part of the
  `has_history` test in `mitglied_delete`: after the transfer nothing in the file area points at
  the member, so a member whose only trace was owning files is really deleted.
  `Mitteilung`, `Artikel` and `Abstimmung` still trigger the anonymising branch.
- **The transfer is called explicitly, never from a `pre_delete` signal** — in the view and,
  for the way around it, in `UserAdmin.delete_model`/`delete_queryset` (`intern/admin.py`).
  Django's deletion collector gathers its `SET_NULL` updates *before* `pre_delete` is sent and
  may write `owner=NULL` over freshly set owners; called before `delete()` there is no race,
  because the collector then finds no rows left. The helper writes through queryset `update()`
  for the same class of reason: `save()` would fire `on_filer_file_saved` and spawn an
  indexing plus three thumbnail threads per file, for a field that affects neither.

## Standard folders

The folders the portal files into on its own sit under **Backstage**, so a member browsing the
archive sees their own folders rather than a dozen system ones. The folder browser lists
Backstage at the root only for holders of `intern.manage_folder_permissions` (the Webmaster
group) — hidden, not locked: it has no `FolderPermission` rows, the pages that use its files, the
search and direct links keep working. An upload without a better folder lands at the **root**
itself (a drop on the browser's root included); its answer carries `"wurzel": true` and the
upload card asks the member to move the file into a folder, so the top level stays tidy.

```
/                      fallback target of every upload without a better folder
Backstage/
  Forenbilder          forum pictures
  Profilbilder         member avatars, see below
  Repertoire/          upload target of the Repertoire page
    Hörbeispiele       Lied.original, Lied.aufnahme
    Notenblätter       Lied.pdf
    Notensatz-Dateien  Lied.noten (capella, MuseScore)
    Probenmitschnitte  imported recordings not tied to a song
  Termin-Anhänge       upload target of the event list
  Wiki-Anhänge         files and pictures used in articles
Verein/                root of the attachment picker in the Rundmail
  Vorstand/            Vorstand-only (FolderPermission rows set by 0003_import)
    Mitgliedsanträge   application and re-confirmation PDFs
```

Next to `PFADE`, `folders.STARTORDNER` lists the choir's initial working folders (Organisation
Chor, Organisation Konzerte, the rest of Verein). `0003_import.py` creates them once after
`PFADE`; the code never looks them up, so members may rename or move them freely. Folder names
must not contain `/` — `StandardOrdnerTest` checks both lists. The Rundmail picker only offers
folders the sender can see, and the send path drops attachments from any other folder.

`intern/folders.py` is the registry: the names are constants there, `PFADE` maps each logical
name to its path from the root, and one accessor per folder (`folders.pdf()` …) resolves that
path level by level and caches the id. `0003_import.py` creates the tree from `PFADE`, in its
order (parents first). Renaming or moving one of these folders would break the lookup, so
**the standard folders are protected**: `folder_rename`, `folder_move` and `folder_delete` refuse
every folder of `PFADE` and every folder holding one (`folders.standard_ids()`), for superusers
too; only `/admin/` can still change them. Should one go missing anyway, its accessor returns
`None` and uploads fall back or fail — except `folders.avatare()`, which recreates
Backstage/Profilbilder, because a profile picture must never be filed elsewhere: `mitglied_edit`
keeps the old avatar rather than link one outside that folder.

**Backstage is a target for webmasters only.** For everyone without
`intern.manage_folder_permissions` the folder pickers (`_build_folder_flat(ohne_backstage=True)`
in the folder browser's action panel and context menu, and `datei_aktionen` for the article file
menu) leave out Backstage and everything below it, and `folder_move` / `_copy_action` refuse such
a target with a 403 — the portal files into these folders on its own, members don't. Who sees
Backstage at the root may also move, link and copy into it (`_sieht_backstage`), e.g. to put a
stray profile picture back. Uploads are
not affected; the Repertoire page uploads there, but only files it can assign to a song: an
upload with `route_by_type` is refused when its extension maps to no song-file type, or when
neither `lied_id` (the Titel page) nor the file name names a song.

**Backstage has no `FolderPermission` rows, deliberately.** A folder is only visible when every
ancestor is readable, so restricting Backstage would hide the song files from members.
`_pdf_ablegen` in `views/auth.py` does not recreate a missing Mitgliedsanträge: a fresh
folder has no rules of its own and would only be as closed as wherever it lands, while holding
membership applications.

## Folder permissions

Access is governed by `FolderPermission(folder, group)` rows, decided by `folder_access()` in
`intern/folder_access.py` on three independent axes — read, write, delete. An axis is *ruled* on
a folder when at least one row carries its flag; the rule admits exactly the groups whose rows
carry it. This is what the editor at `/intern/ordner/<pk>/berechtigungen/` stores: „Wie im
übergeordneten Ordner" or „Nur bestimmte Gruppen" per axis.

- **Inheritance is dynamic and per axis.** Without an own rule an axis takes the rule of the
  nearest ancestor that has one, at every check — a change to a parent reaches the whole branch
  at once. Without any, the default holds: read and write open, delete closed. An own rule
  *replaces* the inherited one and may widen it.
- **Read is bounded by the chain.** A folder is visible only if every read rule on the way to
  the root admits the user, so a widened read rule below a hidden folder shows nothing.
- **Write and delete require read.** Who cannot see a folder cannot write or delete there.
- **Delete** is granted by `intern.delete_folder` or by a delete rule naming one of the user's
  groups — the same mechanics as write with the default inverted. `folder_access()` checks the
  global right itself.
- **The root** (top level) is open for read and write; delete there needs `intern.delete_folder`.
  Folders of the top level may carry a read rule like any other.
- Superusers may everything.

New folders get no rows (`folder_create`); they inherit. `_copy_folder_deep` (used by both
`folder_link` and `folder_duplicate`) gives each copied folder its source's *own* rows only, and
a moved folder keeps its own rows — in both cases whatever the folder had only inherited it
inherits afresh from its new place. The pure rule is `rechte()` / `sichtbare_ordner()`, guarded
by the `Ordnerrechte*`, `OrdnerVererbungTest` and `SichtbareOrdnerTest` classes.

## Avatars are write-protected against other members

The `Profilbilder` folder has no `FolderPermission` rows, so by the rule above every logged-in
member has **write** access to it. Without a second check that means anyone could overwrite,
rename or `datei_restore` someone else's profile picture — and the imported avatar history
reaches back to 2012. Folder permissions cannot fix this: restricting the folder would also
block the self-service upload in `mitglied_edit`, which goes through `upload()` and is checked
against `folder_access()`.

`intern/avatar_access.py` is therefore a second access axis, orthogonal to folder permissions:

- `avatar_mitglied(f)` — the member whose profile picture `f` is, resolved via the
  **`User.avatar` FK, not the `<id>.jpg` naming convention**, and across *all* linked rows
  (`verknuepfte_dateien`): a sibling row in another folder shares the blob and the version
  chain, so acting on it would swap the avatar just the same.
- `darf_avatar_aendern(user, f)` — `False` when `f` is another member's avatar. Holders of
  `intern.change_user` (the permission `mitglied_edit` already requires for foreign profiles)
  and superusers always pass. A file in `Profilbilder` with no resolvable owner (a leftover
  `<id>.jpg` of a member who has since cleared their avatar) is administration-only.
  Everything that is not an avatar returns `True` — normal files are unaffected.

**Every write path on files must call `darf_avatar_aendern()`.** Current call sites:
`datei_restore` and `upload` (the file already holding the final name — after `rename_to` —
is checked *before* the ablage, as are the `rename_to`/`avatar_user_id` parameters, so a
rejection leaves no orphan) in `views/files.py`; `folder_rename`, `folder_move` and
`folder_delete` in `views/folders.py`. Every merge goes through `dateiablage.pruefen`, which
checks the *target* too: another member's avatar is conflict type `gesperrt` and is never
merged into, whichever path leads there.

`datei_view` passes `darf_wiederherstellen` (= `darf_schreiben` **and** `darf_avatar_aendern`)
to `datei.html`, which hides only the restore button. The version list itself stays visible to
everyone — a deliberate choice, not an oversight.

## Breaking references: warn before deleting or renaming

Two kinds of references point at a file, and they break differently:

- **Wiki links** (`[[Datei:name.pdf]]`) address a file by **name**
  (`replacements.internal_links`). They break on **rename**, and on **delete** only when the
  *last* row goes — while another folder still links the file, the name resolves. Note
  `internal_links` must use `filter().first()`, not `get()`: a file linked into several
  folders has several rows, and `get()` would report a live file as broken.
- **Everything else** — `Lied` (original/aufnahme/pdf/noten), `Forum.bild`, `User.avatar` and
  `Konfiguration` keys ending in `_FILE_ID` (Satzung, Beitragsordnung — linked from the public
  join form) — hangs off the **PK**. Those break when that row is deleted, even if the file
  survives elsewhere, and are unaffected by a rename.

`intern/verwendung.py` (`datei_verwendungen(dateien, user, beim_loeschen=True)`) collects
both, honouring that distinction; `Artikel.aktuelle_datei_verweise()` maps file name →
articles over each article's newest version only. Article names the user may not read
(`_artikel_access`) are counted, not named. The endpoint `datei_verwendung`
(`datei/verwendung/`) feeds the confirmation dialogs in `intern.js` (`verwendungenAbfragen` /
`verwendungsDialog`, a native `<dialog>`), which the folder browser opens before deleting and
before renaming. The file detail page shows the same list under „Verwendet in".

On rename the dialog offers **„Links mitziehen"**: `folder_rename` with `links_mitziehen=1`
calls `_wiki_links_umschreiben`, which writes a **new article version** per affected article
(articles are immutable versions, same path as `article_edit`) with the comment „Dateiname
geändert: alt → neu". Articles the user may not edit are skipped and reported back in
`links_uebersprungen`.

## The folder browser's row context menu

`initRowContextMenu` in `intern.js` (right-click or 500 ms long-press) groups its entries by
*what they act on*, separated by rules. An action over every file in a folder belongs to the
folder, not to whichever file happened to be right-clicked, so the two scopes never share a
row:

- **On a file row** — `data-url` (the `/media/…` path) plus `data-audio` → „Abspielen" (a
  one-track queue), and `data-versionen` (a `DateiVersion` row exists) → „Frühere Versionen",
  linking to `datei_view`.
- **On a folder row** — `data-audios` / `data-bilder` carry how many audio files and images
  lie **directly** in that folder, so an entry only appears when there is something to do:
  play them in order, play them shuffled, or open `gallerie_view`.
- **For the folder currently open** there is no row, so the topbar takes over: the gallery
  button (`gallery_url`), plus the generic play menu in `base.html` filled by `folder_view`
  (`play_menu`, `ordner_playlist_count`, and `playlists` under the key `ordner`). That menu's
  handler reads `data-playlist-type` + `data-shuffle` and pulls its queue from
  `#playlists-data`. This one queue *is* embedded, because it is a single known folder and it
  must cover the **whole** folder rather than the loaded page (built from `files_list` after
  sorting, before pagination). `/intern/titel/` does **not**: its three queues cover the whole
  filtered repertoire and came to 72.7 KB in every page view, so the page carries only the
  address (`#playlists-url` → `titel_playlist`, the list's filters minus `sort`/`offset`) and
  the counts for the menu, while `startPlaylistType` in `intern.js` fetches the queue on the
  first click and keeps it for the page. That took the list from 244 to 171 KB (40.4 to
  21.7 KB gzipped).

A folder row's playlist is fetched on click from `folder_playlist`
(`/intern/ordner/<pk>/playlist/`) instead of being embedded — rendering the playlist of every
visible subfolder would bloat the listing. It guards access exactly like `gallerie_view`
(`is_folder_visible` **and** `folder_access`, else 404).

Scope is deliberately **not** recursive anywhere here, matching `gallerie_view` — unlike the
size and item counts in the same table, which do walk the subtree. Playback goes through
`window.startPlayQueue(items, shuffle)`, the mini-player's queue entry point, i.e. the same
`playQueue()` behind `startPlaylist`/`startPlaylistType`.

What counts as playable is decided twice and must stay in sync: `_ist_audio()` (Python, for
records already in memory) and `_audio_filter()` (the same rule as a `Q` for the row counts).
Both read `_AUDIO_ENDUNGEN` — MIME type first, filename extensions as the fallback for uploads
filer typed as `application/octet-stream` — and both honour the same field precedence,
`original_filename` before `name` (which may be NULL). If they drift, a folder row promises a
count its playlist then does not deliver.

`_AUDIO_ENDUNGEN` itself is `intern/medientypen.py`'s `AUDIO_ENDUNGEN`, shared with the wiki
media bar (see `articles.md`); `medientyp()` there applies the same MIME-before-extension order
and additionally knows `VIDEO_ENDUNGEN`. Both lists cover only what a browser actually plays —
`.mkv`, `.avi`, `.wmv` and `.flv` are left out on purpose, so they stay a file link rather than
becoming a dead player. The folder browser keeps reading the constant rather than calling
`medientyp()`, because the `Q` version would have to be taught the same delegation to stay
equivalent.

The search branch of `folder_view` sets none of these and renders no `#Action` panel either,
so it has no context menu at all.

## Indexing and thumbnails

Files uploaded through the app are indexed and thumbnailed immediately via a `post_save`
signal on `filer.File` (`on_filer_file_saved` in `signals.py`): a daemon thread calls
`index_file()` and pre-generates all three thumbnail sizes so the upload response is not
delayed. A semaphore caps concurrent thumbnail threads at 4 to prevent MySQL connection
exhaustion; each thread closes its DB connection when done. The signal is suppressed
(`_migrating.active`) during management commands that bulk-import files.

Folder IDs are hard-coded constants in `settings.py` (`FOLDER_AVATARE = 1`, `FOLDER_MUSIK = 5`
etc.).

## Orphaned blobs: `cleanup_verwaiste_blobs`

A blob can outlive every row that named it. The way that happens in practice is the migration
path: `MIGRATE=1` throws the database away, and because filer gives each imported file a fresh
UUID path (`generate_filename.randomized`), the next import does not overwrite the old set — it
puts a second one beside it. Up to v1.0.0-rc2 `start.sh` deleted `media/` only in the SQLite
branch, so on the MySQL side the volume grew by the full data set on every run. `start.sh` now
clears `media/` for both, and this command recovers what earlier runs left behind.

The rule sits in `intern/blob_aufraeumen.py`, free of database and filesystem so it can be
tested (`VerwaisteBlobsTest`); the command holds the two halves that touch either. It decides by
**directory**, not by individual path, and that is what makes it safe where
`filer_check --delete-orphans` is not:

- **`DateiVersion.pfad` counts as a reference.** A superseded revision has no `File` row by
  construction — the very thing `--delete-orphans` mistakes for garbage.
- **A blob's directory shelters its neighbours.** The 96×96 version previews land *inside*
  `filer_public/` rather than under the thumbnail `base_dir` (see above) and appear in no column
  at all; compared path by path they would look orphaned and be deleted on every run. Since each
  UUID directory belongs to exactly one file, „a known blob lives here" is the right question.
  It also sidesteps reconstructing a thumbnail's source name, which is ambiguous when the
  original name contains `__`.
- **Only the two filer prefixes are considered.** Anything else under `MEDIA_ROOT` is none of
  this command's business.
- **`--min-alter` (default 60 minutes) spares fresh files.** An upload has written its blob
  before its row is committed; without the grace period a cleanup running at that moment deletes
  it out from under the request.

Nothing is deleted without `--loeschen`; the default run only reports count and size. It is
deliberately **not** wired into `start.sh` — unlike the retention jobs it is a repair tool, and
a bad run costs files that no version history holds.

## Retention: what the cleanup jobs actually delete

Two scheduled jobs enforce retention, both started in the background by `start.sh`:

| Job | Deletes | Never touches |
|---|---|---|
| `cleanup_changelog` | `ChangeLog` rows older than 3 years (`timestamp__lt`), a plain queryset `delete()`. Backs the „Speicherdauer" promise in `datenschutz.html` | Any file, any content — only the audit trail |
| `cleanup_dateiversionen` | `DateiVersion` rows **plus** the blob at `v.pfad` via `storage.delete()` and the thumbnails at that path | Live files: a `DateiVersion` blob has no `filer.File` row by construction, so nothing a member can see in a folder is ever a candidate |

`cleanup_dateiversionen` selects by two independent rules, unioned (`_veraltet`):
`datum__lt=now-days` **or** everything past the newest `--keep` per `aktuell` group
(`Meta.ordering = ["-nummer"]`, so `[keep:]` is the oldest tail). A row hit by either rule
goes. `aktuell` is the path of the *live* revision, so grouping by it is grouping by file.

**The command defaults are not what runs.** `start.sh` calls it with `--keep 25 --days 36500`
(≈100 years), which switches the age rule off entirely: in production only the count rule
bites, i.e. each file keeps its newest 25 revisions forever. That is deliberate — the avatar
history imported from the legacy system would otherwise vanish on the next server start, since
those `DateiVersion` rows carry the original file mtime as `datum` (see `../migration.md`).
Consequence to keep in mind: **there is currently no time-based deletion of superseded file
revisions in production.** A revision only disappears when 25 newer ones exist, when the last
`filer.File` occurrence is deleted (`dateiablage.datei_loeschen` → `versionen_loeschen`), or on an
explicit erasure request. If a real time limit is ever wanted, the imported avatar versions
have to be exempted first — a blanket `--days` would take them with it.

Not covered by either job, and worth knowing when answering an Art. 17 request: **deleting a
file removes one occurrence, not the blob** — the blob survives as long as another `File` row
points at the same path. Erasure therefore means deleting *every* linked row, which is exactly
what `datei_verwendungen` shows in the confirmation dialog.

Server logs are the third retention item in „Speicherdauer" (90 days), but they are not this codebase's
job: nginx logs to stdout and Django's `LOGGING` uses a `StreamHandler`, so both land in
journald/`podman logs` and their rotation is a host-side setting.

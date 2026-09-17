# Files: identity, versions, permissions, retention

Everything about `django-filer` in this project. Two rules dominate and are easy to violate:
a file's identity is its **storage path**, not its row, and the `Profilbilder` folder needs a
second permission axis on top of the folder permissions.

## Files as links

**A file's identity is its storage path.** Two `filer.File` rows pointing at the same `file`
path are the *same file in two folders* — folders work like tags (one invoice under Haus,
Versicherung and Finanzamt). This is filer's own semantics: `File.delete()` drops the blob
only when no other row references that path. Every operation that changes a file's path or
name therefore has to carry all its rows along, which is what the helpers in `views/files.py`
are for — use them instead of touching `File.file`/`name` directly:

| Helper | Purpose |
|---|---|
| `verknuepfte_dateien(f, inklusive_selbst=True)` | all rows sharing `f`'s blob |
| `datei_url(pfad)` | the public URL of a storage path, without loading the `File` |
| `datei_umbenennen(f, name)` | rename everywhere — one file, one name |
| `version_anlegen(f, autor)` | archive the current revision before it is replaced |
| `geschwister_nachziehen(alter_pfad, quelle)` | point all rows at the new blob, move the version chain over |
| `versionen_loeschen(f)` | drop the archived blobs (when the last occurrence goes) |
| `besitz_uebertragen(member, fallback)` | hand a departing member's files **and** folders to the owner of the folder above them |

**Copy vs. duplicate:** `folder_link` (button „Verknüpfen") adds a row sharing the blob — the
tag case above. `folder_duplicate` („Duplizieren") copies the blob, giving an independent
file. Both share `_copy_action` / `_copy_folder_deep(…, blob_kopieren)` in `views/folders.py`.
Deleting goes through `_datei_loeschen`, which removes one occurrence and only cleans up
versions when it was the last one — pass it a **freshly loaded** instance, a stale one would
have filer delete a blob that is still in use.

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

**Overwriting** an upload with the same name in the same folder (`upload` in `views/files.py`)
keeps the `File` PK — so `Lied`/`Artikel`/`Forum` references survive — archives the old
revision as a `DateiVersion` and moves every linked row onto the new blob. The update thus
appears in *all* folders the file sits in, and nothing is deleted. The search index follows by
itself (`ensure_indexed` spots a changed `file_size`); the sibling rows' `DateiIndex` entries
are dropped so a same-size replacement is re-indexed too.

**`DateiVersion`** (`models.py`) records the path and metadata of a superseded revision; the
blob itself simply stays where it is. `aktuell` holds the path of the *live* revision and
chains the history — it is rewritten whenever the file moves to a new blob.
`/intern/datei/<pk>/` (`datei_view`, `datei.html`) shows the places a file is linked into
(filtered by `visible_folder_ids` — never reveal folders the member cannot see) plus its
version list; `datei_restore` makes an old revision current again, mirroring the overwrite
path. Reached from the `#id` badge in the folder listing.

A version blob has **no `File` row** — that is the whole point, and it makes the blob an
orphan by filer's reckoning. **Never run `filer_check --delete-orphans` on this project:** it
walks `filer_public/` and deletes every blob without a matching row, i.e. the entire version
history.

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
archive sees their own folders rather than a dozen system ones. Two stay at the root:
**Eingang**, because every upload without a better folder lands there (a drop on the browser's
root included) and members have to find it, and **Mitglieder-Verwaltung** (application and
re-confirmation PDFs, Vorstand-only).

```
Eingang                fallback target of every upload without a better folder
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
Mitglieder-Verwaltung  root of the attachment picker in the Rundmail
```

`intern/folders.py` is the registry: the names are constants there, `PFADE` maps each logical
name to its path from the root, and one accessor per folder (`folders.pdf()` …) resolves that
path level by level and caches the id. `0003_import.py` creates the tree from `PFADE`, in its
order (parents first). Renaming or moving one of these folders in the browser breaks the lookup
— the accessor then returns `None` and uploads fall back or fail.

**Backstage has no `FolderPermission` rows, deliberately.** A folder is only visible when every
ancestor is readable, so restricting Backstage would hide the song files from members.
`_pdf_ablegen` in `views/auth.py` does not recreate a missing Mitglieder-Verwaltung: a fresh
folder would be open to everyone while holding membership applications.

## Folder permissions

Access is governed by `FolderPermission(folder, group)` rows — `folder_access()` in
`intern/folder_access.py` treats a folder *without* rows as **open** for read/write. Any code
that creates a folder must therefore set rows explicitly, or the new folder is world-readable.
`folder_create` copies the parent's rows; `_copy_folder_deep` (used by both `folder_link` and
`folder_duplicate`) gives each copied folder its source folder's own rows and, if the source
was unrestricted, the rows of its new parent (`_perm_specs` / `_apply_perm_specs`) — otherwise
copying a protected folder into an open one would expose its contents.

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
`datei_restore` and `upload` (overwrite branch — checked *before* `version_anlegen`, plus the
`rename_to`/`avatar_user_id` parameters, checked before the `File` row is created so a
rejection leaves no orphan) in `views/files.py`; `folder_rename`, `folder_move` and
`folder_delete` in `views/folders.py`. `folder_link`/`folder_duplicate` need no guard — they
do not change the avatar, and reading is open anyway.

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
  `#playlists-data` — the same path `/intern/titel/` uses. This one queue *is* embedded,
  because it is a single known folder and it must cover the **whole** folder rather than the
  loaded page (built from `files_list` after sorting, before pagination).

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
`filer.File` occurrence is deleted (`_datei_loeschen` → `versionen_loeschen`), or on an
explicit erasure request. If a real time limit is ever wanted, the imported avatar versions
have to be exempted first — a blanket `--days` would take them with it.

Not covered by either job, and worth knowing when answering an Art. 17 request: **deleting a
file removes one occurrence, not the blob** — the blob survives as long as another `File` row
points at the same path. Erasure therefore means deleting *every* linked row, which is exactly
what `datei_verwendungen` shows in the confirmation dialog.

Server logs are the third retention item in „Speicherdauer" (90 days), but they are not this codebase's
job: nginx logs to stdout and Django's `LOGGING` uses a `StreamHandler`, so both land in
journald/`podman logs` and their rotation is a host-side setting.

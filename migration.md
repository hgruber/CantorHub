# One-time migration from the legacy PHP system

Everything in this file exists for the single changeover from the old PHP portal to CantorHub.
**Once the final migration has run, this file and the machinery it describes can be deleted** —
see the checklist at the end. Nothing here is relevant to running CantorHub, which is `INSTALL.md`,
or to developing it, which is `CLAUDE.md`.

## Status

The final migration has run; production was imported with v1.0.4. Since then the `MIGRATE`
path is gone from `start.sh`, and `0002_add_filer.py` — regenerated on every build until then —
is frozen and checked in, so the schema evolves through ordinary migrations from `0004` on
(see „Migrations“ in `CLAUDE.md`). What is left below documents what the import did.

## What `0003_import.py` does

- reads the legacy MySQL database directly and creates users, articles, forums, messages, events,
  songs, locations and votes;
- `seed_konfiguration` writes the choir-specific configuration values (`VEREINSNAME`,
  `VEREINSNAME_KURZ`, `HOMEPAGE_UEBER_UNS`, `HOMEPAGE_AUFNAHME`, …). Those keys carry an
  empty-string default in `intern/apps.py` on purpose, so the codebase stays deployable for
  another organisation without pre-filled choir text;
- sets `_migrating.active = True` around file creation so the `post_save` signal on `filer.File`
  does not spawn an indexing and three thumbnail threads per imported file — a large import would
  otherwise exhaust the MySQL connection limit. The overridden `import_files` command
  (`intern/management/commands/import_files.py`) does the same;
- writes a space into `Termin.extern` for the three upcoming gigs listed in
  `_STARTSEITE_OHNE_TEXT`. They have no announcement text in the legacy system, but the public
  homepage lists events by a non-empty `extern` — and a `MIGRATE=1` run discards everything typed
  into the portal, so that mark has to come from here. The list is a stopgap: a real announcement
  text replaces it entry by entry, and it disappears with this file;
- restricts `Lied.aktiv` to the 18 songs listed in `_AKTIVES_REPERTOIRE`. The legacy column
  `repertoire.aktiv` has collected the choices of past seasons (32 songs); what actually counts
  is the list in the wiki article „Aktuell", section „Repertoire für 2026/27". Its titles are
  written freehand and do not match `Lied.titel`, hence songids rather than titles. The
  Christmas songs are deliberately absent — they carry the separate `weihnacht` flag and the
  table filter „Weihnachten" finds them. Another stopgap that disappears with this file.
- skips every article version dated before 12.12.2015 (`_ARTIKEL_CUTOFF`). The remaining
  versions keep their legacy numbers, so an article's history may start above 1; an article
  whose versions all predate the cutoff is not imported at all.
- lets **only Webmaster, Vorstand and KonzertOrga edit** the article „Aktuell"
  (`artikel_schreibrechte`, `_ARTIKEL_GESCHUETZT`, `_ARTIKEL_SCHREIBGRUPPEN`): one
  `ArtikelPermission` row with `can_edit` per group. Reading stays open; every other article
  carries no row and is open to everyone until someone restricts it.
- gives **only the members of „Gründer" an Eintrittsdatum** — the founding date 17.06.2026
  (`_GRUENDUNGSDATUM`, `import_gruendungsdatum`). Every other account arrives with
  `date_joined=None`; the legacy column `aktiv_seit` is no longer read, because it was
  inconsistent, partly empty and meant the login in the old portal rather than the join date.
  A `date_joined` of `None` plus the tag „Mitglied" is what the portal reads as „never
  taken in": whoever is admitted later through „Mitgliedschaft genehmigen" receives the
  welcome mail and is stamped with that day as their Eintrittsdatum (see `docs/members.md`).
- gives the founding members the **tag „Mitglied"** on top of „Gründer"
  (`import_mitglieder_tag`). The legacy system had no notion of club membership — only
  „aktiv" and the rights table — so the hardcoded founding list is the only membership the
  import knows. „Gründer" itself keeps no function beyond this migration: it steers these
  three steps and is a bare label afterwards, free to be deleted.
- **starts every account outside „Gründer" deactivated** (`deaktiviere_nicht_gruender`), with
  one exception: `legacy_id=232`, the conductor's account, stays active — it needs the portal
  right after the switch. It is deliberately **not** given the tag „Mitglied": the conductor is
  not a club member, and without the tag a later re-activation counts as a reactivation rather
  than a first admission (no welcome mail, no Eintrittsdatum — see `intern/mitgliedschaft.py`).
  The fresh installation therefore has the founding members plus that one account as active
  users; the rest are admitted one by one through „Mitgliedschaft genehmigen", which sets tag
  and `is_active` together. The step has to run after `import_avatars`, which checks
  `u.is_active` and would otherwise give those accounts the placeholder picture instead of
  their photo, and after `import_gruendungsmitglieder`, which fills the group the two steps
  work on.

**This dependency on the legacy MySQL server is why every test in `intern/tests.py` is a
`SimpleTestCase`:** a `TestCase` makes Django build a test database, which runs `0003_import`,
which then blows up anywhere that legacy environment is absent. Logic worth testing is kept free
of DB access and the DB half is isolated in thin wrappers. That constraint disappears with this
file — `0003_import` is empty since October 2026, so normal `TestCase`
tests become possible.

## Avatars and their history

`import_files --path $CANTORHUB_DATA/migration/Avatare` imports the profile pictures into filer; `import_avatars` later
renames that root folder to `Backstage/Profilbilder` (see „Standard folders" in
`docs/files.md`). The `Avatare/` directory
also holds the *superseded* pictures as `<legacy_id>_<md5-prefix>.jpg`, and `import_avatars` in
`0003_import.py` hangs those off the member's current avatar as `DateiVersion` rows (see
`docs/files.md`):

- candidates whose `sha1` equals the current picture's are dropped — the legacy system stored the
  running revision under its hash name too;
- the rest are ordered by **file mtime**, because the name carries no chronology, and get that
  mtime written into `datum` after the fact (`datum` is `auto_now_add`);
- their `File` rows are then removed with a *queryset* `delete()`, which bypasses `File.delete()`
  and so leaves the blob in place. This has to happen **before** the `owner is None` sweep, which
  would otherwise take the blobs with it. Versions of members who were not imported fall to that
  sweep.

Two consequences that outlive the import and are easy to destroy by accident:

- **`start.sh` runs `cleanup_dateiversionen --keep 25 --days 36500`** instead of the command's own
  defaults (`--keep 10 --days 730`). The ≈100-year age limit switches the time rule off entirely,
  because the imported versions carry their original mtime (2012 ff.) and would vanish on the next
  server start. If a real retention limit is ever wanted, exempt the imported avatar versions
  first.
- **Never run `filer_check --delete-orphans`.** A `DateiVersion` blob has no `filer.File` row by
  construction, so the command would delete the entire version history. The migration path therefore
  only runs `thumbnail_files`.

## Legacy passwords

`intern/php_pbkdf2_hasher.py` verifies the password hashes of the old PHP system and is listed in
`PASSWORD_HASHERS` in `settings.py`. Django re-hashes a password with the current default on the
first successful login, so the entry can be dropped once no legacy hash is left in the `auth_user`
table. The stored prefix is the hasher's `algorithm`, `php_sha256`, not the module name:

```sql
SELECT COUNT(*) FROM auth_user WHERE password LIKE 'php_sha256$%';
```

## After the final migration

Everything that belongs to the migration carries a `MIGRATIONSPFAD` marker, so it comes out in
one piece:

- ~~the `if [ -n "${MIGRATE}" ]` block in `start.sh`~~ — removed in October 2026;
- ~~`intern/migrations/0003_import.py`, including its `_migrationsquellen()` helper~~ — emptied
  in October 2026; the file stays as a placeholder because the chain hangs off it;
- ~~the `pymysql` line in `requirements.txt`~~ — removed in October 2026;
- `/data/migration/` in the volume (data only, no code);
- this file, and the references to it in `INSTALL.md` and `CLAUDE.md`.

Then also:

- ~~commit a normal, checked-in migration chain~~ — `0002` frozen in October 2026;
- drop `php_pbkdf2_hasher.py` from `PASSWORD_HASHERS` once the query above returns 0;
- revisit `cleanup_dateiversionen`'s parameters in `start.sh` if a retention limit is wanted;
- drop the `SimpleTestCase`-only rule from `CLAUDE.md` — with `0003_import` gone, tests may use a
  database again.

~~**One thing has to be built before `0003_import` can go**~~ — built in October 2026: the
permission groups, the standard folders and the first administrator of a new installation come
from the first-run setup (`intern/einrichtung.py`, `/einrichtung/`; see `INSTALL.md`).

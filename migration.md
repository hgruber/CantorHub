# One-time migration from the legacy PHP system

Everything in this file exists for the single changeover from the old PHP portal to CantorHub.
**Once the final migration has run, this file and the machinery it describes can be deleted** —
see the checklist at the end. Nothing here is relevant to running CantorHub, which is `README.md`,
or to developing it, which is `CLAUDE.md`.

## `MIGRATE=1` — the fresh-install path

The migration path is a block inside `start.sh`, marked `MIGRATIONSPFAD` at both ends so it can
later be lifted out in one piece. It runs only when `MIGRATE` is set:

```bash
podman run --rm -e MIGRATE=1 \
    -e DATABASE_URL=mysql://cantorhub:secret@db:3306/cantorhub \
    -v cantorhub-data:/data \
    cantorhub:latest

MIGRATE=1 DEBUG=1 ./start.sh      # DEV: runserver, data next to the code
```

The **legacy sources belong in `$CANTORHUB_DATA/migration/`** — that is `/data/migration/public/`
and `/data/migration/Avatare/` in the container. They are needed for this one run only and can be
deleted afterwards; `public/` alone is 2.5 GB and has no business in the image.

It **discards all data**: with `DATABASE_URL` pointing at MySQL it drops every table, otherwise it
deletes the SQLite file — and in both cases the whole `media/` tree goes with it. The blobs belong
to the database that was just thrown away: filer gives every imported file a fresh UUID path, so a
second run would not overwrite them but pile a complete second set on top, growing the volume by
the full data set each time (`public/` alone is 2.5 GB). Until v1.0.0-rc2 the `rm` sat inside the
SQLite branch and the MySQL side did exactly that; `cleanup_verwaiste_blobs` cleans up a volume
where it already happened (see „Orphaned blobs" in `docs/files.md`). That is acceptable only during the current
test phase, where every run rebuilds the portal from the legacy data. Afterwards the test system
simply receives a copy of the production database and starts without `MIGRATE`.

Steps after the wipe:

1. `rm intern/migrations/0002_add_filer.py`, `mv intern/migrations/0003_import.py /tmp`
2. `makemigrations intern --name add_filer` → regenerates `0002` from the current models
3. `migrate` → schema only
4. move `0003_import.py` back, `import_files --path $CANTORHUB_DATA/migration/Avatare`,
   `migrate` again → the data import
5. `createcachetable`, then `index_files` and `thumbnail_files` in the background

The connection to the legacy MySQL is hardcoded in `0003_import.py` (`get_legacy_connection`:
hosts `127.0.0.1` and `10.88.0.4`, user and password `jgf`, database `jg_frankfurt`) and needs no
environment variable — only network access. Without it the migration calls `exit(1)`.

## Why the migrations are numbered the way they are

- `0002_add_filer.py` is **always regenerated** and **must never be committed**. Every model
  change therefore lands in `models.py` and is picked up by the next regeneration — there are no
  hand-written `0004+` migrations in this project, and adding one would break the rebuild.
- `0003_import.py` is moved out of the way while `0002` is generated, because it declares a
  dependency on `0002` and must see it freshly created.
- `createcachetable` is plain DDL, not a migration, and idempotent — which is why it can sit in
  both scripts without colliding with the regeneration rule.

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

**This dependency on the legacy MySQL server is why every test in `intern/tests.py` is a
`SimpleTestCase`:** a `TestCase` makes Django build a test database, which runs `0003_import`,
which then blows up anywhere that legacy environment is absent. Logic worth testing is kept free
of DB access and the DB half is isolated in thin wrappers. That constraint disappears with this
file — once `0003_import` is gone (or learns to no-op without the legacy DB), normal `TestCase`
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

- the `if [ -n "${MIGRATE}" ]` block in `start.sh`;
- `intern/migrations/0003_import.py`, including its `_migrationsquellen()` helper;
- the `pymysql` line in `requirements.txt` — nothing else imports it;
- `/data/migration/` in the volume (data only, no code);
- this file, and the references to it in `README.md` and `CLAUDE.md`.

Then also:

- commit a normal, checked-in migration chain (or squash the regenerated `0002` once) so
  `makemigrations` stops being part of the start-up;
- drop `php_pbkdf2_hasher.py` from `PASSWORD_HASHERS` once the query above returns 0;
- revisit `cleanup_dateiversionen`'s parameters in `start.sh` if a retention limit is wanted;
- drop the `SimpleTestCase`-only rule from `CLAUDE.md` — with `0003_import` gone, tests may use a
  database again.

**One thing has to be built before `0003_import` can go**, and it is the only real entanglement
left: the permission groups (`create_groups`), the standard folders under `Backstage` and the
first administrator exist today *only* because this migration creates them. A fresh install
against an empty database therefore has no groups, no folders and nobody who can log in. That
first-start path is a separate piece of work — it is what a second choir would need, and it is
deliberately not part of the container rework.

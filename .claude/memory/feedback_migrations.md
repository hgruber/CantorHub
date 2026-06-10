---
name: Migration numbering constraint
description: Never create migration files numbered 0004 or higher — all model changes must land in 0002 via models.py
type: feedback
originSessionId: 1acbc71d-2dd1-4bf7-be9a-a3bdaf40c6ed
---
Never generate a migration file with a sequence number above 0003.

**Why:** `migrate.sh` and `start.sh` reset the database and regenerate `0002_add_filer.py` fresh from the current `models.py` state. `0003_import.py` depends on 0002 being newly created. Any migration numbered 0004+ would either (a) try to add fields already present in the regenerated 0002 → error, or (b) never run at all because the chain breaks.

**How to apply:** When model fields are added (e.g. new columns), only change `intern/models.py`. Do not run `makemigrations` and commit the result as 0004+. The regenerated 0002 will pick up all model changes automatically at setup time. If asked to generate a migration, delete any file above 0003 that was created.

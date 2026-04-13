# Matrix Integration — What Was Added

This document describes all code changes introduced between commits `7525a3e` and
`0f35c63`. Use it as a reference if the integration needs to be rebuilt from scratch.

---

## Overview

The integration bridges each CantorHub forum thread to a Matrix room via a Synapse
Application Service. Messages flow in both directions. Files are sent as native Matrix
media events. A shared Matrix Space groups all forum rooms and controls membership.

---

## New dependency: `httpx`

**`requirements.txt`**: added `httpx==0.28.1`.
All Matrix API calls use `httpx` (synchronous, not async).

---

## `config/settings.py`

### Logging

```python
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "intern": {"handlers": ["console"], "level": "INFO"},
    },
}
```

### Matrix settings block (all values read from env vars)

```python
MATRIX_HOMESERVER = os.environ.get("MATRIX_HOMESERVER", "https://matrix.example.org")
MATRIX_AS_TOKEN   = os.environ.get("MATRIX_AS_TOKEN", "")
MATRIX_HS_TOKEN   = os.environ.get("MATRIX_HS_TOKEN", "")
MATRIX_BOT_USER   = os.environ.get("MATRIX_BOT_USER", "@cantorbot:example.org")
MATRIX_ENABLED    = os.environ.get("MATRIX_ENABLED", "0") == "1"
MATRIX_PUBLIC_URL = os.environ.get("MATRIX_PUBLIC_URL", MATRIX_HOMESERVER)
MATRIX_SPACE_NAME = os.environ.get("MATRIX_SPACE_NAME", "CantorHub Forums")
```

`MATRIX_ADMIN_TOKEN` is read directly from `os.environ` at call time in `matrix.py`
(not declared in `settings.py`).

---

## `config/urls.py`

Added three AppService endpoints (outside `/intern/`, no Django login required):

```python
from intern import views_matrix

path("_matrix/app/v1/transactions/<str:txn_id>", views_matrix.appservice_transaction),
path("_matrix/app/v1/users/<path:user_id>",      views_matrix.appservice_user),
path("_matrix/app/v1/rooms/<path:room_alias>",   views_matrix.appservice_room),
```

---

## `intern/models.py`

Two new fields:

```python
# Forum
matrix_room_id = models.CharField(max_length=255, null=True, blank=True, unique=True)

# Mitteilung
matrix_event_id = models.CharField(
    max_length=255, null=True, blank=True, unique=True, db_index=True
)
```

`matrix_event_id` is indexed and unique — used for deduplication when Synapse delivers
inbound events.

---

## `intern/apps.py`

Added a thread-local migration guard and signal wiring:

```python
import threading
from django.apps import AppConfig

_migrating = threading.local()

class InternConfig(AppConfig):
    name = "intern"

    def ready(self):
        from django.db.models.signals import pre_migrate, post_migrate

        def _start_migration(sender, **kwargs):
            _migrating.active = True

        def _end_migration(sender, **kwargs):
            _migrating.active = False

        pre_migrate.connect(_start_migration)
        post_migrate.connect(_end_migration)

        import intern.signals  # noqa: F401
```

`_migrating.active` is `True` during the entire migration run. Signals check this flag
to avoid firing during data import.

---

## `intern/signals.py` (new file)

Three signal handlers:

### `_capture_old_xmpp` (pre_save on User)
Saves the current `xmpp` value before a save so the post_save handler can detect changes.

### `invite_user_on_xmpp_set` (post_save on User)
When `user.xmpp` is set (or changed) to a valid Matrix ID (`@...`), invites the user to
the CantorHub Space. Guards: migration flag, `MATRIX_ENABLED`, unchanged value.

### `create_matrix_room_for_forum` (post_save on Forum)

When a new Forum is created **not** during migration, creates a Matrix room and adds it
to the Space.

Guard order (belt-and-suspenders):
1. `getattr(instance, '_skip_matrix_signal', False)` — set by the import migration
2. `getattr(_migrating, 'active', False)` — thread-local from `apps.py`
3. `settings.MATRIX_ENABLED`
4. `instance.matrix_room_id` already set

Room topic is set to `"CantorHub Forum: {thema}"` — used as a fallback recovery key
during `matrix_sync --sync`.

---

## `intern/migrations/0003_import.py`

Changed every `Forum(...).save()` to suppress the signal:

```python
f = Forum(id=row["id"] or 1, thema=thema)
f._skip_matrix_signal = True
f.save()
```

---

## `intern/matrix.py` (new file)

Full Matrix Application Service client. All calls impersonate the bot via the
`user_id` query parameter (AppService privilege). The `_request()` helper handles
authentication, retry on 429, and timeout errors.

### Key constants / module state

```python
_MAX_RETRIES = 3
_RETRY_CAP   = 5    # max seconds between retries
_space_id    = None # module-level cache, per gunicorn worker
```

### `localpart_from_username(username)`

Derives a valid Matrix localpart from a Django username:
lowercase + replace `[^a-z0-9._-]` with `.` + strip leading/trailing dots.

### `_request(method, path, **kwargs)`

Authenticated Matrix client API call. Appends `user_id=MATRIX_BOT_USER` to every
request (AppService impersonation). Retries on 429 up to `_MAX_RETRIES` times.
Network/timeout errors are raised immediately (no retry).

### `send_message(room_id, text, display_name=None, ts=None)`

Sends a plain-text message. If `ts` is given it is passed as `?ts=<ms>` — Synapse
uses it as `origin_server_ts` (AppService privilege; preserves timestamps for backfill).
Prepends `[display_name]` to the body when provided.

### `upload_file(path, content_type, filename)`

Uploads a local file to the Synapse media store via `/_matrix/media/v3/upload`.
Returns the `mxc://` URI on success, `None` on failure. 60-second timeout.

### `send_file_message(room_id, mxc_uri, filename, content_type, size, msgtype)`

Sends a Matrix media event (`m.image`, `m.audio`, `m.video`, or `m.file`).

### `send_media_from_text(room_id, text)`

Scans `text` for local media URLs (matching `MEDIA_URL`), uploads each file to Synapse
and sends it as a native media event. Called in a background thread after a forum post.

### `create_room(name, topic=None)`

Creates a private Matrix room with `join_rule: restricted` tied to the Space (so any
Space member can join without a per-room invite). Returns `room_id` or `None`.

### `get_space_id()`

Returns the `room_id` of the CantorHub Space, creating it if absent. Result is cached
per process in `_space_id`. The Space is detected by `m.room.create` content
`{"type": "m.space"}`.

### `find_space_in_rooms(room_ids)`

Scans a provided set of room IDs for the Space (avoids an extra `get_joined_rooms`
call during sync).

### `get_room_name(room_id)` / `get_room_topic(room_id)`

Fetch a room's name or topic via state events. Used during `--sync` to build recovery
maps.

### `public_media_url(mxc_uri, filename)`

Converts an `mxc://` URI to a public browser-accessible URL using `MATRIX_PUBLIC_URL`.
The trailing filename gives the URL the file extension `apply_replacements()` needs for
inline rendering.

### `ensure_user(matrix_id)` / `ensure_bot_user()`

Registers a Matrix user as an AppService virtual user via
`POST /_matrix/client/v3/register` (with AS token, no `user_id` param — Synapse rejects
self-impersonation on `/register`). `M_USER_IN_USE` is treated as success. Required
before any profile operation on a user that hasn't logged into Synapse directly.

### `set_bot_avatar(mxc_uri)`

Sets the bot's avatar via a direct `httpx.put()` call **without** the `user_id` query
param. Using `_request()` here causes a Synapse 500 (self-impersonation on profile set
is rejected). Calls `ensure_bot_user()` first to ensure the bot exists in Synapse's DB.

### `create_user(localpart, password=None, displayname=None, avatar_url=None, admin=False)`

Creates or updates a local Synapse user via the admin API:
`PUT /_synapse/admin/v2/users/@{localpart}:{server}`.
Requires `MATRIX_ADMIN_TOKEN` in the environment (must be a `syt_...` access token from
a Synapse admin user — **not** a registration token).
Returns the full Matrix ID on success, `None` on failure.

**Important**: `MATRIX_ADMIN_TOKEN` must be obtained by logging into Synapse as an admin
user (`POST /_matrix/client/v3/login`). The "Registrierungstoken" shown in the Synapse
admin GUI is a *new-user registration token*, not an admin API access token.

### `generate_login_token(matrix_id)`

Generates a short-lived login token via
`POST /_synapse/admin/v1/user/{userId}/login`.
Requires `MATRIX_ADMIN_TOKEN`. Returns the token string or `None`.

### `delete_room(room_id)`

Deletes a room permanently via `DELETE /_synapse/admin/v1/rooms/{room_id}` with
`{"purge": true}`. Requires `MATRIX_ADMIN_TOKEN`. Falls back to `leave_room()` if no
admin token is available.

### Other helpers

- `invite_user(room_id, matrix_id)` — POST invite; treats `M_FORBIDDEN` as a warning.
- `get_joined_rooms()` — returns the bot's current room list.
- `join_room(room_id)` — bot joins a room.
- `leave_room(room_id)` — bot leaves a room.
- `add_room_to_space(space_id, room_id)` — adds a child room to the Space.

---

## `intern/views_matrix.py` (new file)

AppService HTTP endpoints — called by Synapse, not by browsers.
Authentication is via `hs_token` (checked in `_check_hs_token()`).
All views are `@csrf_exempt`.

### `appservice_transaction(request, txn_id)` — PUT

Receives batches of Matrix events from Synapse. For each `m.room.message` event:

1. Skip if `Mitteilung.matrix_event_id` already exists (deduplication).
2. Find the `Forum` by `matrix_room_id`.
3. Skip messages from `MATRIX_BOT_USER` (echo prevention).
4. Map the sender Matrix ID to a `User` via `user.xmpp`.
5. For `m.text`: store the body as a `Mitteilung`.
6. For `m.image`/`m.file`/`m.audio`/`m.video`: convert the `mxc://` URL to a public
   download URL via `public_media_url()` and store that as the message body.
7. Messages from unrecognised Matrix users get a `[username] ` prefix.

### `appservice_user(request, user_id)` — GET

Returns `200 {}` — CantorHub doesn't provision virtual users.

### `appservice_room(request, room_alias)` — GET

Returns `200 {}` — CantorHub doesn't use room aliases.

---

## `intern/views.py`

### `CantorLoginView`

Subclass of `django.contrib.auth.views.LoginView`:

```python
class CantorLoginView(_LoginView):
    template_name = "login.html"
    next_page = "/intern/artikel/Aktuell/"

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.get_user()
        if (settings.MATRIX_ENABLED
                and not user.xmpp
                and os.environ.get("MATRIX_ADMIN_TOKEN")):
            # provision Synapse account in background thread
            ...
        return response
```

Triggers on the user's **first login** (when `user.xmpp` is not yet set). The raw
password is available in `form.cleaned_data["password"]` at this point — it is not
available anywhere else. Provisioning runs in a `threading.Thread(daemon=True)`:

1. Upload the user's filer avatar to Synapse (if present).
2. Call `create_user(localpart, password=password, displayname=..., avatar_url=...)`.
3. On success: `User.objects.filter(pk=user_pk).update(xmpp=matrix_id)`.
4. Invite the user to the CantorHub Space.

### `forum_send` changes

After saving a `Mitteilung`, if `MATRIX_ENABLED` and the forum has a `matrix_room_id`,
sends the message to Matrix in a background thread:

```python
event_id = _matrix.send_message(forum_obj.matrix_room_id, text, display_name=str(request.user))
if event_id:
    Mitteilung.objects.filter(pk=msg.pk).update(matrix_event_id=event_id)
    threading.Thread(
        target=_matrix.send_media_from_text,
        args=(forum_obj.matrix_room_id, text),
        daemon=True,
    ).start()
```

---

## `intern/urls.py`

`CantorLoginView` replaces the inline `auth_views.LoginView`:

```python
path("login/", views.CantorLoginView.as_view(), name="login"),
```

---

## `intern/management/commands/matrix_sync.py` (new file)

Management command for bootstrapping and maintenance. Requires `MATRIX_ENABLED=1`.

```
python manage.py matrix_sync --sync
python manage.py matrix_sync --backfill [--forum PK]
python manage.py matrix_sync --cleanup
python manage.py matrix_sync --cleanup-space
python manage.py matrix_sync --invite
python manage.py matrix_sync --list [--forum PK]
python manage.py matrix_sync --set-bot-avatar FILE
python manage.py matrix_sync --set-space-avatar FILE
python manage.py matrix_sync --create-user USER_PK [--password PASSWORD]
```

### `--sync` (`_do_sync`)

1. Fetch `get_joined_rooms()` once and reuse throughout.
2. Find or create the Space from that list.
3. Call `ensure_bot_user()` (required for profile ops).
4. Build `name_to_room` and `topic_to_room` maps (topic must start with
   `"CantorHub Forum: "`).
5. For each `Forum` without a `matrix_room_id`:
   - Try to recover by name, then by topic (fallback).
   - If no match: create a new room.
6. For every forum room: `join_room()` + `add_room_to_space()` (both idempotent).
7. Detect orphans (bot is in them, no forum maps to them) — **warn only**, never
   auto-delete (auto-deletion caused data loss when recovery failed transiently).
8. Invite all users with a `@`-prefixed `xmpp` to the Space.

### `--backfill` (`_do_backfill`)

Sends all `Mitteilung` records with `matrix_event_id=None` to their forum's Matrix
room in chronological order. Passes `ts=int(msg.datum.timestamp() * 1000)` to
`send_message()` so Synapse records the original timestamp. After each send, stores the
returned `event_id` in `Mitteilung.matrix_event_id` (idempotent — already-sent
messages are skipped).

### `--create-user USER_PK [--password PASSWORD]` (`_do_create_user`)

1. Look up `User` by pk.
2. Derive `localpart` via `localpart_from_username(user.username)`.
3. Upload avatar from filer (if present).
4. Call `matrix.create_user(localpart, password, displayname, avatar_url)`.
5. Update `user.xmpp` if not already set.
6. Invite to Space.
7. If no password given: call `generate_login_token()` and print the one-time token
   (member opens Element → "Sign in" → "Use token").

### `--set-bot-avatar FILE` / `--set-space-avatar FILE`

Upload `FILE` (PNG/JPG) and call `set_bot_avatar()` or set the Space's `m.room.avatar`
state event.

### `--cleanup` / `--cleanup-space`

`--cleanup`: `delete_room()` every forum room the bot is in; clear all
`Forum.matrix_room_id`; preserve the Space.
`--cleanup-space`: delete the Space and clear `_space_id` cache.

---

## `intern/static/intern/js/intern.js`

Added HTMX deduplication handler for the forum message list. The 5-second poll and the
form submit both swap content into `#messages`. If they race, the same message can
appear twice. After every `htmx:afterSwap` on `#messages`, removes any duplicate
`[data-id]` elements:

```js
document.body.addEventListener("htmx:afterSwap", function (evt) {
  const target = evt.detail.target;
  if (!target || target.id !== "messages") return;
  const seen = new Set();
  target.querySelectorAll("[data-id]").forEach((el) => {
    const id = el.dataset.id;
    if (seen.has(id)) {
      el.remove();
    } else {
      seen.add(id);
    }
  });
});
```

---

## `start.sh`

Runs `matrix_sync --sync` automatically on container start when `MATRIX_ENABLED=1`:

```bash
if [ "${MATRIX_ENABLED}" = "1" ]; then
    ./manage.py matrix_sync --sync
fi
```

---

## `synapse.md` (new file)

Operator documentation: Synapse `homeserver.yaml` config, AppService registration
file format, all environment variables, bootstrap commands, how the bridge works, and
troubleshooting tips.

---

## Key design decisions

| Decision | Reason |
|---|---|
| Topic `"CantorHub Forum: {thema}"` set on every room | Fallback recovery key when name lookup fails during `--sync` |
| Orphans: warn only, never auto-delete | Auto-deletion caused permanent data loss when name recovery failed transiently |
| `set_bot_avatar`: direct `httpx.put()`, no `user_id` param | Synapse returns 500 when an AppService sets its own profile via impersonation |
| `ensure_bot_user()` before profile ops | Bot user must exist in Synapse's DB; lazily created on room activity but not for direct profile calls |
| Login provisioning in background thread | Keeps the HTTP response instant; raw password only available in `LoginView.form_valid()` |
| `MATRIX_ADMIN_TOKEN` = admin user's access token | Must be `syt_...` from `POST /_matrix/client/v3/login`; the Synapse admin GUI "Registrierungstoken" is for new-user self-registration, not the admin API |
| `_skip_matrix_signal = True` on Forum instances in migration | Belt-and-suspenders with thread-local `_migrating`; instance flag is more reliable because it's set at the exact call site |

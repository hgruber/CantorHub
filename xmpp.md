# XMPP / ejabberd Integration

Bidirectional bridge between CantorHub forum threads and ejabberd MUC rooms.

## Architecture

```
Forum (Django)                     MUC (ejabberd)
──────────────                     ──────────────
forum_send view ── create Mitteilung ──┐
                                        │ (DB)
ejabberd_bot ── _relay_messages ────────┴──> CantorBot sends groupchat to MUC
(long-running)   (every 3 s, live session)

ejabberd_bot     <──groupchat_message── XMPP user in MUC
(long-running)       │
                     ├── _resolve_sender_jid  (cache → REST: get_room_occupants)
                     ├── _db_store_message     (ORM: create Mitteilung)
                     └── _db_invite_missing_users (REST: send_direct_invitation)
```

Two processes:
1. **Django web process** — `forum_send` only writes the `Mitteilung` to the DB; it does **not** talk to XMPP
2. **`ejabberd_bot` management command** — long-running slixmpp bot that (a) receives MUC messages and stores them as Mitteilung records, (b) **relays new Forum-originated messages to MUC over its own live session** (`_relay_messages`, polled every 3 s), and (c) sends invitations

Forum→MUC deliberately runs through the bot's persistent connection rather than a per-message short-lived connection: the first TLS handshake is intermittently flaky (`RECORD_LAYER_FAILURE`), so opening a fresh connection per message was unreliable (random timeouts) and collided on the `CantorBot` nick with the persistent bot.

All ejabberd admin operations (room config, affiliations, invitations) use the REST API, authenticated as the bot user. The bot JID has admin rights in ejabberd. This avoids cross-domain permission issues (bot JID is on `example.org`, MUC service on `conference.example.net`).

## Model fields

| Model | Field | Purpose |
|---|---|---|
| `User` | `xmpp` (CharField 255, nullable) | User's ejabberd JID, e.g. `holger@example.net`. Used for 1:1 user mapping. |
| `Forum` | `xmpp_muc_jid` (CharField 255, nullable, unique) | MUC room JID, e.g. `forum-42@conference.example.net` |
| `Mitteilung` | `xmpp_stanza_id` (CharField 255, nullable, unique, indexed) | XMPP stanza ID for deduplication |

## Settings

Environment variables (see `config/settings.py`):

```
EJABBERD_API_URL          ejabberd REST API URL, e.g. http://10.88.0.8:5280
EJABBERD_HOST             XMPP domain, e.g. example.net  ← required to enable integration
EJABBERD_MUC_SERVICE      MUC service domain, e.g. conference.example.net
EJABBERD_BOT_JID          Bot JID (also used for REST API auth), e.g. forum@example.org  ← required to enable integration
EJABBERD_BOT_PASSWORD
EJABBERD_BOT_PORT         c2s port (default 5222)
```

The integration is enabled when both `EJABBERD_HOST` and `EJABBERD_BOT_JID` are non-empty (`is_ejabberd_configured()`). There is no separate `EJABBERD_ENABLED` flag. Environment variables take priority over DB values so `docker run -e EJABBERD_HOST=... -e EJABBERD_BOT_JID=...` works without `initial.sh`.

## SASL authentication

The bot uses `sasl_mech="PLAIN"` with slixmpp. This avoids `SCRAM-SHA-1-PLUS` channel binding failures that occur when TLS is terminated by a proxy or uses a self-signed certificate. PLAIN is only sent after the TLS handshake completes (slixmpp enforces `encrypted_plain: True, unencrypted_plain: False`), so credentials are encrypted in transit.

No dedicated unencrypted c2s listener is needed.

## REST API client (`intern/ejabberd.py`)

All calls are `POST /api/<endpoint>` with HTTP Basic auth (bot credentials). A `Host` header is required because HAProxy sits in front of ejabberd.

| Function | ejabberd API | Parameters | Notes |
|---|---|---|---|
| `register_user` | `register` | user, host, password | Returns full JID; 409 = already exists |
| `ensure_bot` | `register` | user, host, password | Idempotent bot account creation |
| `set_user_password` | `change_password` | user, host, newpass | Syncs password changes to ejabberd |
| `set_vcard` | `set_vcard` + `set_vcard2` | user, host, name, avatar_file | Sets FN and PHOTO (base64); avatar_file is a FilerFileField |
| `get_room_members` | `get_room_affiliations` | room, service | Returns `[{username, domain, affiliation, reason}]` — JID reconstructed as `username@domain` |
| `set_room_affiliation` | `set_room_affiliation` | room, service, user, host, affiliation | `host` is the *user* host |
| `get_room_occupants` | `get_room_occupants` | room, service | Returns `[{jid, nick, role}]` — admin API returns real JIDs regardless of room anonymity |
| `get_room_options` | `get_room_options` | room, service | Returns a flat `{option_name: value}` dict (string values), or `None` if room doesn't exist. Use `option_is_true()` to coerce booleans |
| `create_room` | `create_room` | room, service, host | Create a MUC room via REST API; used as fallback when `change_room_option` receives 400 "Room not found" |
| `change_room_option` | `change_room_option` | room, service, option, value | Low-level option setter; auto-recreates the room (via `_ensure_room`) if 400 "Room not found" is returned, then retries once |
| `configure_room` | (multiple `change_room_option`) | muc_jid, title | Enforces `persistent`, `anonymous=true`, `public=false`, `members_only=true`, `allow_user_invites=true`, `lang=de`, and optional `title`. Called on every bot (re)join and `ejabberd_admin sync` |
| `send_invitation` | `send_direct_invitation` | room, service, password, reason, users | `users` is a list of JIDs; `reason` and `password` must be non-empty |
| `unregister_user` | `unregister` | user, host | Delete ejabberd account; returns True/False |
| `destroy_room` | `destroy_room` | room, service | Delete MUC room; returns True/False |

(Forum→MUC sending is **not** a REST call — the bot sends groupchat over its live slixmpp session; see `CantorBot._relay_messages`.)

### REST API quirks

- ejabberd returns JSON `null` for success with no result; `_request()` normalizes to `{}`
- `None` return means HTTP error or string error (caller distinguishes failure from success)
- ejabberd returns a plain JSON string (HTTP 200) for some errors (e.g. `"Unknown host passed in 'service'"`); `_request()` treats any string result as an error and returns `None`
- Retries on HTTP 429 with exponential backoff (max 5 s, 3 attempts)
- `allow_statuses` parameter treats extra status codes as success (e.g. `{409}` for register)
- All room functions use `_split_muc_jid(muc_jid)` to extract `(room_localpart, service)` directly from the JID — they do **not** rely on `EJABBERD_MUC_SERVICE` config; `set_room_affiliation` similarly extracts `user_host` from `user_jid`

## Forum → MUC forwarding (`CantorBot._relay_messages`)

`forum_send` only creates the `Mitteilung`. The persistent bot relays it to MUC on a 3 s timer over its **live** session:

- `_db_init_relay_cursor()` records the highest Mitteilung id at startup, so existing history is not replayed to MUC. The cursor advances only past messages actually sent.
- `_db_pending_forum_messages(after_id)` selects Forum-originated messages (`sender` set, `xmpp_stanza_id` NULL) for forums with a `xmpp_muc_jid`, formatted as `*Full Name*: text` with `rewrite_media_urls()` applied (so `/media/` links become token URLs).
- Each is sent with `self._client.send_message(mto=muc_jid, mbody=body, mtype="groupchat")`. If the room isn't joined yet, the loop stops (cursor not advanced) and retries next cycle, so nothing is lost.
- Echo prevention: the relayed message echoes back under nick `CantorBot` and `_on_muc_message` skips it, so it is not re-stored.

This replaced an earlier per-message short-lived slixmpp connection that was unreliable (flaky first TLS handshake → random timeouts) and collided on the `CantorBot` nick.

**Known gap — `_relay_cursor` is not persistent:** the relay cursor is held only in memory and re-baselined to the highest `Mitteilung` id at each bot **process** start (`_db_init_relay_cursor`). In-process reconnects (TLS blip, auth retry, disconnect) keep the cursor, so they lose nothing. But if the bot **process** restarts while the portal keeps accepting posts, every forum message written during that downtime is treated as already-delivered and never reaches the MUC. This is currently masked because `start.sh`/`migrate.sh` wipe the DB on each start (test phase only). Once that wipe is gone after the final migration, the gap becomes real. Fix when it matters: persist the last-relayed `Mitteilung` id (DB/file) instead of taking the max at startup, so a bot restart replays the downtime window instead of skipping it. A supervisor/restart policy for the bot (it currently runs as a bare `&` background process in `start.sh` with no auto-restart) reduces the downtime window but does not remove the gap.

## MUC → Forum forwarding (`intern/management/commands/ejabberd_bot.py`)

### Bot startup

1. Connects to ejabberd c2s (port from `EJABBERD_BOT_PORT`) using SASL PLAIN
2. `session_start`: joins all MUC rooms from DB with `maxhistory="20"`, starts 60 s rescan timer
3. For each new room: waits 2 s for creation, then calls `configure_room(muc_jid, title)` which enforces (via REST `change_room_option`):
   - `title` = Forum topic name
   - `persistent` = `true` (room survives when empty, preserves history)
   - `anonymous` = `true` (semi-anonymous — see note below)
   - `public` = `false` (not listed in disco)
   - `members_only` = `true` (only affiliated members may join)
   - `allow_user_invites` = `true` (members may invite others)
   - `lang` = `de`

   After `configure_room`, the bot also calls `set_room_vcard` to push the Forum's `bild` as the MUC room avatar (if set). This ensures newly created rooms get their avatar immediately after the bot joins, without requiring a manual re-save of the forum.

   These are re-enforced on every (re)join and by `ejabberd_admin sync` for all existing rooms (overwriting manual admin changes).

   **Why semi-anonymous:** OMEMO in a MUC technically requires a non-anonymous room (clients must know every member's real JID to fetch keys). Making the room semi-anonymous (`anonymous=true`) means Conversations/Gajim won't offer OMEMO and default to **unencrypted**, so the bridge can read messages. The bot maps senders to users via a presence-based nick→JID cache (primary) and the admin REST `get_room_occupants` as fallback — see `_resolve_sender_jid`. As room owner/moderator the bot receives real JIDs in MUC presence stanzas even in semi-anonymous rooms. Regular members no longer see each other's real JIDs in their client.

### slixmpp plugins

- `xep_0045` — MUC
- `xep_0199` — Keepalive ping
- `xep_0359` — Unique and Stable Stanza IDs (used for deduplication)

### Message handling (`_on_muc_message`)

1. **Echo prevention**: sender nickname `CantorBot` → skip storage, but still trigger invitations
2. **History detection**: messages with `<delay xmlns="urn:xmpp:delay"/>` (via `msg.get_plugin("delay")`) are replayed room history — these are messages sent **before the bot joined**; they ARE imported (so pre-join history reaches the Forum), but only if they carry a `stanza_id`, so `xmpp_stanza_id` dedup suppresses re-imports on every reconnect
3. **Resolve sender JID**: checks `_nick_jid_cache` (populated from MUC presence stanzas — the bot is room owner/moderator, so ejabberd includes real JIDs in `<x muc#user>` even in semi-anonymous rooms). Falls back to `get_room_occupants` REST API with case-insensitive nick matching and updates the cache. For history, the original sender may have left → resolves to `None` → stored as an anonymous message
4. **Store message**: `_db_store_message` looks up `User.objects.get(xmpp__iexact=sender_jid)` — sender is always mapped via `User.xmpp`, never by nickname. Unresolved senders are stored with `sender=None`; the forum view (`_message.html`) then renders them as **"Unbekannt"** with the `kein_photo.png` fallback avatar via `Mitteilung.sender_name()` / `sender_avatar_url()`. A sender whose `User.xmpp` equals `EJABBERD_BOT_JID` (`Mitteilung.is_from_bot()`) is shown as nick `CantorBot` with `bot.png`. Both fallback images are filer files imported from `Avatare/` (kept by `0003_import.py`, which assigns them an owner so the orphan cleanup does not delete them).
5. **Deduplication**: by `xmpp_stanza_id` (XEP-0359, via `msg.get_plugin("stanza_id")`), falling back to `msg["id"]`, plus content-based (same text + same sender within 5 s = Forum echo)

### Invitation flow

On the first **live** message in a room (including CantorBot-relayed Forum messages, but **not** replayed `<delay/>` history), via the `_maybe_invite` helper:

1. `get_room_members` via REST → current affiliations
2. For each active `User` with `xmpp` not in the room: `send_direct_invitation` with `reason = "CantorHub Forum: Full Name"`, then `set_room_affiliation(..., "member")` so the user appears in future affiliation queries
3. Only runs once per room per bot session (`_invitation_done` set)

This avoids mass invitations on startup — invitations only fire when a live message actually arrives, never from imported history.

### Room history

The bot joins rooms with `maxhistory="20"` to receive recent messages on join. This allows it to:
- See CantorBot echoes from the short-lived sender and trigger invitations
- Import messages that arrived **before the bot joined** (e.g. a room created in a client, chatted in, then the bot joins) into the Forum

History messages (identified by `<delay/>` tags) ARE stored, relying on `xmpp_stanza_id` dedup to avoid duplicates across reconnects; history without a stanza_id is skipped (cannot be deduped safely). Limitation: only the last ~20 messages are replayed, and senders no longer present resolve to anonymous.

### Reconnection

The bot never exits under normal operation:

- **Network disconnect**: reconnects after 5 s via `asyncio.call_later`
- **Auth failure**: retries with exponential backoff (30 s, 60 s, 120 s), then stops after 3 failures
- **Unhandled exceptions**: caught in the `run()` event loop, bot reconnects with a fresh event loop
- **Schedule cleanup**: `_cancel_all_schedules()` clears all slixmpp scheduled events before reconnecting to avoid `ValueError: There is already a scheduled event of name: Whitespace Keepalive`

### Async/sync boundary

slixmpp runs in an async event loop. Django ORM is sync-only. All DB access is wrapped in `asyncio.to_thread()`. REST API calls (httpx) are also sync, so they run inside `asyncio.to_thread()` too.

## Message reactions (XEP-0444)

Emoji reactions on individual forum messages sync both ways. The bot registers
`xep_0444` (reactions) and `xep_0359` (stanza-id / origin-id). Reactions are stored in the
`Reaktion` model (`mitteilung`, `sender`, `reactor_jid`, `emoji`, `origin`). Per XEP-0444 a
reactor's stanza restates that reactor's **full** set for a message, so all paths use
*delete-then-insert per reactor* (reactor identity = `sender` for web, `reactor_jid` for
XMPP).

### Stanza-id capture for forum-originated messages (prerequisite)

Reactions target a message's MUC stanza-id (XEP-0359). Inbound MUC messages already store
it in `Mitteilung.xmpp_stanza_id`. Forum-originated messages relayed by the bot previously
had **no** stanza-id (the CantorBot echo is dropped). So `_relay_messages` now builds the
outgoing groupchat message with an **origin-id** `cantorhub-<mitteilung_id>`; when the echo
arrives, `_capture_forum_stanza_id` reads that origin-id and writes the room-assigned
`<stanza-id>` back onto the Mitteilung (only when still NULL). Body storage stays suppressed
— only the id is backfilled. `_db_pending_forum_messages` is unaffected: its discriminator
is `xmpp_stanza_id IS NULL` **and** `id > _relay_cursor`, and the cursor has already advanced
past a relayed message, so the late id-set never causes a re-send.

### XMPP → Web (inbound)

Reaction stanzas carry no `<body>`, so `_on_muc_message` checks for the reactions plugin
**before** the `if not body` return. CantorBot's own reaction echoes are skipped (no
re-import → no loop). Otherwise `_handle_reaction` resolves the reactor JID (presence cache →
REST) and `_db_store_xmpp_reaction` finds the Mitteilung by `xmpp_stanza_id == reactions.id`,
replaces that reactor's `origin="xmpp"` set, and maps the JID to a `User` for display. It
does **not** set `reactions_dirty` (no rebroadcast).

### Web → XMPP (outbound, bot-union)

`forum_react` toggles the user's `origin="web"` reaction and sets `Mitteilung.reactions_dirty`.
The bot's `_relay_reactions` task (3 s, like the message relay) takes dirty messages that have
a known stanza-id and room, and sends the **union** of their `origin="web"` emojis as the
bot's own reaction set (`xep_0444.set_reactions`). The dirty flag is cleared *before*
computing/sending so a concurrent toggle at worst triggers a harmless idempotent re-send,
never a lost update; a message whose stanza-id isn't captured yet stays dirty and is retried.

**Bot-attribution limitation:** XEP-0444 attributes a reaction to the sending JID. Since the
bridge sends web reactions under the bot JID, XMPP clients show **all** web reactions bundled
as a single `CantorBot` reaction set (the union). XMPP→Web and Web→Web are per-person correct;
only Web→XMPP collapses this way. `origin="xmpp"` reactions are excluded from the union, so
native XMPP reactions are never rebroadcast.

Surfacing the *number* of web approvals in XMPP (e.g. a `👍 5` chip) was considered and
**deliberately rejected**: XEP-0444 encodes *who* reacted, not *how many*, and the bot is a
single JID. Embedding the count in the reaction text (`👍 5`) is technically sendable
(slixmpp's `is_emoji` is a permissive `True` stub, so nothing is stripped) but (a) does not
merge with native `👍` reactions — it shows as a separate chip — and (b) may be filtered by
strict clients. The plain-emoji union is kept; exact per-person counts live in the web UI.

**Restart gap:** like the `_relay_cursor` gap, stanza-ids for messages relayed while the bot
**process** is down aren't captured, so reactions to those specific messages don't round-trip.
Acceptable during the DB-wipe test phase; improvable later via MAM.

## Forum edit page (`forum_edit`)

`/intern/forum/<id>/edit/` lets admins set `thema`, `bild`, and (when ejabberd is configured) `xmpp_muc_jid`. When ejabberd is configured (`is_ejabberd_configured()`), the MUC JID is auto-derived as `forum-{id}@{EJABBERD_MUC_SERVICE}` if not set; the first invite also persists it to the DB so the bot picks it up. XMPP sections are hidden entirely when ejabberd is not configured (no fallback). When enabled, the page shows: a room-info card (exists, persistent, members\_only, public, moderated, anonymous, allow\_user\_invites, lang, title, owners with bot marker, bot presence via `get_room_options`), invited (affiliations `member`/`admin`/`owner`), attending (occupants), without invitation (active users with xmpp not in affiliations), without XMPP account, and **Gäste/Fremde** (occupants whose bare JID matches no active user and is not the bot JID). The invite button calls `ejabberd.set_room_affiliation(..., "member")` silently.

`get_room_options` returns a flat `{option_name: value}` dict (all values are strings, e.g. `"true"`); `ejabberd.option_is_true(options, key)` coerces them to bool (handles string/JSON-bool/list-of-objects formats across ejabberd versions). The "Besitzer" of a bot-created room is the bot JID itself (it created the room by joining first); `owner_is_bot` flags this in the UI.

### Room avatar sync (`_sync_forum_avatar`)

When `bild` is set or changed, `_sync_forum_avatar(forum_obj)` is called (best-effort) to push the image as MUC room avatar via `ejabberd.set_room_vcard(muc_jid, avatar_file, name)`. This sets the `vcard` room option via `change_room_option` (XEP-0054 vcard-temp XML with `PHOTO/TYPE/BINVAL`). Clients like Conversations fetch the room vCard via IQ and show the avatar. Two quirks found in testing:

1. ejabberd's fxml parser requires **double-quoted** XML namespace attributes — single quotes cause a 500 internal_error.
2. `vcard_xupdate="external"` via `change_room_option` returns 500 — the accepted format is the hex SHA1 hash of the raw image bytes, which ejabberd then includes in the room presence (XEP-0153) so clients like Conversations automatically fetch and display the avatar.

Called from `forum_edit` (on every save, idempotent) and `forum_add` (if bild set on creation); no crash if the MUC room doesn't exist yet.

## Forum read permissions → MUC affiliations

A forum can be restricted to specific groups (model `ForumPermission`, view
`forum_permissions` at `/intern/forum/<id>/berechtigungen/`, perm
`intern.manage_forum_permissions`). Because the forum is mirrored to a MUC room, the read
restriction must be enforced in ejabberd too, otherwise a removed reader could still read
in their XMPP client. Three sync points (all best-effort, guarded by
`is_ejabberd_configured()`):

1. **On save** — `_reconcile_forum_muc(forum_obj)` (`views/forums.py`): for a restricted
   forum it computes the permitted readers' JIDs (`_allowed_reader_jids`), sets every
   current member that isn't permitted (and isn't the bot) to affiliation `none`, and
   ensures permitted readers are `member`. An unrestricted forum is left untouched.
2. **Bot auto-invite** — `_db_invite_missing_users(room_jid)` (`ejabberd_bot.py`) filters
   its candidate users to the permitted groups when the forum has `ForumPermission` rows.
3. **Manual invite** — `forum_invite` refuses to invite a user who may not read a
   restricted forum.

## Room assignment (`intern/signals.py`)

`post_save` on `Forum`: assigns `forum-{pk}@{EJABBERD_MUC_SERVICE}` to `xmpp_muc_jid`. Guards: `_migrating` thread-local, `_skip_ejabberd_signal` flag, `is_ejabberd_configured()` check.

## User provisioning (`intern/views.py` — `CantorLoginView`)

On first login, if `user.xmpp` is empty, a daemon thread calls `_provision_xmpp_user` which:
1. Calls `ejabberd.register_user(user.username, password)` — creates account with the login password
2. Stores the returned JID in `User.xmpp`
3. Calls `ejabberd.set_vcard()` to upload the user's full name and avatar to ejabberd vCard

This uses a custom `CantorLoginView` that overrides Django's `LoginView.form_valid()` to access the plaintext password from the login form.

## Password sync (`intern/views.py` — `member_passwd`)

When a user changes their password, `member_passwd` calls `ejabberd.set_user_password()` in a daemon thread to keep the ejabberd password in sync. Only triggers if `user.xmpp` is set.

## vCard / avatar sync (`intern/signals.py`)

When a `User` is saved and their `avatar` field has changed, a daemon thread calls `ejabberd.set_vcard()` to update the ejabberd vCard (FN + PHOTO). The pre_save signal captures `old_avatar_id` for change detection.

The `_provision_xmpp_user` function also uploads the vCard on first login, so both initial provisioning and subsequent avatar changes are covered.

## Startup script (`start.sh`)

When `EJABBERD_HOST` and `EJABBERD_BOT_JID` are set as environment variables:
1. `./manage.py ejabberd_admin sync` — registers bot account, assigns MUC JIDs, configures rooms
2. `./manage.py ejabberd_bot &` — starts the bot in background

## Admin management command (`manage.py ejabberd_admin`)

Subcommands are grouped by noun (`bot`, `room`, `user`, `invite`, `server`), plus a top-level `sync` action that runs the full startup synchronization (formerly the separate `ejabberd_sync --sync` command, now merged here).

```
./manage.py ejabberd_admin sync                        # Full sync: ensure bot, assign MUC JIDs, configure rooms

./manage.py ejabberd_admin bot ensure                  # Register/ensure the bot account (idempotent)

./manage.py ejabberd_admin room list                   # List forums and their MUC JIDs
./manage.py ejabberd_admin room assign-jids            # Assign MUC JIDs to forums missing them
./manage.py ejabberd_admin room configure [--forum=<id>]  # Enforce standard options on one/all rooms
./manage.py ejabberd_admin room delete <forum_id>      # Destroy a forum's MUC room (with confirmation)
./manage.py ejabberd_admin room avatar <forum_id>      # Push the forum image (bild) as MUC room avatar
./manage.py ejabberd_admin room members <forum_id>     # List a room's affiliations
./manage.py ejabberd_admin room occupants <forum_id>   # List a room's current occupants
./manage.py ejabberd_admin room options <forum_id>     # Show a room's options

./manage.py ejabberd_admin user list                   # List users with XMPP JIDs
./manage.py ejabberd_admin user delete <username_or_id> # Delete a user's ejabberd account (with confirmation)
./manage.py ejabberd_admin user vcard <username_or_id>  # Re-upload vCard (name + avatar)
./manage.py ejabberd_admin user password <username_or_id>  # Set ejabberd password (prompts)

./manage.py ejabberd_admin invite add --forum=<id> --user=<username_or_id>     # Send direct invitation
./manage.py ejabberd_admin invite remove --forum=<id> --user=<username_or_id>  # Remove user from room
./manage.py ejabberd_admin invite clear --forum=<id> [--user=<username_or_id>] # Remove affiliations/invitations (with confirmation)

./manage.py ejabberd_admin server users                # List all registered ejabberd accounts
```

All sub-commands require `EJABBERD_HOST` and `EJABBERD_BOT_JID` to be set. Destructive operations (`room delete`, `user delete`, `invite clear`) prompt for confirmation. User identifiers accept either numeric pk or username string.

`clear_invites` without `--user` removes all members from the room. With `--user`, removes only that user's affiliation.

## ejabberd server configuration

- `mod_http_api` under the `example.net` vhost
- HAProxy injects `Host: example.net` header on the ejabberd backend
- `api_permissions` must allow the CantorHub backend IP for: `register`, `change_password`, `set_vcard`, `set_vcard2`, `get_room_affiliations`, `set_room_affiliation`, `get_room_occupants`, `change_room_option`, `send_direct_invitation`, `destroy_room`, `unregister`

## Cross-domain setup

The bot JID uses `example.org` while the MUC service is on `conference.example.net`. ejabberd rejects admin IQs (affiliation changes, room config) from cross-domain users. All admin operations use the REST API instead, which runs as the admin user and is not subject to this restriction.
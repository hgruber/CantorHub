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
                     ├── _resolve_sender_jid  (REST: get_room_occupants)
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
EJABBERD_ENABLED          "0" / "1"
EJABBERD_API_URL          ejabberd REST API URL, e.g. http://10.88.0.8:5280
EJABBERD_HOST             XMPP domain, e.g. example.net
EJABBERD_MUC_SERVICE      MUC service domain, e.g. conference.example.net
EJABBERD_BOT_JID          Bot JID (also used for REST API auth), e.g. forum@example.org
EJABBERD_BOT_PASSWORD
EJABBERD_BOT_PORT         c2s port (default 5222)
```

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
| `change_room_option` | `change_room_option` | room, service, option, value | Low-level option setter; prefer `configure_room()` for the standard option set |
| `configure_room` | (multiple `change_room_option`) | muc_jid, title | Enforces `persistent`, `anonymous=true`, `public=false`, `members_only=true`, `allow_user_invites=true`, `lang=de`, and optional `title`. Called on every bot (re)join and `ejabberd_sync` |
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

   These are re-enforced on every (re)join and by `ejabberd_sync --sync` for all existing rooms (overwriting manual admin changes).

   **Why semi-anonymous:** OMEMO in a MUC technically requires a non-anonymous room (clients must know every member's real JID to fetch keys). Making the room semi-anonymous (`anonymous=true`) means Conversations/Gajim won't offer OMEMO and default to **unencrypted**, so the bridge can read messages. The bot still maps senders to users via the admin REST `get_room_occupants`, which returns real JIDs regardless of anonymity (server/moderator privilege) — see `_resolve_sender_jid`. Regular members no longer see each other's real JIDs in their client.

### slixmpp plugins

- `xep_0045` — MUC
- `xep_0199` — Keepalive ping
- `xep_0359` — Unique and Stable Stanza IDs (used for deduplication)

### Message handling (`_on_muc_message`)

1. **Echo prevention**: sender nickname `CantorBot` → skip storage, but still trigger invitations
2. **History detection**: messages with `<delay xmlns="urn:xmpp:delay"/>` (via `msg.get_plugin("delay")`) are replayed room history — these are messages sent **before the bot joined**; they ARE imported (so pre-join history reaches the Forum), but only if they carry a `stanza_id`, so `xmpp_stanza_id` dedup suppresses re-imports on every reconnect
3. **Resolve sender JID**: calls `get_room_occupants` REST API to map nickname → real JID (bare JID, resource stripped). For history, the original sender may have left → resolves to `None` → stored as an anonymous message
4. **Store message**: `_db_store_message` looks up `User.objects.get(xmpp__iexact=sender_jid)` — sender is always mapped via `User.xmpp`, never by nickname
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

## Room assignment (`intern/signals.py`)

`post_save` on `Forum`: assigns `forum-{pk}@{EJABBERD_MUC_SERVICE}` to `xmpp_muc_jid`. Guards: `_migrating` thread-local, `_skip_ejabberd_signal` flag, `EJABBERD_ENABLED` check.

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

When `EJABBERD_ENABLED=1`:
1. `./manage.py ejabberd_sync --sync` — registers bot account, assigns MUC JIDs
2. `./manage.py ejabberd_bot &` — starts the bot in background

## Admin management command (`manage.py ejabberd_admin`)

```
./manage.py ejabberd_admin delete_forum <forum_id>   # Delete a forum's MUC room (with confirmation)
./manage.py ejabberd_admin delete_user <username_or_id> # Delete a user's ejabberd account (with confirmation)
./manage.py ejabberd_admin clear_invites --forum=<id> [--user=<username_or_id>]  # Remove affiliations/invitations
./manage.py ejabberd_admin invite --forum=<id> --user=<username_or_id>  # Send direct invitation
./manage.py ejabberd_admin remove_user --forum=<id> --user=<username_or_id>  # Remove user from room
./manage.py ejabberd_admin list_rooms   # List forums and their MUC JIDs
./manage.py ejabberd_admin list_users   # List users with XMPP JIDs
./manage.py ejabberd_admin sync_vcard <username_or_id>  # Re-upload vCard (name + avatar)
./manage.py ejabberd_admin sync_password <username_or_id>  # Sync password (prompts for password)
```

All sub-commands require `EJABBERD_ENABLED=1`. Destructive operations (`delete_forum`, `delete_user`, `clear_invites`) prompt for confirmation. User identifiers accept either numeric pk or username string.

`clear_invites` without `--user` removes all members from the room. With `--user`, removes only that user's affiliation.

## ejabberd server configuration

- `mod_http_api` under the `example.net` vhost
- HAProxy injects `Host: example.net` header on the ejabberd backend
- `api_permissions` must allow the CantorHub backend IP for: `register`, `change_password`, `set_vcard`, `set_vcard2`, `get_room_affiliations`, `set_room_affiliation`, `get_room_occupants`, `change_room_option`, `send_direct_invitation`, `destroy_room`, `unregister`

## Cross-domain setup

The bot JID uses `example.org` while the MUC service is on `conference.example.net`. ejabberd rejects admin IQs (affiliation changes, room config) from cross-domain users. All admin operations use the REST API instead, which runs as the admin user and is not subject to this restriction.
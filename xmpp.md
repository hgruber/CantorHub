# XMPP / ejabberd Integration

Bidirectional bridge between CantorHub forum threads and ejabberd MUC rooms.

## Architecture

```
Forum (Django)                     MUC (ejabberd)
──────────────                     ──────────────
forum_send view  ──send_muc_message──> CantorBot in MUC
                 (short-lived slixmpp)

ejabberd_bot     <──groupchat_message── XMPP user in MUC
(long-running)       │
                     ├── _resolve_sender_jid  (REST: get_room_occupants)
                     ├── _db_store_message     (ORM: create Mitteilung)
                     └── _db_invite_missing_users (REST: send_direct_invitation)
```

Two processes:
1. **Django web process** — forwards Forum posts to MUC via short-lived slixmpp connections
2. **`ejabberd_bot` management command** — long-running slixmpp bot that receives MUC messages, stores them as Mitteilung records, and sends invitations

All ejabberd admin operations (room config, affiliations, invitations) use the REST API to avoid cross-domain permission issues (bot JID is on `example.org`, MUC service on `conference.example.net`).

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
EJABBERD_ADMIN_USER       Full admin JID, e.g. admin@example.net
EJABBERD_ADMIN_PASSWORD
EJABBERD_BOT_JID          Bot JID, e.g. forum@example.org
EJABBERD_BOT_PASSWORD
EJABBERD_BOT_PORT         c2s port (default 5222)
```

## SASL authentication

Both the long-running bot and the short-lived sender use `sasl_mech="PLAIN"` with slixmpp. This avoids `SCRAM-SHA-1-PLUS` channel binding failures that occur when TLS is terminated by a proxy or uses a self-signed certificate. PLAIN is only sent after the TLS handshake completes (slixmpp enforces `encrypted_plain: True, unencrypted_plain: False`), so credentials are encrypted in transit.

No dedicated unencrypted c2s listener is needed.

## REST API client (`intern/ejabberd.py`)

All calls are `POST /api/<endpoint>` with HTTP Basic auth. A `Host` header is required because HAProxy sits in front of ejabberd.

| Function | ejabberd API | Parameters | Notes |
|---|---|---|---|
| `register_user` | `register` | user, host, password | Returns full JID; 409 = already exists |
| `ensure_bot` | `register` | user, host, password | Idempotent bot account creation |
| `get_room_members` | `get_room_affiliations` | room, service | Returns `[{jid, affiliation, reason}]` — no `host` param |
| `set_room_affiliation` | `set_room_affiliation` | room, service, user, host, affiliation | `host` is the *user* host |
| `get_room_occupants` | `get_room_occupants` | room, service | Returns `[{jid, nick, role}]` — real JIDs exposed in non-anonymous rooms |
| `change_room_option` | `change_room_option` | room, service, option, value | Used for title, persistent, anonymous |
| `send_invitation` | `send_direct_invitation` | room, service, password, reason, users | `users` is a list of JIDs; `reason` and `password` must be non-empty |
| `send_muc_message` | (slixmpp) | — | Short-lived XMPP connection, configures room, sends groupchat, disconnects |

### REST API quirks

- ejabberd returns JSON `null` for success with no result; `_request()` normalizes to `{}`
- `None` return means HTTP error (caller distinguishes failure from success)
- Retries on HTTP 429 with exponential backoff (max 5 s, 3 attempts)
- `allow_statuses` parameter treats extra status codes as success (e.g. `{409}` for register)

### slixmpp event loop cleanup

`send_muc_message` runs slixmpp in a background thread with its own event loop. On disconnect, all pending tasks must be cancelled and async generators shut down before closing the loop, otherwise slixmpp's `XMLStream.__del__` raises `RuntimeError: Event loop is closed`.

## Forum → MUC forwarding (`intern/views.py`)

After `forum_send` creates a `Mitteilung`, a daemon thread calls `_forward_to_xmpp`:

- Format: `*Full Name*: message text` — Markdown bold for the sender name, which many XMPP clients render as bold
- Uses `ejabberd.send_muc_message()` (short-lived slixmpp connection)
- The short-lived sender configures the room as `persistent=true` and `anonymous=false` before sending, so the message is preserved in room history for late-joining users
- Echo prevention: the bot ignores CantorBot-nicknamed messages from MUC

## MUC → Forum forwarding (`intern/management/commands/ejabberd_bot.py`)

### Bot startup

1. Connects to ejabberd c2s (port from `EJABBERD_BOT_PORT`) using SASL PLAIN
2. `session_start`: joins all MUC rooms from DB with `maxhistory="20"`, starts 60 s rescan timer
3. For each new room: waits 2 s for creation, then configures via REST:
   - `title` = Forum topic name
   - `persistent` = `true` (room survives when empty, preserves history)
   - `anonymous` = `false` (exposes real JIDs for user mapping)

### slixmpp plugins

- `xep_0045` — MUC
- `xep_0199` — Keepalive ping
- `xep_0359` — Unique and Stable Stanza IDs (used for deduplication)

### Message handling (`_on_muc_message`)

1. **History detection**: messages with `<delay xmlns="urn:xmpp:delay"/>` (via `msg.get_plugin("delay")`) are replayed room history — skip storage, but still process CantorBot echoes for invitations
2. **Echo prevention**: sender nickname `CantorBot` → skip storage, but still trigger invitations
3. **Resolve sender JID**: calls `get_room_occupants` REST API to map nickname → real JID (bare JID, resource stripped)
4. **Store message**: `_db_store_message` looks up `User.objects.get(xmpp__iexact=sender_jid)` — sender is always mapped via `User.xmpp`, never by nickname
5. **Deduplication**: by `xmpp_stanza_id` (XEP-0359, via `msg.get_plugin("stanza_id")`), falling back to `msg["id"]`, plus content-based (same text + same sender within 5 s = Forum echo)

### Invitation flow

On first message in a room (including CantorBot-relayed Forum messages):

1. `get_room_members` via REST → current affiliations
2. For each active `User` with `xmpp` not in the room: `send_direct_invitation` with `reason = "CantorHub Forum: Full Name"`
3. Only runs once per room per bot session (`_invitation_done` set)

This avoids mass invitations on startup — invitations only fire when a message actually arrives.

### Room history

The bot joins rooms with `maxhistory="20"` to receive recent messages on join. This allows it to:
- See CantorBot echoes from the short-lived sender and trigger invitations
- Not miss messages that arrived while the bot was disconnected

History messages (identified by `<delay/>` tags) are not stored again in the DB to avoid duplicates.

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

On first login, if `user.xmpp` is empty, a daemon thread calls `ejabberd.register_user()` and stores the returned JID in `User.xmpp`.

## Startup script (`start.sh`)

When `EJABBERD_ENABLED=1`:
1. `./manage.py ejabberd_sync --sync` — registers bot account, assigns MUC JIDs
2. `./manage.py ejabberd_bot &` — starts the bot in background

## ejabberd server configuration

- `mod_http_api` under the `example.net` vhost
- HAProxy injects `Host: example.net` header on the ejabberd backend
- `api_permissions` must allow the CantorHub backend IP for: `register`, `get_room_affiliations`, `set_room_affiliation`, `get_room_occupants`, `change_room_option`, `send_direct_invitation`

## Cross-domain setup

The bot JID uses `example.org` while the MUC service is on `conference.example.net`. ejabberd rejects admin IQs (affiliation changes, room config) from cross-domain users. All admin operations use the REST API instead, which runs as the admin user and is not subject to this restriction.
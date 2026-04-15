# XMPP / ejabberd Integration — Implementation Record

This document describes what was built and what problems remain unsolved,
as input for a fresh architecture design.

---

## What was built

### Model fields

| Model | Field | Purpose |
|---|---|---|
| `User` | `xmpp` (CharField, nullable) | Stores the user's ejabberd JID, e.g. `holger@example.net` |
| `Forum` | `xmpp_muc_jid` (CharField, nullable, unique) | Stores the MUC room JID, e.g. `forum-42@conference.example.net` |
| `Mitteilung` | `xmpp_stanza_id` (CharField, nullable, unique, indexed) | Stores the XMPP stanza ID for deduplication |

### Settings (`config/settings.py`)

All configured via environment variables, with safe defaults:

```
EJABBERD_ENABLED          "0" / "1"
EJABBERD_API_URL          URL of ejabberd REST API, e.g. http://10.88.0.8:5280
EJABBERD_HOST             XMPP domain, e.g. example.net
EJABBERD_MUC_SERVICE      MUC service domain, e.g. conference.example.net
EJABBERD_ADMIN_USER       Full admin JID, e.g. admin@example.net
EJABBERD_ADMIN_PASSWORD
EJABBERD_BOT_JID          Bot JID, e.g. forum@example.org
EJABBERD_BOT_PASSWORD
EJABBERD_BOT_PORT         XMPP c2s port (default 5222)
```

Note: `EJABBERD_BOT_JID` uses domain `example.org` while the MUC service is
on `conference.example.net` — these are different domains on the same server.
This cross-domain setup caused significant permission problems (see issues below).

### REST API client (`intern/ejabberd.py`)

Thin wrapper around ejabberd's `mod_http_api`. All calls are `POST /api/<endpoint>`
with HTTP Basic auth using the admin JID and password. A `Host` header must be set
to the ejabberd vhost because the server sits behind HAProxy which otherwise
routes to the wrong vhost.

Functions:
- `register_user(username, password)` — creates ejabberd account, returns JID
- `ensure_bot()` — idempotent bot account creation, used at startup
- `get_room_members(muc_jid)` — queries `get_room_affiliations`, filters for `"member"`
- `set_room_affiliation(muc_jid, user_jid, affiliation)` — calls `set_room_affiliation`
- `send_muc_message(muc_jid, body)` — one-shot slixmpp connection to post a groupchat message

Known REST API quirks:
- ejabberd returns JSON `null` for commands with no result value; `_request()` normalises
  this to `{}` so callers can use `is None` to detect HTTP-level failures only.
- The `set_room_affiliation` endpoint requires `room` (localpart) + `service`, not a full JID.

### User provisioning (`intern/views.py` — `CantorLoginView`)

On every successful login, if `user.xmpp` is not set, a background daemon thread calls
`ejabberd.register_user()` with the plaintext password captured from the login form,
then writes the returned JID to `User.xmpp`. Subsequent logins are no-ops.

### Forum → MUC room assignment (`intern/signals.py`)

A `post_save` signal on `Forum` fires when a new forum thread is created. It assigns
`forum-{pk}@{EJABBERD_MUC_SERVICE}` to `Forum.xmpp_muc_jid`. Guards prevent this from
running during migrations (`_migrating` thread-local in `apps.py`), when the signal is
explicitly suppressed (`_skip_ejabberd_signal`), or when `EJABBERD_ENABLED=0`.

### Forum → MUC message forwarding (`intern/views.py` — `forum_send`)

After a `Mitteilung` is created, if the forum has a `xmpp_muc_jid`, a daemon thread
calls `ejabberd.send_muc_message()`. This opens a short-lived slixmpp connection,
joins the room, sends a groupchat message, and disconnects.

### MUC → Forum message forwarding (`intern/management/commands/ejabberd_bot.py`)

A long-running management command (`ejabberd_bot`) runs a `slixmpp.ClientXMPP` bot.

On startup:
1. Connects to ejabberd c2s (port 5224 — dedicated unencrypted listener, because SASL
   SCRAM-SHA-1-PLUS channel binding caused auth failures on the default TLS port).
2. `session_start`: joins all MUC rooms from DB, starts a 60-second rescan timer.
3. For each room: waits for `muc::ROOM::got_online` confirmation (event-driven, not a
   blind sleep), then configures the room (name, members-only, no user invites).
4. Checks existing member list via REST API; if empty, attempts to invite all XMPP users.

On message receipt (`groupchat_message` event):
- Detects OMEMO-encrypted payloads and replies with a private message explaining
  that encrypted messages cannot be forwarded.
- Resolves the sender's real bare JID from the room roster via `get_jid_property`.
- Deduplicates via stanza ID stored in `Mitteilung.xmpp_stanza_id`.
- Creates a `Mitteilung` record with the sender mapped to a `User` via `User.xmpp`.

### Startup script (`start.sh`)

When `EJABBERD_ENABLED=1`:
1. `./manage.py ejabberd_sync --sync` — registers bot account, assigns MUC JIDs to
   all forums that don't have one yet.
2. `./manage.py ejabberd_bot &` — starts the bot in the background.

---

## What does not work

### MUC room invitations

Users were never reliably invited to newly created MUC rooms. The following issues
were encountered and partially fixed, but the overall invite flow remained broken:

1. **`_startup_done` flag logic**: Invites were gated on a `_startup_done` boolean
   that was `False` during the startup scan. Any forum that existed when the bot
   started was treated as an "existing" room with no invites. Replaced with a
   member-list check via REST API.

2. **Cross-domain XMPP permission error**: `set_affiliation` IQ sent by the bot
   (`forum@example.org`) to a room on `conference.example.net` was
   rejected by ejabberd with `<not-allowed>` / "Changing role/affiliation is not
   allowed". Root cause: the bot's XMPP domain differs from the MUC service domain;
   ejabberd does not grant owner privileges to cross-domain users for admin IQs.
   Worked around by using the REST API (`set_room_affiliation`) instead.

3. **REST API `set_room_affiliation` returning `null`**: ejabberd returns JSON `null`
   on success; the `_request()` helper treated this as a failure (`None`). Fixed by
   normalising `null` to `{}`.

4. **`remove_event_handler` does not exist**: slixmpp uses `del_event_handler`.
   Fixed.

5. **Despite all fixes, invitation success was not confirmed** before this session
   ended. The last logged state: `set_affiliation` via REST API appears to succeed
   (no error log, null → {} normalisation applied), but it was not verified whether
   the XMPP `invite()` stanza was actually delivered to the client.

### Root architectural tension

The bot JID (`forum@example.org`) and the MUC service (`conference.example.net`)
are on different XMPP domains. ejabberd enforces stricter permission checks for
cross-domain room ownership. This likely affects not just `set_affiliation` but
potentially `get_room_config` / `set_room_config` as well. A bot JID on the same
domain as the MUC service (e.g. `forum@example.net`) would avoid all of
these issues.

Alternatively, all room administration (affiliation, config) could be done
exclusively via the ejabberd REST API (running as admin), with the XMPP bot limited
to joining rooms and sending/receiving messages only.

---

## ejabberd configuration notes

- `mod_http_api` must be declared under the correct vhost (`example.net`),
  not the IP address ejabberd sees on the TCP socket.
- HAProxy must inject `http-request set-header Host example.net` on the
  backend pointing to ejabberd port 5280.
- A dedicated c2s listener on port 5224 with `starttls: false` was added for the bot
  to avoid SCRAM-SHA-1-PLUS channel binding failures.
- `api_permissions` must list the CantorHub backend IP with full access to at least:
  `register`, `get_room_affiliations`, `set_room_affiliation`.
- SASL `PLAIN` is used by the bot (`use_channel_binding = False` in slixmpp).

# Forums: read permissions and reactions

Each forum is also an XMPP MUC room; the bridge itself — relay, invitations, avatar sync, room
invariants — is documented in `xmpp.md`. This file covers what the portal decides.

## Read permissions

Forums are open to every logged-in member by default. Holders of
`intern.manage_forum_permissions` can restrict a forum to specific groups via the lock button on
the forum detail page (`/intern/forum/<id>/zugriff/`, `forum_permissions` view,
`forum_zugriff.html`) — analogous to the article permissions, but **read-only**: there is no
separate write right. Whoever may read a forum may also post; whoever may not read it doesn't
see it at all.

Model `ForumPermission(forum, group)`: the **presence** of any row for a forum marks it
restricted to the listed groups; no row = open. `_forum_access(user, forum_id)` and
`_hidden_forum_ids(user)` in `views/forums.py` mirror `_artikel_access` — holders of
`manage_forum_permissions` always have access. Enforcement covers the forum list/search,
detail/poll/more/send views (403 for non-readers), and the notification bubbles in
`views/notify.py` (restricted Forum/Mitteilung entries are dropped per user).

Because each forum is also an XMPP MUC room, the restriction is synced to ejabberd so it can't be
bypassed in an XMPP client: saving permissions runs `_reconcile_forum_muc` (removes non-reader
affiliations, ensures readers are `member`), the bot's `_db_invite_missing_users` only invites
permitted readers, and `forum_invite` refuses non-readers.

Permission changes are recorded in the audit log: `_audit_forum_permissions` writes a `ChangeLog`
row under `model_name="Forum"` with a `berechtigungen` change (group-name labels, or "Alle
Mitglieder" when open), so it shows up in `forum_aenderungen` next to the regular forum-field
edits. The forum's audited fields are `thema`, `aktiv`, `bild_id`, `xmpp_muc_jid`
(`_AUDIT_FIELDS` in `signals.py`).

## Reactions

Members can react to individual forum messages with emoji (XEP-0444), synced both ways with the
linked MUC room. A reaction bar renders under each message bubble (`_message.html` →
`.reactions` container, populated by `forum.js`); a `+` opens a small picker (fixed quick set
**plus** a free-emoji input). `forum.js` polls `forum_reactions` (JSON) every 5 s and re-renders
all bars, so XMPP-originated reactions appear too; clicks POST to `forum_react` (`X-CSRFToken`
via `getCsrfToken()`). Both views are gated by `_forum_access` — whoever may read a forum may
react.

Model `Reaktion` stores one row per (message, reactor, emoji) with `origin` (`"web"`/`"xmpp"`),
`sender` for display and `reactor_jid` for XMPP-origin rows. XEP-0444 replace semantics (a
reactor's stanza restates their full set) are implemented as delete-then-insert per reactor —
per-reactor uniqueness is enforced in code, not by a DB constraint. The Forum↔MUC relay, the
bot-attribution limitation (web reactions appear in XMPP clients bundled under `CantorBot`) and
the origin-id stanza-id capture are documented in `xmpp.md`.

## Message display fallbacks

`Mitteilung.sender_name()` / `sender_avatar_url()` / `is_from_bot()` fall back to
"Unbekannt" + `kein_photo.png` for `sender=None`, and to nick `CantorBot` + `bot.png` for the bot
JID. `xmpp_stanza_id` deduplicates the bridge, `reactions_dirty` flags web reactions that still
need relaying.

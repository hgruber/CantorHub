# Forums: read permissions, reactions and unread markers

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
**plus** a free-emoji input). `forum.js` polls `forum_reactions` (JSON) every 5 s **while the tab is visible** and
re-renders all bars, so XMPP-originated reactions appear too; clicks POST to `forum_react` (`X-CSRFToken`
via `getCsrfToken()`). Both views are gated by `_forum_access` — whoever may read a forum may
react.

Model `Reaktion` stores one row per (message, reactor, emoji) with `origin` (`"web"`/`"xmpp"`),
`sender` for display and `reactor_jid` for XMPP-origin rows. XEP-0444 replace semantics (a
reactor's stanza restates their full set) are implemented as delete-then-insert per reactor —
per-reactor uniqueness is enforced in code, not by a DB constraint. The Forum↔MUC relay, the
bot-attribution limitation (web reactions appear in XMPP clients bundled under `CantorBot`) and
the origin-id stanza-id capture are documented in `xmpp.md`.

## Unread markers

Members see where new messages arrived since their last visit, in three places: the forum row in
`/intern/forum/` is set in bold and its „Anzahl" column shows the unread count as a badge in
front of the dimmed total (`ForumTabelle.render_anzahl_mitteilungen`, row class `ungelesen`), the
„Forum" sidebar entry gets the same pulsing dot as „Termine" (`nav-item-offen`), and the forum
page draws a „Neu seit Deinem letzten Besuch" divider below the oldest unread message of the
first 25 (none if it lies further back — `forum_view` asks `hat_aeltere_ungelesene()` with one
`exists()` query whether an unread foreign message lies below the window, and `trenner_id()`
stays `None` then). While the oldest unread lies beyond the loaded window, the divider is not
drawn at all; the first `forum_more` page that loads it draws it below that message — `forum_
more` recomputes with the same `trenner_id`/`hat_aeltere_ungelesene` pair, the read marker for
that runs along the sentinel chain as a `bis_id` GET parameter.

Model `ForumGelesen(user, forum, bis_id)` holds, per member and forum, the id of the newest
message seen — an id rather than a date, because `forum_get` polls by `id__gt` and the `datum`
of relayed XMPP messages is not guaranteed to be monotonic. The logic lives in
`intern/forum_gelesen.py` (pure `trenner_id`/`ist_ungelesen`, tested with `SimpleTestCase`; DB
wrapper below it):

- **Marking read.** `forum_view` reads the old marker (for the divider), then raises it to the
  newest loaded message; `forum_get` raises it whenever the poll delivers something, so what
  arrives while the page is open counts as read (`forum_send` runs through `forum_get`).
  `markiere_gelesen` only ever raises — an in-flight poll with an older `last_id` cannot undo
  a visit.
- **Own messages never count**, whether posted on the web or from the member's XMPP client.
  Messages without a sender (unmapped JIDs) do count. This makes the badge and the divider
  disagree by the number of own posts above the marker: the count leaves them out, the divider
  shows them, because they really did arrive since the last visit. Posting in the portal cannot
  produce that gap — `forum_send` runs through `forum_get` and raises the marker past the new
  message — but posting from the XMPP client does, and the difference stays visible until the
  member opens the forum in the portal. Counting own posts as unread, or dragging the marker
  along to the member's newest own message, were both considered and rejected: the first
  contradicts the rule above, the second would silently mark older messages from others as read.
- **Order.** Everything here speaks ids: the marker, `trenner_id` (the smallest unread id),
  the poll (`forum_get`, `id__gt`) and the paging (`forum_more`, `id__lt`) — and so does the
  display, `Mitteilung.Meta.ordering = ["-id"]`. It used to order by `-datum`, which has no
  tiebreaker: `datum` is stored at second resolution, so messages sharing a second came back in
  an undefined order — SQLite returns such a group *ascending* inside a descending list. The
  divider then landed in the middle of that group, and the number of messages visible above it
  differed from the badge by one — upwards or downwards, depending on where the marker sat
  inside the group. The same mismatch could hide a message for good: `forum_view` cut the first
  25 by date and handed on the smallest id it had loaded, while `forum_more` pages by
  `id__lt`, so a tie straddling that boundary left a message in neither half. Ordering by id
  also matches what the live view already did — `forum_get` prepends what arrives
  (`hx-swap="afterbegin"`), regardless of its `datum`. `ForumGelesenTest` pins it.
- **Starting point.** A member without any row yet (feature just deployed, fresh database, new
  member) gets one per forum at its current newest message (`sichere_ausgangspunkt`), so the
  history doesn't show up as new. A forum that appears later without a row — newly created, or
  newly readable after a permission change — counts from 0. `forum_view` calls
  `sichere_ausgangspunkt` as well, but only when the forum it opens has no marker at all:
  opening a forum directly as the very first forum action would otherwise leave the member with
  that single row, and the `exists()` short-circuit would never set up the others.
- **Restricted forums** are excluded through `_hidden_forum_ids`, like everywhere else.
- **Cost.** The sidebar dot is one `exists()` query in `config/context_processors.py`, skipped
  for requests carrying `HX-Request` — partials have no sidebar. `forum_view` pays one more
  `exists()` (`hat_aeltere_ungelesene`) to decide whether the divider can be placed at all, and
  every `forum_more` batch pays it once against its own bottom edge. `forum_get` goes further and
  renders through `render_to_string` **without** a request, so the context processor does not
  run at all: the partial only needs `user`. Both polls carry `[!document.hidden]` /
  a `document.hidden` check, so a forgotten tab stops asking. The poll costs 24 ms and seven
  queries, down from 50 ms and 14. The list uses the conditional count
  `ForumQuerySet.mit_ungelesen(user)` on the join `extra_data()` already makes.

**Limitation:** reading in an XMPP client (Conversations) is not recorded; a member who follows
a forum only on the phone still sees its messages as unread in the portal until they open it
there.

## Cutoff date and deactivated forums

`FORUM_ANZEIGE_AB` (ISO date, read through `app_settings.get_forum_anzeige_ab()`) hides every
message older than that day; nothing is deleted. `Mitteilung.objects` is a `MitteilungManager`
that applies the cutoff to every query, so search, detail, paging, poll, reactions, unread
markers, `forum.mitteilung_set` and the admin all inherit it. Two paths bypass it and are
deliberate: `Mitteilung.alle` (unfiltered — only the XMPP bridge and `has_history` in
`mitglied_delete`), and joins through `mitteilung` (`Count`, `Max`, `mitteilung__…`), which
ignore managers and therefore add `ab_stichtag()` explicitly. `MitteilungStichtagTest` counts
both per file; a new site fails the test until its cutoff handling has been reviewed.

`Forum.aktiv = False` archives a forum: it disappears from the list, search, notification
bubbles and unread dot, and `_forum_access` and `forum_edit` refuse it (403). The only way past
is `intern.view_forum_archiv` („Forum: Archiv"), checked by `darf_forum_archiv()` — deliberately
**not** through `has_perm()`, because superusers would pass that; an archived forum stays hidden
from them too unless the right was granted directly or through a group. `manage_forum_permissions`
lifts only the group restriction. The import deactivates every forum without a message on or
after the cutoff, once; changing `FORUM_ANZEIGE_AB` later does not toggle forums. Where the list
does show one, its row carries `forum-inaktiv` (text in `--t3`, background unchanged) and an
archive icon before the topic. On the edit page an active forum offers „Forum deaktivieren"
(`forum_deaktivieren`, POST, `change_forum`); afterwards a user without the archive right lands on
the forum list. A deactivated forum offers „Reaktivieren" (`forum_reaktivieren`, POST) to archive
holders only.

## Message display fallbacks

`Mitteilung.sender_name()` / `sender_avatar_url()` / `is_from_bot()` fall back to
"Unbekannt" + `kein_photo.png` for `sender=None`, and to nick `CantorBot` + `bot.png` for the bot
JID. `xmpp_stanza_id` deduplicates the bridge, `reactions_dirty` flags web reactions that still
need relaying.

## Forum image in the list

`Forum.bild` is the MUC room avatar (`xmpp.md`) and, in `/intern/forum/`, the optional column
„Bild" in front of „Thema": a round thumbnail from `vorschau_url()` over the annotated
`bild_pfad`/`bild_oeffentlich`, so the column costs no query per row. Columns in
`FORUM_SPALTEN_AUS` (`tables.py`) stay hidden until a member saves a column choice that includes
them; a saved choice from before the column existed lacks it and keeps it hidden too.

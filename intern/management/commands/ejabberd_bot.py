"""
Management command: ejabberd_bot

Long-running slixmpp bot that bridges ejabberd MUC rooms <-> CantorHub forum.
Started as a background process by start.sh/migrate.sh; exits cleanly if ejabberd is not configured.

Responsibilities:
- Joins (and thereby creates) all MUC rooms listed in Forum.xmpp_muc_jid.
- Sets room title, persistent flag, and semi-anonymous mode (so clients don't
  default to OMEMO; the bot resolves real JIDs via presence events/REST API).
- Resolves sender JIDs from MUC presence stanzas (cache) with REST API fallback.
- Rescans every 60 s to pick up newly created forums.
- Forwards inbound groupchat messages to Mitteilung records,
  mapping senders via User.xmpp (not by nickname).
- On first message in a room, invites active XMPP users via send_direct_invitation.

Note: slixmpp runs in an async event loop. Django ORM is synchronous-only,
so all DB access is wrapped in asyncio.to_thread() to avoid
SynchronousOnlyOperation errors.
"""

import asyncio
import logging
from datetime import datetime

from django.core.management.base import BaseCommand

from intern.app_settings import get_config, get_config_int

logger = logging.getLogger(__name__)


def _db_ensure_rooms(joined_rooms):
    """Synchronous DB query: return forums that need MUC rooms joined."""
    from django.db.models import F, Max
    from intern.models import Forum

    forums = (
        Forum.objects.exclude(xmpp_muc_jid=None)
        .exclude(xmpp_muc_jid="")
        .annotate(_last=Max("mitteilung__datum"))
        .order_by(F("_last").desc(nulls_last=True))
    )
    to_join = []
    for forum in forums:
        if forum.xmpp_muc_jid not in joined_rooms:
            to_join.append((forum.pk, forum.xmpp_muc_jid, forum.thema))
    return to_join


def _db_init_relay_cursor():
    """Highest Mitteilung id at startup — forum messages above this get relayed
    to MUC; older ones are treated as already delivered."""
    from django.db.models import Max
    from intern.models import Mitteilung

    return Mitteilung.alle.aggregate(m=Max("id"))["m"] or 0


def _db_pending_forum_messages(after_id):
    """Forum-originated messages (a local sender, no XMPP stanza id) newer than
    after_id that belong to a forum with a MUC room. Returns a list of
    (id, muc_jid, formatted_body) tuples ordered by id."""
    from intern.models import Mitteilung
    from intern.views.media import rewrite_media_urls

    qs = (
        Mitteilung.alle.filter(
            id__gt=after_id,
            sender__isnull=False,
            xmpp_stanza_id__isnull=True,
        )
        .exclude(forum__xmpp_muc_jid__isnull=True)
        .exclude(forum__xmpp_muc_jid="")
        .select_related("forum", "sender")
        .order_by("id")
    )
    result = []
    for m in qs:
        sender_name = str(m.sender) if m.sender else "Anonymous"
        # /media/ URLs are session-protected; XMPP clients need token links.
        body = rewrite_media_urls(f"*{sender_name}*: {m.mitteilung}")
        result.append((m.id, m.forum.xmpp_muc_jid, body))
    return result


def _db_store_message(room_jid, body, sender_jid, stanza_id):
    """Synchronous DB write: store an inbound MUC message as a Mitteilung."""
    from intern.models import Forum, Mitteilung, User

    try:
        forum = Forum.objects.get(xmpp_muc_jid=room_jid)
    except Forum.DoesNotExist:
        logger.warning("ejabberd_bot: unknown MUC room %s, ignoring", room_jid)
        return

    # Deduplicate by stanza ID
    if stanza_id and Mitteilung.alle.filter(xmpp_stanza_id=stanza_id).exists():
        logger.debug("ejabberd_bot: duplicate stanza_id %s, skipping", stanza_id)
        return

    # Deduplicate by content: if the exact text already exists in this forum
    # within the last 5 seconds, skip (Forum echo).
    from django.utils.timezone import now as tz_now
    from datetime import timedelta

    recent_cutoff = tz_now() - timedelta(seconds=5)

    # Map sender via User.xmpp field
    sender_user = None
    if sender_jid:
        try:
            sender_user = User.objects.get(xmpp__iexact=sender_jid)
        except User.DoesNotExist:
            pass

    dup_query = Mitteilung.alle.filter(
        forum=forum,
        mitteilung=body,
        datum__gte=recent_cutoff,
    )
    if sender_user:
        dup_query = dup_query.filter(sender=sender_user)
    else:
        dup_query = dup_query.filter(sender__isnull=True)

    if dup_query.exists():
        logger.debug("ejabberd_bot: recent duplicate in forum #%s, skipping", forum.pk)
        return

    Mitteilung.alle.create(
        forum=forum,
        sender=sender_user,
        mitteilung=body,
        datum=datetime.now(),
        xmpp_stanza_id=stanza_id,
    )
    logger.info(
        "ejabberd_bot: stored message in forum #%s from %s",
        forum.pk,
        sender_jid or "Unknown",
    )



def _db_invite_missing_users(room_jid):
    """Synchronous: invite active XMPP users who aren't in this room yet.

    Respects the forum's read restriction: for a restricted forum only members
    of the permitted groups are invited."""
    from intern.models import Forum, ForumPermission, User
    from intern.ejabberd import get_room_members, send_invitation, set_room_affiliation

    users = User.objects.filter(is_active=True).exclude(xmpp=None).exclude(xmpp="")

    forum = Forum.objects.filter(xmpp_muc_jid=room_jid).first()
    if forum is not None:
        group_ids = list(
            ForumPermission.objects.filter(forum=forum).values_list(
                "group_id", flat=True
            )
        )
        if group_ids:
            users = users.filter(groups__id__in=group_ids).distinct()

    if not users.exists():
        return

    current_members = get_room_members(room_jid)
    member_jids = {jid.lower() for jid, _ in current_members}

    invited = 0
    for user in users:
        if user.xmpp and user.xmpp.lower() not in member_jids:
            nick = f"{user.first_name} {user.last_name}".strip() or user.username
            reason = f"CantorHub Forum: {nick}"
            if send_invitation(room_jid, user.xmpp, reason=reason):
                set_room_affiliation(room_jid, user.xmpp, "member")
                invited += 1

    if invited:
        logger.info(
            "ejabberd_bot: invited %d user(s) to %s",
            invited,
            room_jid,
        )


def _db_capture_stanza_id(mitteilung_id, stanza_id):
    """Backfill the MUC-assigned stanza-id on a forum-originated Mitteilung once
    its CantorBot echo arrives, so reactions can target it. Only sets it when
    still NULL (never overwrites an inbound id)."""
    from intern.models import Mitteilung

    try:
        Mitteilung.alle.filter(
            pk=mitteilung_id, xmpp_stanza_id__isnull=True
        ).update(xmpp_stanza_id=stanza_id)
    except Exception:
        logger.exception("ejabberd_bot: failed to capture stanza_id for #%s", mitteilung_id)


def _db_store_xmpp_reaction(to_id, reactor_jid, emojis):
    """Apply an inbound XMPP reaction set to the Mitteilung whose stanza-id is
    ``to_id``. XEP-0444 replace semantics: the reactor's previous XMPP set for
    this message is fully replaced. Never marks reactions_dirty (no rebroadcast)."""
    from intern.models import Mitteilung, Reaktion, User

    mitteilung = Mitteilung.alle.filter(xmpp_stanza_id=to_id).first()
    if mitteilung is None:
        logger.debug("ejabberd_bot: reaction for unknown stanza_id %s, skipping", to_id)
        return

    sender_user = User.objects.filter(xmpp__iexact=reactor_jid).first()
    Reaktion.objects.filter(
        mitteilung=mitteilung, reactor_jid=reactor_jid, origin="xmpp"
    ).delete()
    if emojis:
        Reaktion.objects.bulk_create(
            [
                Reaktion(
                    mitteilung=mitteilung,
                    sender=sender_user,
                    reactor_jid=reactor_jid,
                    emoji=e,
                    origin="xmpp",
                )
                for e in emojis
            ]
        )
    logger.info(
        "ejabberd_bot: stored %d reaction(s) on #%s from %s",
        len(emojis),
        mitteilung.pk,
        reactor_jid,
    )


def _db_dirty_reaction_candidates():
    """Forum messages whose web-reaction set changed and that have a known MUC
    stanza-id and room. Returns (mitteilung_id, muc_jid, to_id) tuples."""
    from intern.models import Mitteilung

    return list(
        Mitteilung.alle.filter(reactions_dirty=True)
        .exclude(xmpp_stanza_id__isnull=True)
        .exclude(xmpp_stanza_id="")
        .exclude(forum__xmpp_muc_jid__isnull=True)
        .exclude(forum__xmpp_muc_jid="")
        .values_list("id", "forum__xmpp_muc_jid", "xmpp_stanza_id")
    )


def _db_clear_and_get_ranked(mitteilung_id):
    """Clear the dirty flag and return the union of web-origin reaction emojis for
    a message, ranked by frequency (most-reacted first, ties broken by earliest
    reaction). Clearing before the send means a concurrent toggle at worst causes a
    harmless idempotent re-send next cycle, never a lost update."""
    from django.db.models import Count, Min

    from intern.models import Mitteilung, Reaktion

    Mitteilung.alle.filter(pk=mitteilung_id).update(reactions_dirty=False)
    return list(
        Reaktion.objects.filter(mitteilung_id=mitteilung_id, origin="web")
        .values("emoji")
        .annotate(cnt=Count("id"), erste=Min("datum"))
        .order_by("-cnt", "erste")
        .values_list("emoji", flat=True)
    )


class CantorBot:
    """slixmpp-based MUC listener and room manager."""

    def __init__(self, stdout):
        import slixmpp

        self._stdout = stdout
        self._joined_rooms = set()
        self._invitation_done = set()
        self._auth_retries = 0
        self._relay_cursor = None  # highest forum Mitteilung id relayed to MUC
        # nick→bare_jid per room, populated from MUC presence stanzas
        self._nick_jid_cache: dict = {}

        self._client = slixmpp.ClientXMPP(
            get_config("EJABBERD_BOT_JID", ""),
            get_config("EJABBERD_BOT_PASSWORD", ""),
            sasl_mech="PLAIN",
        )
        self._client.register_plugin("xep_0045")  # MUC
        self._client.register_plugin("xep_0199")  # Keepalive ping
        self._client.register_plugin("xep_0359")  # Stanza IDs / origin-id
        self._client.register_plugin("xep_0444")  # Message Reactions

        self._client.add_event_handler("session_start", self._on_session_start)
        self._client.add_event_handler("groupchat_message", self._on_muc_message)
        self._client.add_event_handler("presence", self._on_presence)
        self._client.add_event_handler("failed_auth", self._on_failed_auth)
        self._client.add_event_handler("disconnected", self._on_disconnected)

    def _cancel_all_schedules(self):
        """Cancel all scheduled events on the client to avoid duplicates on reconnect."""
        for name in list(self._client.scheduled_events):
            self._client.cancel_schedule(name)

    def _on_presence(self, pres):
        """Cache MUC nick→bare-JID from room presence stanzas.

        As room owner the bot receives real JIDs in the <x muc#user> element even
        in semi-anonymous rooms (moderator privilege). This cache is the primary
        source for sender resolution; the REST API is only the fallback.
        """
        room_jid = str(pres["from"].bare)
        if room_jid not in self._joined_rooms:
            return
        nick = pres["from"].resource
        if not nick:
            return

        cache = self._nick_jid_cache.setdefault(room_jid, {})

        if pres["type"] == "unavailable":
            cache.pop(nick, None)
            return

        # slixmpp xep_0045 parses <x xmlns="http://jabber.org/protocol/muc#user">
        # and exposes the real JID via pres["muc"]["item"]["jid"].
        real_jid = None
        try:
            real_jid = str(pres["muc"]["item"]["jid"])
        except Exception:
            pass

        if not real_jid or "@" not in real_jid:
            # Fallback: raw XML search
            ns = "http://jabber.org/protocol/muc#user"
            item = pres.xml.find(f"{{{ns}}}x/{{{ns}}}item")
            if item is not None:
                real_jid = item.get("jid", "")

        if real_jid and "@" in real_jid:
            cache[nick] = real_jid.split("/")[0]
            logger.debug("ejabberd_bot: cached %s → %s in %s", nick, cache[nick], room_jid)

    def _resolve_sender_jid(self, room_jid, nickname):
        """Synchronous: resolve a MUC nick to the occupant's bare XMPP JID.

        Checks the presence cache first (populated by _on_presence). Falls back to
        the REST API get_room_occupants with case-insensitive nick matching.
        """
        cache = self._nick_jid_cache.get(room_jid, {})
        if nickname in cache:
            return cache[nickname]

        from intern.ejabberd import get_room_occupants
        occupants = get_room_occupants(room_jid)
        nickname_lower = nickname.lower()
        for jid, nick in occupants:
            if nick == nickname or nick.lower() == nickname_lower:
                bare = jid.split("/")[0]
                self._nick_jid_cache.setdefault(room_jid, {})[nickname] = bare
                return bare

        logger.warning(
            "ejabberd_bot: could not resolve JID for nick %r in %s (occupants: %s)",
            nickname,
            room_jid,
            [n for _, n in occupants],
        )
        return None

    def run(self):
        host = get_config("EJABBERD_HOST", "")
        port = get_config_int("EJABBERD_BOT_PORT", 5222)
        logger.info(
            "ejabberd_bot: connecting to %s:%s as %s",
            host, port, get_config("EJABBERD_BOT_JID", ""),
        )
        self._client.connect((host, port))
        loop = asyncio.get_event_loop()
        while True:
            try:
                loop.run_forever()
            except Exception:
                logger.exception("ejabberd_bot: unhandled exception")
            # If auth failed too many times, the loop was stopped deliberately.
            if self._auth_retries > 3:
                logger.error("ejabberd_bot: stopping due to repeated auth failures")
                return
            logger.info("ejabberd_bot: reconnecting...")
            self._joined_rooms.clear()
            self._cancel_all_schedules()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._client.connect((host, port))

    async def _on_session_start(self, event):
        self._auth_retries = 0
        self._client.send_presence()

        await self._ensure_rooms()

        # Rescan every N s to pick up forums created after the bot started.
        rescan = get_config_int("EJABBERD_BOT_RESCAN_SECONDS", 60)
        self._client.schedule("room_check", rescan, self._ensure_rooms_sync, repeat=True)

        # Relay Forum→MUC over this live session every N s — far more reliable
        # than opening a fresh (TLS-flaky) connection per message.
        relay = get_config_int("EJABBERD_BOT_RELAY_SECONDS", 3)
        self._client.schedule("relay_check", relay, self._relay_check_sync, repeat=True)

        # Relay web-originated reaction changes (union under the bot identity) to
        # their MUC room, im selben Intervall.
        self._client.schedule(
            "reaction_relay_check", relay, self._relay_reactions_sync, repeat=True
        )

        self._stdout.write("ejabberd_bot: ready.")

    def _ensure_rooms_sync(self):
        """Sync wrapper called by slixmpp scheduler."""
        asyncio.ensure_future(self._ensure_rooms())

    def _relay_check_sync(self):
        """Sync wrapper called by slixmpp scheduler."""
        asyncio.ensure_future(self._relay_messages())

    def _relay_reactions_sync(self):
        """Sync wrapper called by slixmpp scheduler."""
        asyncio.ensure_future(self._relay_reactions())

    async def _relay_messages(self):
        """Send new Forum-originated messages to their MUC room via the bot's
        own joined session. The relayed message echoes back under nick
        'CantorBot' and is skipped by echo prevention, so it is not re-stored."""
        if self._relay_cursor is None:
            # Establish a baseline so existing history isn't replayed to MUC.
            self._relay_cursor = await asyncio.to_thread(_db_init_relay_cursor)
            return

        pending = await asyncio.to_thread(
            _db_pending_forum_messages, self._relay_cursor
        )
        for msg_id, muc_jid, body in pending:
            if muc_jid not in self._joined_rooms:
                # Not joined yet — stop so the message isn't skipped; retry later.
                break
            # Tag with an origin-id so the CantorBot echo can be correlated back to
            # this Mitteilung and its MUC stanza-id captured (for reaction targeting).
            outgoing = self._client.make_message(
                mto=muc_jid, mbody=body, mtype="groupchat"
            )
            outgoing["origin_id"]["id"] = f"cantorhub-{msg_id}"
            outgoing.send()
            self._relay_cursor = msg_id
            logger.info(
                "ejabberd_bot: relayed forum message #%s to %s", msg_id, muc_jid
            )

    async def _relay_reactions(self):
        """Send web-originated reaction changes to MUC. All web reactions on a
        message are sent as the bot's own reaction set (their union, ranked by
        frequency — most-reacted emoji first), since XEP-0444 attributes a reaction
        to the sending JID — see docs/xmpp.md."""
        candidates = await asyncio.to_thread(_db_dirty_reaction_candidates)
        for mid, muc_jid, to_id in candidates:
            if muc_jid not in self._joined_rooms:
                # Not joined yet — leave dirty, retry next cycle.
                continue
            emojis = await asyncio.to_thread(_db_clear_and_get_ranked, mid)
            outgoing = self._client.make_message(mto=muc_jid, mtype="groupchat")
            self._client["xep_0444"].set_reactions(outgoing, to_id=to_id, reactions=emojis)
            outgoing.send()
            logger.info(
                "ejabberd_bot: relayed %d reaction(s) for #%s to %s",
                len(emojis),
                mid,
                muc_jid,
            )

    async def _ensure_rooms(self):
        """Join any MUC room that has a Forum mapping but hasn't been joined yet."""
        to_join = await asyncio.to_thread(_db_ensure_rooms, self._joined_rooms)

        new_count = 0
        for forum_pk, muc_jid, thema in to_join:
            if muc_jid in self._joined_rooms:
                continue
            try:
                self._client.plugin["xep_0045"].join_muc(
                    muc_jid, "CantorBot", maxhistory="20"
                )
                self._joined_rooms.add(muc_jid)
                new_count += 1
                logger.info("ejabberd_bot: joined %s (forum #%s)", muc_jid, forum_pk)
                # Wait for ejabberd to finish creating the room before configuring it
                await asyncio.sleep(2)
                await asyncio.to_thread(self._configure_room, muc_jid, thema, forum_pk)
            except Exception as exc:
                logger.error("ejabberd_bot: failed to join %s: %s", muc_jid, exc)

        if new_count:
            self._stdout.write(f"ejabberd_bot: joined {new_count} room(s).")

    @staticmethod
    def _configure_room(muc_jid, title, forum_pk):
        """Apply the standard CantorHub room options (enforced on every join)."""
        from intern.ejabberd import configure_room, set_room_vcard
        from intern.models import Forum
        configure_room(muc_jid, title)
        try:
            forum = Forum.objects.select_related("bild").get(pk=forum_pk)
            if forum.bild:
                set_room_vcard(muc_jid, forum.bild, name=title)
        except Forum.DoesNotExist:
            pass

    def _on_failed_auth(self, event):
        """Handle authentication failure — retry with backoff, then give up."""
        self._auth_retries += 1
        if self._auth_retries > 3:
            logger.error(
                "ejabberd_bot: giving up after %d auth failures for %s — "
                "check EJABBERD_BOT_JID and EJABBERD_BOT_PASSWORD",
                self._auth_retries,
                get_config("EJABBERD_BOT_JID", ""),
            )
            asyncio.get_event_loop().stop()
            return

        delay = min(300, 30 * 2 ** (self._auth_retries - 1))
        logger.error(
            "ejabberd_bot: authentication failed for %s (attempt %d, retry in %ds)",
            get_config("EJABBERD_BOT_JID", ""),
            self._auth_retries,
            delay,
        )
        self._joined_rooms.clear()
        self._cancel_all_schedules()
        asyncio.get_event_loop().call_later(delay, self._reconnect)

    async def _on_muc_message(self, msg):
        """Handle inbound groupchat messages from MUC."""
        room_jid = str(msg["from"].bare)

        # Messages with <delay/> are replayed room history on join — these are
        # messages sent before the bot joined. We DO want to import them, relying
        # on stanza_id dedup so re-joins don't create duplicates.
        is_history = msg.get_plugin("delay", check=True) is not None

        # Echo prevention: in MUC, from = room@service/nickname,
        # so check the resource (nickname) not the bare JID.
        sender_nickname = msg["from"].resource

        # Reaction stanzas (XEP-0444) carry no <body>, so handle them first.
        if msg.get_plugin("reactions", check=True) is not None:
            if sender_nickname == "CantorBot":
                return  # our own relayed reaction echo — never re-import
            await self._handle_reaction(msg, room_jid, sender_nickname)
            return

        body = (msg["body"] or "").strip()

        if sender_nickname == "CantorBot":
            if not is_history:
                # Backfill the room stanza-id onto the forum-originated Mitteilung
                # this echo belongs to, then trigger invitations.
                await self._capture_forum_stanza_id(msg)
                await self._maybe_invite(room_jid)
            return

        if not body:
            return

        stanza_id = msg["id"]
        stanza_id_plugin = msg.get_plugin("stanza_id", check=True)
        if stanza_id_plugin and stanza_id_plugin["id"]:
            stanza_id = stanza_id_plugin["id"]

        # Replayed history can be re-delivered on every reconnect; only import it
        # when it carries a stanza_id, so xmpp_stanza_id dedup can suppress dupes.
        if is_history and not stanza_id:
            return

        # Resolve sender's real XMPP JID from room occupants. For history this may
        # be None (the sender may have left) → stored as an anonymous message.
        sender_jid = await asyncio.to_thread(
            self._resolve_sender_jid, room_jid, sender_nickname
        )

        await asyncio.to_thread(
            _db_store_message, room_jid, body, sender_jid, stanza_id
        )

        # Invite missing users on first live message in this room (not history).
        if not is_history:
            await self._maybe_invite(room_jid)

    async def _maybe_invite(self, room_jid):
        """Invite missing users once per room per bot session."""
        if room_jid not in self._invitation_done:
            self._invitation_done.add(room_jid)
            await asyncio.to_thread(_db_invite_missing_users, room_jid)

    async def _handle_reaction(self, msg, room_jid, sender_nickname):
        """Store an inbound XMPP reaction (XEP-0444) against the targeted message."""
        to_id = msg["reactions"]["id"]
        if not to_id:
            return
        emojis = set(msg["reactions"]["values"])
        reactor_jid = await asyncio.to_thread(
            self._resolve_sender_jid, room_jid, sender_nickname
        )
        if not reactor_jid:
            return
        await asyncio.to_thread(_db_store_xmpp_reaction, to_id, reactor_jid, emojis)

    async def _capture_forum_stanza_id(self, msg):
        """For a CantorBot echo of a relayed forum message, map its origin-id back
        to the Mitteilung and store the room-assigned stanza-id (for reactions)."""
        origin_id = msg["origin_id"]["id"]
        if not origin_id or not origin_id.startswith("cantorhub-"):
            return
        try:
            mitteilung_id = int(origin_id.split("cantorhub-", 1)[1])
        except (ValueError, IndexError):
            return
        stanza_id = msg["stanza_id"]["id"]
        if not stanza_id:
            return
        await asyncio.to_thread(_db_capture_stanza_id, mitteilung_id, stanza_id)

    def _on_disconnected(self, event):
        """Reconnect on disconnection."""
        logger.warning("ejabberd_bot: disconnected, reconnecting...")
        self._joined_rooms.clear()
        self._cancel_all_schedules()
        asyncio.get_event_loop().call_later(5, self._reconnect)

    def _reconnect(self):
        """Attempt to reconnect."""
        host = get_config("EJABBERD_HOST", "")
        port = get_config_int("EJABBERD_BOT_PORT", 5222)
        self._client.connect((host, port))


class Command(BaseCommand):
    """Management command to run the ejabberd bot."""

    help = "Run the ejabberd bot for MUC <-> Forum bridging."

    def handle(self, *args, **options):
        from intern.app_settings import is_ejabberd_configured

        if not is_ejabberd_configured():
            self.stderr.write("EJABBERD_HOST and EJABBERD_BOT_JID must be set.")
            return
        try:
            bot = CantorBot(self.stdout)
            bot.run()
        except Exception:
            logger.exception("ejabberd_bot: fatal startup error")
            raise

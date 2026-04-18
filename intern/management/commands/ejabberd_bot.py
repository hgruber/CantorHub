"""
Management command: ejabberd_bot

Long-running slixmpp bot that bridges ejabberd MUC rooms <-> CantorHub forum.
Started as a background process by start.sh when EJABBERD_ENABLED=1.

Responsibilities:
- Joins (and thereby creates) all MUC rooms listed in Forum.xmpp_muc_jid.
- Sets room title, persistent flag, and non-anonymous mode.
- Resolves sender JIDs via get_room_occupants REST API for User.xmpp mapping.
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

from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


def _db_ensure_rooms(joined_rooms):
    """Synchronous DB query: return forums that need MUC rooms joined."""
    from intern.models import Forum

    forums = Forum.objects.exclude(xmpp_muc_jid=None).exclude(xmpp_muc_jid="")
    to_join = []
    for forum in forums:
        if forum.xmpp_muc_jid not in joined_rooms:
            to_join.append((forum.pk, forum.xmpp_muc_jid, forum.thema))
    return to_join


def _db_store_message(room_jid, body, sender_jid, stanza_id):
    """Synchronous DB write: store an inbound MUC message as a Mitteilung."""
    from intern.models import Forum, Mitteilung, User

    try:
        forum = Forum.objects.get(xmpp_muc_jid=room_jid)
    except Forum.DoesNotExist:
        logger.warning("ejabberd_bot: unknown MUC room %s, ignoring", room_jid)
        return

    # Deduplicate by stanza ID
    if stanza_id and Mitteilung.objects.filter(xmpp_stanza_id=stanza_id).exists():
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

    dup_query = Mitteilung.objects.filter(
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

    Mitteilung.objects.create(
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


def _resolve_sender_jid(room_jid, nickname):
    """Synchronous: look up a MUC occupant's real XMPP JID via REST API."""
    from intern.ejabberd import get_room_occupants

    occupants = get_room_occupants(room_jid)
    for jid, nick in occupants:
        if nick == nickname:
            # jid includes resource (user@host/res), strip to bare JID
            return jid.split("/")[0]
    return None


def _db_invite_missing_users(room_jid):
    """Synchronous: invite active XMPP users who aren't in this room yet."""
    from intern.models import User
    from intern.ejabberd import get_room_members, send_invitation

    users = User.objects.filter(is_active=True).exclude(xmpp=None).exclude(xmpp="")
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
                invited += 1

    if invited:
        logger.info(
            "ejabberd_bot: invited %d user(s) to %s",
            invited,
            room_jid,
        )


class CantorBot:
    """slixmpp-based MUC listener and room manager."""

    def __init__(self, stdout):
        import slixmpp

        self._stdout = stdout
        self._joined_rooms = set()
        self._invitation_done = set()
        self._auth_retries = 0

        self._client = slixmpp.ClientXMPP(
            settings.EJABBERD_BOT_JID,
            settings.EJABBERD_BOT_PASSWORD,
            sasl_mech="PLAIN",
        )
        self._client.register_plugin("xep_0045")  # MUC
        self._client.register_plugin("xep_0199")  # Keepalive ping
        self._client.register_plugin("xep_0359")  # Stanza IDs

        self._client.add_event_handler("session_start", self._on_session_start)
        self._client.add_event_handler("groupchat_message", self._on_muc_message)
        self._client.add_event_handler("failed_auth", self._on_failed_auth)
        self._client.add_event_handler("disconnected", self._on_disconnected)

    def _cancel_all_schedules(self):
        """Cancel all scheduled events on the client to avoid duplicates on reconnect."""
        for name in list(self._client.scheduled_events):
            self._client.cancel_schedule(name)

    def run(self):
        host = settings.EJABBERD_HOST
        port = settings.EJABBERD_BOT_PORT
        logger.info(
            "ejabberd_bot: connecting to %s:%s as %s",
            host, port, settings.EJABBERD_BOT_JID,
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

        # Rescan every 60 s to pick up forums created after the bot started.
        self._client.schedule("room_check", 60, self._ensure_rooms_sync, repeat=True)

        self._stdout.write("ejabberd_bot: ready.")

    def _ensure_rooms_sync(self):
        """Sync wrapper called by slixmpp scheduler."""
        asyncio.ensure_future(self._ensure_rooms())

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
                await asyncio.to_thread(self._configure_room, muc_jid, thema)
            except Exception as exc:
                logger.error("ejabberd_bot: failed to join %s: %s", muc_jid, exc)

        if new_count:
            self._stdout.write(f"ejabberd_bot: joined {new_count} room(s).")

    @staticmethod
    def _configure_room(muc_jid, title):
        """Configure a newly created MUC room: title, persistent, non-anonymous."""
        from intern.ejabberd import change_room_option
        if title:
            change_room_option(muc_jid, "title", title)
        change_room_option(muc_jid, "persistent", "true")
        change_room_option(muc_jid, "anonymous", "false")

    def _on_failed_auth(self, event):
        """Handle authentication failure — retry with backoff, then give up."""
        self._auth_retries += 1
        if self._auth_retries > 3:
            logger.error(
                "ejabberd_bot: giving up after %d auth failures for %s — "
                "check EJABBERD_BOT_JID and EJABBERD_BOT_PASSWORD",
                self._auth_retries,
                settings.EJABBERD_BOT_JID,
            )
            asyncio.get_event_loop().stop()
            return

        delay = min(300, 30 * 2 ** (self._auth_retries - 1))
        logger.error(
            "ejabberd_bot: authentication failed for %s (attempt %d, retry in %ds)",
            settings.EJABBERD_BOT_JID,
            self._auth_retries,
            delay,
        )
        self._joined_rooms.clear()
        self._cancel_all_schedules()
        asyncio.get_event_loop().call_later(delay, self._reconnect)

    async def _on_muc_message(self, msg):
        """Handle inbound groupchat messages from MUC."""
        room_jid = str(msg["from"].bare)

        body = (msg["body"] or "").strip()
        if not body:
            return

        # Messages with <delay/> are replayed room history on join —
        # don't store them again, but still trigger invitations.
        is_history = msg.get_plugin("delay", check=True) is not None

        # Echo prevention: in MUC, from = room@service/nickname,
        # so check the resource (nickname) not the bare JID.
        sender_nickname = msg["from"].resource
        if sender_nickname == "CantorBot":
            # Still trigger invitations for Forum-relayed messages
            if room_jid not in self._invitation_done:
                self._invitation_done.add(room_jid)
                await asyncio.to_thread(_db_invite_missing_users, room_jid)
            return

        # Skip storing replayed history — dedup should catch it,
        # but no point querying the REST API for stale occupants.
        if is_history:
            return

        # Resolve sender's real XMPP JID from room occupants
        sender_jid = await asyncio.to_thread(
            _resolve_sender_jid, room_jid, sender_nickname
        )

        stanza_id = msg["id"]
        stanza_id_plugin = msg.get_plugin("stanza_id", check=True)
        if stanza_id_plugin and stanza_id_plugin["id"]:
            stanza_id = stanza_id_plugin["id"]
        await asyncio.to_thread(
            _db_store_message, room_jid, body, sender_jid, stanza_id
        )

        # Invite missing users on first message in this room
        if room_jid not in self._invitation_done:
            self._invitation_done.add(room_jid)
            await asyncio.to_thread(_db_invite_missing_users, room_jid)

    def _on_disconnected(self, event):
        """Reconnect on disconnection."""
        logger.warning("ejabberd_bot: disconnected, reconnecting...")
        self._joined_rooms.clear()
        self._cancel_all_schedules()
        asyncio.get_event_loop().call_later(5, self._reconnect)

    def _reconnect(self):
        """Attempt to reconnect."""
        host = settings.EJABBERD_HOST
        port = settings.EJABBERD_BOT_PORT
        self._client.connect((host, port))


class Command(BaseCommand):
    """Management command to run the ejabberd bot."""

    help = "Run the ejabberd bot for MUC <-> Forum bridging."

    def handle(self, *args, **options):
        bot = CantorBot(self.stdout)
        bot.run()

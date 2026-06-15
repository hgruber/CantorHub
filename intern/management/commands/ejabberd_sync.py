"""
Management command: ejabberd_sync

Startup synchronization for XMPP/ejabberd integration.
Runs at startup when EJABBERD_ENABLED=1.

Tasks:
- Register the bot account (idempotent)
- Assign MUC JIDs to forums that don't have them
- Invite users with XMPP JIDs to the Space (future)
"""

import logging

from django.core.management.base import BaseCommand

from intern.ejabberd import configure_room, ensure_bot
from intern.app_settings import get_config, get_config_bool
from intern.models import Forum, User

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Management command to sync XMPP state with Django."""

    help = "Sync XMPP/ejabberd state at startup."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Register bot and assign MUC JIDs to forums",
        )
        parser.add_argument(
            "--invite",
            action="store_true",
            help="Invite users with XMPP JIDs to the Space",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="List forums and their MUC JIDs",
        )

    def handle(self, *args, **options):
        if not get_config_bool("EJABBERD_ENABLED"):
            self.stdout.write("ejabberd_sync: EJABBERD_ENABLED is False, skipping")
            return

        if options.get("list"):
            self._do_list()
        elif options.get("invite"):
            self._do_invite()
        elif options.get("sync"):
            self._do_sync()
        else:
            self._do_sync()

    def _do_sync(self):
        """Register bot and assign MUC JIDs to forums."""
        self.stdout.write("ejabberd_sync: starting sync...")

        # Register bot account (idempotent)
        self.stdout.write("ejabberd_sync: ensuring bot account...")
        if not ensure_bot():
            self.stdout.write("ejabberd_sync: FAILED to ensure bot account")
            return
        self.stdout.write("ejabberd_sync: bot account ready")

        # Assign MUC JIDs to forums that don't have them
        self.stdout.write("ejabberd_sync: checking forum MUC assignments...")
        self._assign_muc_jids()

        # Enforce standard room options on all existing rooms
        self.stdout.write("ejabberd_sync: configuring existing rooms...")
        self._configure_rooms()

        # Check if the bot is in all rooms (it will join on next scan)
        self.stdout.write(
            "ejabberd_sync: bot will join rooms on next 60-second rescan"
        )

    def _configure_rooms(self):
        """Re-apply the standard room options to all forums with a MUC JID.

        Rooms that don't exist yet on ejabberd are skipped silently (the bot
        configures them when it first joins).
        """
        count = 0
        for forum in Forum.objects.exclude(xmpp_muc_jid=None).exclude(xmpp_muc_jid=""):
            if configure_room(forum.xmpp_muc_jid, forum.thema):
                count += 1
                logger.info(
                    "ejabberd_sync: configured room %s (forum #%s)",
                    forum.xmpp_muc_jid,
                    forum.pk,
                )
        self.stdout.write(f"ejabberd_sync: configured {count} room(s)")

    def _assign_muc_jids(self):
        """Assign MUC JIDs to forums that don't have them."""
        from intern.apps import _migrating

        # Mark as migrating to skip the post_save signal
        _migrating.active = True
        try:
            forums_needing_jid = Forum.objects.filter(
                xmpp_muc_jid=None
            ) | Forum.objects.filter(xmpp_muc_jid="")

            count = 0
            for forum in forums_needing_jid:
                muc_jid = f"forum-{forum.pk}@{get_config('EJABBERD_MUC_SERVICE', '')}"
                forum.xmpp_muc_jid = muc_jid
                forum.save(update_fields=["xmpp_muc_jid"])
                count += 1
                logger.info(
                    "ejabberd_sync: assigned %s to forum #%s",
                    muc_jid,
                    forum.pk,
                )

            if count > 0:
                self.stdout.write(
                    f"ejabberd_sync: assigned MUC JIDs to {count} forum(s)"
                )
            else:
                self.stdout.write("ejabberd_sync: all forums have MUC JIDs")
        finally:
            _migrating.active = False

    def _do_list(self):
        """List forums and their MUC JIDs."""
        self.stdout.write("ejabberd_sync: forum list")
        self.stdout.write("-" * 60)
        for forum in Forum.objects.exclude(xmpp_muc_jid=None).exclude(
            xmpp_muc_jid=""
        ):
            self.stdout.write(
                f"#{forum.pk}: {forum.thema} -> {forum.xmpp_muc_jid}"
            )
        self.stdout.write("-" * 60)
        self.stdout.write(
            f"Total: {Forum.objects.exclude(xmpp_muc_jid=None).exclude(xmpp_muc_jid='').count()} forum(s) with MUC"
        )

    def _do_invite(self):
        """Invite users with XMPP JIDs to the Space."""
        self.stdout.write("ejabberd_sync: inviting XMPP users to Space...")

        users_with_xmpp = User.objects.exclude(xmpp=None).exclude(xmpp="")

        for user in users_with_xmpp:
            # TODO: Actually invite the user to the Space
            self.stdout.write(
                f"ejabberd_sync: would invite {user.username} ({user.xmpp}) to Space"
            )

        self.stdout.write(
            f"ejabberd_sync: would invite {users_with_xmpp.count()} user(s)"
        )

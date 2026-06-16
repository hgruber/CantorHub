"""
Management command: ejabberd_admin

Single entry point for all administrative operations of the XMPP/ejabberd
integration. Subcommands are grouped by noun (bot, room, user, invite, server)
plus a top-level `sync` action that performs the full startup synchronization.
"""

import getpass

from django.core.management.base import BaseCommand

from intern.ejabberd import (
    assign_muc_jids,
    configure_all_rooms,
    configure_room,
    destroy_room,
    ensure_bot,
    get_room_members,
    get_room_occupants,
    get_room_options,
    list_registered_users,
    send_invitation,
    set_room_affiliation,
    set_room_vcard,
    set_user_password,
    set_vcard,
    unregister_user,
)
from intern.app_settings import is_ejabberd_configured
from intern.models import Forum, User


class Command(BaseCommand):
    """Manage ejabberd users, rooms, invitations, and startup sync."""

    help = "Admin commands for XMPP/ejabberd integration."

    def add_arguments(self, parser):
        groups = parser.add_subparsers(dest="group")

        # sync (top-level, no verb) — full startup synchronization
        groups.add_parser(
            "sync", help="Full sync: ensure bot, assign MUC JIDs, configure rooms"
        )

        # bot
        bot = groups.add_parser("bot", help="Bot account operations").add_subparsers(
            dest="action"
        )
        bot.add_parser("ensure", help="Register/ensure the bot account (idempotent)")

        # room
        room = groups.add_parser("room", help="Forum MUC room operations").add_subparsers(
            dest="action"
        )
        room.add_parser("list", help="List forums and their MUC JIDs")
        room.add_parser("assign-jids", help="Assign MUC JIDs to forums missing them")
        sp = room.add_parser("configure", help="Enforce standard options on one/all rooms")
        sp.add_argument("--forum", type=int, help="Forum primary key (omit for all rooms)")
        sp = room.add_parser("delete", help="Destroy a forum's MUC room")
        sp.add_argument("forum_id", type=int, help="Forum primary key")
        sp = room.add_parser("avatar", help="Push the forum image as MUC room avatar")
        sp.add_argument("forum_id", type=int, help="Forum primary key")
        sp = room.add_parser("members", help="List a room's affiliations")
        sp.add_argument("forum_id", type=int, help="Forum primary key")
        sp = room.add_parser("occupants", help="List a room's current occupants")
        sp.add_argument("forum_id", type=int, help="Forum primary key")
        sp = room.add_parser("options", help="Show a room's options")
        sp.add_argument("forum_id", type=int, help="Forum primary key")

        # user
        user = groups.add_parser("user", help="CantorHub user / ejabberd account operations").add_subparsers(
            dest="action"
        )
        user.add_parser("list", help="List users with XMPP JIDs")
        sp = user.add_parser("delete", help="Delete a user's ejabberd account")
        sp.add_argument("user", help="Username or numeric user ID")
        sp = user.add_parser("vcard", help="Re-upload a user's vCard (name + avatar)")
        sp.add_argument("user", help="Username or numeric user ID")
        sp = user.add_parser("password", help="Set a user's ejabberd password")
        sp.add_argument("user", help="Username or numeric user ID")

        # invite
        invite = groups.add_parser("invite", help="Room invitation / affiliation operations").add_subparsers(
            dest="action"
        )
        sp = invite.add_parser("add", help="Send a direct invitation to a user")
        sp.add_argument("--forum", type=int, required=True, help="Forum primary key")
        sp.add_argument("--user", required=True, help="Username or numeric user ID")
        sp = invite.add_parser("remove", help="Remove a user from a forum's MUC room")
        sp.add_argument("--forum", type=int, required=True, help="Forum primary key")
        sp.add_argument("--user", required=True, help="Username or numeric user ID")
        sp = invite.add_parser("clear", help="Remove affiliations/invitations from a room")
        sp.add_argument("--forum", type=int, required=True, help="Forum primary key")
        sp.add_argument("--user", help="Username or numeric user ID (omit for all users)")

        # server
        server = groups.add_parser("server", help="Raw ejabberd server operations").add_subparsers(
            dest="action"
        )
        server.add_parser("users", help="List all registered ejabberd accounts")

    def handle(self, *args, **options):
        if not is_ejabberd_configured():
            self.stderr.write("EJABBERD_HOST and EJABBERD_BOT_JID must be set.")
            return

        group = options.get("group")
        if not group:
            self.stderr.write("Specify a command group. See --help for available commands.")
            return

        if group == "sync":
            self._do_sync(options)
            return

        action = options.get("action")
        if not action:
            self.stderr.write(f"Specify an action for '{group}'. See '{group} --help'.")
            return

        handler = getattr(self, f"_do_{group}_{action.replace('-', '_')}", None)
        if handler:
            handler(options)
        else:
            self.stderr.write(f"Unknown command: {group} {action}")

    # --- helpers ---------------------------------------------------------

    def _lookup_user(self, identifier):
        """Look up a User by pk (numeric) or username."""
        try:
            pk = int(identifier)
            return User.objects.get(pk=pk)
        except (ValueError, User.DoesNotExist):
            pass
        try:
            return User.objects.get(username=identifier)
        except User.DoesNotExist:
            self.stderr.write(f"User not found: {identifier}")
            return None

    def _get_forum(self, forum_id):
        """Fetch a Forum or report and return None."""
        try:
            return Forum.objects.get(pk=forum_id)
        except Forum.DoesNotExist:
            self.stderr.write(f"Forum #{forum_id} not found.")
            return None

    def _get_forum_with_muc(self, forum_id):
        """Fetch a Forum that has a MUC JID, or report and return None."""
        forum = self._get_forum(forum_id)
        if not forum:
            return None
        if not forum.xmpp_muc_jid:
            self.stderr.write(f"Forum #{forum_id} has no MUC JID.")
            return None
        return forum

    def _confirm(self, prompt):
        """Print a y/N prompt and return True only on explicit 'y'."""
        self.stdout.write(prompt)
        if input().strip().lower() != "y":
            self.stdout.write("Cancelled.")
            return False
        return True

    # --- sync ------------------------------------------------------------

    def _do_sync(self, options):
        self.stdout.write("ejabberd_admin: starting sync...")
        self.stdout.write("ejabberd_admin: ensuring bot account...")
        if not ensure_bot():
            self.stdout.write("ejabberd_admin: FAILED to ensure bot account")
            return
        self.stdout.write("ejabberd_admin: bot account ready")

        self.stdout.write("ejabberd_admin: checking forum MUC assignments...")
        assigned = assign_muc_jids()
        if assigned:
            self.stdout.write(f"ejabberd_admin: assigned MUC JIDs to {assigned} forum(s)")
        else:
            self.stdout.write("ejabberd_admin: all forums have MUC JIDs")

        self.stdout.write("ejabberd_admin: configuring existing rooms...")
        configured = configure_all_rooms()
        self.stdout.write(f"ejabberd_admin: configured {configured} room(s)")

        self.stdout.write("ejabberd_admin: bot will join rooms on next 60-second rescan")

    # --- bot -------------------------------------------------------------

    def _do_bot_ensure(self, options):
        if ensure_bot():
            self.stdout.write("Bot account ready.")
        else:
            self.stderr.write("Failed to ensure bot account.")

    # --- room ------------------------------------------------------------

    def _do_room_list(self, options):
        forums = Forum.objects.exclude(xmpp_muc_jid=None).exclude(xmpp_muc_jid="")
        if not forums.exists():
            self.stdout.write("No forums with MUC JIDs.")
            return
        for forum in forums:
            self.stdout.write(f"#{forum.pk}: {forum.thema} -> {forum.xmpp_muc_jid}")
        self.stdout.write(f"Total: {forums.count()} forum(s)")

    def _do_room_assign_jids(self, options):
        count = assign_muc_jids()
        if count:
            self.stdout.write(f"Assigned MUC JIDs to {count} forum(s).")
        else:
            self.stdout.write("All forums already have MUC JIDs.")

    def _do_room_configure(self, options):
        forum_id = options.get("forum")
        if forum_id:
            forum = self._get_forum_with_muc(forum_id)
            if not forum:
                return
            if configure_room(forum.xmpp_muc_jid, forum.thema):
                self.stdout.write(f"Configured room {forum.xmpp_muc_jid}.")
            else:
                self.stderr.write(f"Failed to configure room {forum.xmpp_muc_jid}.")
        else:
            count = configure_all_rooms()
            self.stdout.write(f"Configured {count} room(s).")

    def _do_room_delete(self, options):
        forum = self._get_forum_with_muc(options["forum_id"])
        if not forum:
            return
        muc_jid = forum.xmpp_muc_jid
        if not self._confirm(
            f"Delete MUC room {muc_jid} for forum #{forum.pk}: {forum.thema}? [y/N] "
        ):
            return
        if destroy_room(muc_jid):
            Forum.objects.filter(pk=forum.pk).update(xmpp_muc_jid=None)
            self.stdout.write(f"Deleted room {muc_jid} and cleared forum #{forum.pk}.")
        else:
            self.stderr.write(f"Failed to destroy room {muc_jid}.")

    def _do_room_avatar(self, options):
        forum = self._get_forum_with_muc(options["forum_id"])
        if not forum:
            return
        if not forum.bild:
            self.stderr.write(f"Forum #{forum.pk} has no image (bild).")
            return
        if set_room_vcard(forum.xmpp_muc_jid, forum.bild, name=forum.thema):
            self.stdout.write(f"Set room avatar for {forum.xmpp_muc_jid}.")
        else:
            self.stderr.write(f"Failed to set room avatar for {forum.xmpp_muc_jid}.")

    def _do_room_members(self, options):
        forum = self._get_forum_with_muc(options["forum_id"])
        if not forum:
            return
        members = get_room_members(forum.xmpp_muc_jid)
        if not members:
            self.stdout.write(f"No affiliations in {forum.xmpp_muc_jid}.")
            return
        for jid, affiliation in members:
            self.stdout.write(f"  {jid} ({affiliation})")
        self.stdout.write(f"Total: {len(members)} member(s).")

    def _do_room_occupants(self, options):
        forum = self._get_forum_with_muc(options["forum_id"])
        if not forum:
            return
        occupants = get_room_occupants(forum.xmpp_muc_jid)
        if not occupants:
            self.stdout.write(f"No occupants in {forum.xmpp_muc_jid}.")
            return
        for jid, nick in occupants:
            self.stdout.write(f"  {nick} -> {jid}")
        self.stdout.write(f"Total: {len(occupants)} occupant(s).")

    def _do_room_options(self, options):
        forum = self._get_forum_with_muc(options["forum_id"])
        if not forum:
            return
        room_options = get_room_options(forum.xmpp_muc_jid)
        if room_options is None:
            self.stderr.write(
                f"Could not read options for {forum.xmpp_muc_jid} (room may not exist)."
            )
            return
        for key in sorted(room_options):
            self.stdout.write(f"  {key} = {room_options[key]}")

    # --- user ------------------------------------------------------------

    def _do_user_list(self, options):
        users = User.objects.exclude(xmpp=None).exclude(xmpp="")
        if not users.exists():
            self.stdout.write("No users with XMPP JIDs.")
            return
        for user in users:
            self.stdout.write(f"#{user.pk}: {user.username} -> {user.xmpp}")
        self.stdout.write(f"Total: {users.count()} user(s)")

    def _do_user_delete(self, options):
        user = self._lookup_user(options["user"])
        if not user:
            return
        if not user.xmpp:
            self.stderr.write(f"User {user.username} has no XMPP JID.")
            return
        localpart = user.xmpp.split("@")[0]
        if not self._confirm(
            f"Delete ejabberd account {user.xmpp} for user {user.username}? [y/N] "
        ):
            return
        if unregister_user(localpart):
            User.objects.filter(pk=user.pk).update(xmpp=None)
            self.stdout.write(f"Deleted account {user.xmpp} and cleared user.xmpp.")
        else:
            self.stderr.write(f"Failed to unregister {user.xmpp}.")

    def _do_user_vcard(self, options):
        user = self._lookup_user(options["user"])
        if not user:
            return
        if not user.xmpp:
            self.stderr.write(f"User {user.username} has no XMPP JID.")
            return
        localpart = user.xmpp.split("@")[0]
        full_name = f"{user.first_name} {user.last_name}".strip() or user.username
        if set_vcard(localpart, full_name, avatar_file=user.avatar):
            self.stdout.write(f"Synced vCard for {user.xmpp}.")
        else:
            self.stderr.write(f"Failed to sync vCard for {user.xmpp}.")

    def _do_user_password(self, options):
        user = self._lookup_user(options["user"])
        if not user:
            return
        if not user.xmpp:
            self.stderr.write(f"User {user.username} has no XMPP JID.")
            return
        localpart = user.xmpp.split("@")[0]
        password = getpass.getpass(f"New ejabberd password for {user.xmpp}: ")
        if not password:
            self.stderr.write("Password cannot be empty.")
            return
        if set_user_password(localpart, password):
            self.stdout.write(f"Password synced for {user.xmpp}.")
        else:
            self.stderr.write(f"Failed to sync password for {user.xmpp}.")

    # --- invite ----------------------------------------------------------

    def _do_invite_add(self, options):
        forum = self._get_forum_with_muc(options["forum"])
        if not forum:
            return
        user = self._lookup_user(options["user"])
        if not user:
            return
        if not user.xmpp:
            self.stderr.write(f"User {user.username} has no XMPP JID.")
            return
        full_name = f"{user.first_name} {user.last_name}".strip() or user.username
        if send_invitation(
            forum.xmpp_muc_jid, user.xmpp, reason=f"CantorHub Forum: {full_name}"
        ):
            self.stdout.write(f"Invited {user.xmpp} to {forum.xmpp_muc_jid}.")
        else:
            self.stderr.write(f"Failed to invite {user.xmpp} to {forum.xmpp_muc_jid}.")

    def _do_invite_remove(self, options):
        forum = self._get_forum_with_muc(options["forum"])
        if not forum:
            return
        user = self._lookup_user(options["user"])
        if not user:
            return
        if not user.xmpp:
            self.stderr.write(f"User {user.username} has no XMPP JID.")
            return
        if set_room_affiliation(forum.xmpp_muc_jid, user.xmpp, "none"):
            self.stdout.write(f"Removed {user.xmpp} from {forum.xmpp_muc_jid}.")
        else:
            self.stderr.write(f"Failed to remove {user.xmpp} from {forum.xmpp_muc_jid}.")

    def _do_invite_clear(self, options):
        forum = self._get_forum_with_muc(options["forum"])
        if not forum:
            return
        muc_jid = forum.xmpp_muc_jid

        user_identifier = options.get("user")
        if user_identifier:
            user = self._lookup_user(user_identifier)
            if not user:
                return
            if not user.xmpp:
                self.stderr.write(f"User {user.username} has no XMPP JID.")
                return
            if not self._confirm(f"Remove {user.xmpp} from {muc_jid}? [y/N] "):
                return
            if set_room_affiliation(muc_jid, user.xmpp, "none"):
                self.stdout.write(f"Removed {user.xmpp} from {muc_jid}.")
            else:
                self.stderr.write(f"Failed to remove {user.xmpp} from {muc_jid}.")
            return

        members = get_room_members(muc_jid)
        self.stdout.write(f"Found {len(members)} member(s) in {muc_jid}.")
        if not self._confirm(f"Remove ALL members from {muc_jid}? [y/N] "):
            return
        removed = 0
        for jid, affiliation in members:
            if set_room_affiliation(muc_jid, jid, "none"):
                self.stdout.write(f"  Removed {jid} ({affiliation})")
                removed += 1
        self.stdout.write(f"Removed {removed} member(s) from {muc_jid}.")

    # --- server ----------------------------------------------------------

    def _do_server_users(self, options):
        users = list_registered_users()
        if not users:
            self.stdout.write("No registered ejabberd accounts (or query failed).")
            return
        for jid in users:
            self.stdout.write(f"  {jid}")
        self.stdout.write(f"Total: {len(users)} account(s).")

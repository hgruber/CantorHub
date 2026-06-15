"""
Management command: ejabberd_admin

Administrative operations for the XMPP/ejabberd integration.
"""

import getpass

from django.core.management.base import BaseCommand

from intern.ejabberd import (
    destroy_room,
    localpart_from_username,
    send_invitation,
    set_room_affiliation,
    set_user_password,
    set_vcard,
    unregister_user,
)
from intern.app_settings import is_ejabberd_configured
from intern.models import Forum, User


class Command(BaseCommand):
    """Manage ejabberd users, rooms, and invitations."""

    help = "Admin commands for XMPP/ejabberd integration."

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(dest="action")

        # delete_forum
        sp = subparsers.add_parser("delete_forum", help="Delete a forum's MUC room")
        sp.add_argument("forum_id", type=int, help="Forum primary key")

        # delete_user
        sp = subparsers.add_parser("delete_user", help="Delete a user's ejabberd account")
        sp.add_argument("user", help="Username or numeric user ID")

        # clear_invites
        sp = subparsers.add_parser("clear_invites", help="Remove affiliations/invitations from a room")
        sp.add_argument("--forum", type=int, required=True, help="Forum primary key")
        sp.add_argument("--user", help="Username or numeric user ID (omit for all users)")

        # invite
        sp = subparsers.add_parser("invite", help="Send a direct invitation to a user")
        sp.add_argument("--forum", type=int, required=True, help="Forum primary key")
        sp.add_argument("--user", required=True, help="Username or numeric user ID")

        # remove_user
        sp = subparsers.add_parser("remove_user", help="Remove a user from a forum's MUC room")
        sp.add_argument("--forum", type=int, required=True, help="Forum primary key")
        sp.add_argument("--user", required=True, help="Username or numeric user ID")

        # list_rooms
        subparsers.add_parser("list_rooms", help="List forums and their MUC JIDs")

        # list_users
        subparsers.add_parser("list_users", help="List users with XMPP JIDs")

        # sync_vcard
        sp = subparsers.add_parser("sync_vcard", help="Re-upload a user's vCard to ejabberd")
        sp.add_argument("user", help="Username or numeric user ID")

        # sync_password
        sp = subparsers.add_parser("sync_password", help="Sync a user's password to ejabberd")
        sp.add_argument("user", help="Username or numeric user ID")

    def handle(self, *args, **options):
        if not is_ejabberd_configured():
            self.stderr.write("EJABBERD_HOST and EJABBERD_BOT_JID must be set.")
            return

        action = options.get("action")
        if not action:
            self.stderr.write("Specify an action. See --help for available commands.")
            return

        handler = getattr(self, f"_do_{action}", None)
        if handler:
            handler(options)
        else:
            self.stderr.write(f"Unknown action: {action}")

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

    def _do_delete_forum(self, options):
        forum_id = options["forum_id"]
        try:
            forum = Forum.objects.get(pk=forum_id)
        except Forum.DoesNotExist:
            self.stderr.write(f"Forum #{forum_id} not found.")
            return

        muc_jid = forum.xmpp_muc_jid
        if not muc_jid:
            self.stderr.write(f"Forum #{forum_id} has no MUC JID.")
            return

        self.stdout.write(f"Delete MUC room {muc_jid} for forum #{forum_id}: {forum.thema}? [y/N] ")
        confirm = input().strip().lower()
        if confirm != "y":
            self.stdout.write("Cancelled.")
            return

        if destroy_room(muc_jid):
            Forum.objects.filter(pk=forum_id).update(xmpp_muc_jid=None)
            self.stdout.write(f"Deleted room {muc_jid} and cleared forum #{forum_id}.")
        else:
            self.stderr.write(f"Failed to destroy room {muc_jid}.")

    def _do_delete_user(self, options):
        user = self._lookup_user(options["user"])
        if not user:
            return

        if not user.xmpp:
            self.stderr.write(f"User {user.username} has no XMPP JID.")
            return

        localpart = user.xmpp.split("@")[0]
        self.stdout.write(
            f"Delete ejabberd account {user.xmpp} for user {user.username}? [y/N] "
        )
        confirm = input().strip().lower()
        if confirm != "y":
            self.stdout.write("Cancelled.")
            return

        if unregister_user(localpart):
            User.objects.filter(pk=user.pk).update(xmpp=None)
            self.stdout.write(f"Deleted account {user.xmpp} and cleared user.xmpp.")
        else:
            self.stderr.write(f"Failed to unregister {user.xmpp}.")

    def _do_clear_invites(self, options):
        forum_id = options["forum"]
        try:
            forum = Forum.objects.get(pk=forum_id)
        except Forum.DoesNotExist:
            self.stderr.write(f"Forum #{forum_id} not found.")
            return

        muc_jid = forum.xmpp_muc_jid
        if not muc_jid:
            self.stderr.write(f"Forum #{forum_id} has no MUC JID.")
            return

        user_identifier = options.get("user")
        if user_identifier:
            user = self._lookup_user(user_identifier)
            if not user:
                return
            if not user.xmpp:
                self.stderr.write(f"User {user.username} has no XMPP JID.")
                return
            self.stdout.write(f"Remove {user.xmpp} from {muc_jid}? [y/N] ")
            confirm = input().strip().lower()
            if confirm != "y":
                self.stdout.write("Cancelled.")
                return
            if set_room_affiliation(muc_jid, user.xmpp, "none"):
                self.stdout.write(f"Removed {user.xmpp} from {muc_jid}.")
            else:
                self.stderr.write(f"Failed to remove {user.xmpp} from {muc_jid}.")
        else:
            from intern.ejabberd import get_room_members

            members = get_room_members(muc_jid)
            self.stdout.write(f"Found {len(members)} member(s) in {muc_jid}.")
            self.stdout.write(f"Remove ALL members from {muc_jid}? [y/N] ")
            confirm = input().strip().lower()
            if confirm != "y":
                self.stdout.write("Cancelled.")
                return
            removed = 0
            for jid, affiliation in members:
                if set_room_affiliation(muc_jid, jid, "none"):
                    self.stdout.write(f"  Removed {jid} ({affiliation})")
                    removed += 1
            self.stdout.write(f"Removed {removed} member(s) from {muc_jid}.")

    def _do_invite(self, options):
        forum_id = options["forum"]
        user_identifier = options["user"]

        try:
            forum = Forum.objects.get(pk=forum_id)
        except Forum.DoesNotExist:
            self.stderr.write(f"Forum #{forum_id} not found.")
            return

        user = self._lookup_user(user_identifier)
        if not user:
            return

        muc_jid = forum.xmpp_muc_jid
        if not muc_jid:
            self.stderr.write(f"Forum #{forum_id} has no MUC JID.")
            return

        if not user.xmpp:
            self.stderr.write(f"User {user.username} has no XMPP JID.")
            return

        full_name = f"{user.first_name} {user.last_name}".strip() or user.username
        if send_invitation(muc_jid, user.xmpp, reason=f"CantorHub Forum: {full_name}"):
            self.stdout.write(f"Invited {user.xmpp} to {muc_jid}.")
        else:
            self.stderr.write(f"Failed to invite {user.xmpp} to {muc_jid}.")

    def _do_remove_user(self, options):
        forum_id = options["forum"]
        user_identifier = options["user"]

        try:
            forum = Forum.objects.get(pk=forum_id)
        except Forum.DoesNotExist:
            self.stderr.write(f"Forum #{forum_id} not found.")
            return

        user = self._lookup_user(user_identifier)
        if not user:
            return

        muc_jid = forum.xmpp_muc_jid
        if not muc_jid:
            self.stderr.write(f"Forum #{forum_id} has no MUC JID.")
            return

        if not user.xmpp:
            self.stderr.write(f"User {user.username} has no XMPP JID.")
            return

        if set_room_affiliation(muc_jid, user.xmpp, "none"):
            self.stdout.write(f"Removed {user.xmpp} from {muc_jid}.")
        else:
            self.stderr.write(f"Failed to remove {user.xmpp} from {muc_jid}.")

    def _do_list_rooms(self, options):
        forums = Forum.objects.exclude(xmpp_muc_jid=None).exclude(xmpp_muc_jid="")
        if not forums.exists():
            self.stdout.write("No forums with MUC JIDs.")
            return
        for forum in forums:
            self.stdout.write(f"#{forum.pk}: {forum.thema} -> {forum.xmpp_muc_jid}")
        self.stdout.write(f"Total: {forums.count()} forum(s)")

    def _do_list_users(self, options):
        users = User.objects.exclude(xmpp=None).exclude(xmpp="")
        if not users.exists():
            self.stdout.write("No users with XMPP JIDs.")
            return
        for user in users:
            self.stdout.write(f"#{user.pk}: {user.username} -> {user.xmpp}")
        self.stdout.write(f"Total: {users.count()} user(s)")

    def _do_sync_vcard(self, options):
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

    def _do_sync_password(self, options):
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
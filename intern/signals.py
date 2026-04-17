"""
Django signals for the XMPP/ejabberd integration.

Handles:
1. Auto-assigning MUC JIDs when new Forum threads are created
2. Inviting users to the XMPP Space when they set their XMPP JID
"""

import logging

from django.conf import settings
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .apps import _migrating

logger = logging.getLogger(__name__)


@receiver(post_save, sender="intern.Forum")
def assign_xmpp_muc_jid(sender, instance, created, **kwargs):
    """
    When a new Forum thread is created via the UI (not during migration/import),
    assign an ejabberd MUC JID for it. The running bot will join (and thereby
    create) the room within its next 60-second rescan.

    Guard order (belt-and-suspenders):
    1. instance._skip_ejabberd_signal — set by 0003_import to suppress during data import
    2. getattr(_migrating, 'active', False) — thread-local from apps.py
    3. settings.EJABBERD_ENABLED
    4. instance.xmpp_muc_jid already set
    """
    if not created:
        return
    if getattr(instance, "_skip_ejabberd_signal", False):
        return
    if getattr(_migrating, "active", False):
        return
    if not settings.EJABBERD_ENABLED:
        return
    if instance.xmpp_muc_jid:
        return

    muc_jid = f"forum-{instance.pk}@{settings.EJABBERD_MUC_SERVICE}"
    sender.objects.filter(pk=instance.pk).update(xmpp_muc_jid=muc_jid)
    instance.xmpp_muc_jid = muc_jid
    logger.info(
        "ejabberd: assigned MUC JID %s to forum #%s (bot will join)",
        muc_jid,
        instance.pk,
    )


@receiver(pre_save, sender="intern.User")
def _capture_old_xmpp(sender, instance, **kwargs):
    """
    Capture the current xmpp value before a save so the post_save handler
    can detect changes. This is needed because post_save doesn't have access
    to the old value.
    """
    if instance.pk:
        try:
            old_user = sender.objects.get(pk=instance.pk)
            instance._old_xmpp = old_user.xmpp
        except sender.DoesNotExist:
            instance._old_xmpp = None
    else:
        instance._old_xmpp = None


@receiver(post_save, sender="intern.User")
def invite_user_on_xmpp_set(sender, instance, created, **kwargs):
    """
    When a user sets (or changes) their XMPP/Jabber ID, invite them to the
    CantorHub Space. This only happens if:
    - The user's XMPP value actually changed
    - The value is a valid JID (contains @)
    - EJABBERD_ENABLED is True
    - Not during migration

    Note: This invites to the Space, not to individual forum MUCs.
    Forum invitations happen on first message in each room (bot triggers them).
    """
    new_xmpp = instance.xmpp or ""
    old_xmpp = getattr(instance, "_old_xmpp", None)

    # Skip if no change or no XMPP set
    if new_xmpp == old_xmpp:
        return
    if not new_xmpp or "@" not in new_xmpp:
        return

    # Skip during migration
    if getattr(_migrating, "active", False):
        return

    # Skip if XMPP integration disabled
    if not settings.EJABBERD_ENABLED:
        return

    # Only invite if this is a new JID being set (not during migration import)
    # The bot will handle inviting users when it joins rooms
    logger.info(
        "ejabberd: user %s set XMPP JID %s - will be invited to Space on next bot scan",
        instance.username,
        new_xmpp,
    )

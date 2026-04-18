"""
Django signals for the XMPP/ejabberd integration.

Handles:
1. Auto-assigning MUC JIDs when new Forum threads are created
2. Syncing vCard (name + avatar) to ejabberd when User.avatar changes
"""

import logging
import threading

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
def _capture_old_values(sender, instance, **kwargs):
    """
    Capture the current xmpp and avatar values before a save so the post_save
    handler can detect changes. This is needed because post_save doesn't have
    access to the old value.
    """
    if instance.pk:
        try:
            old_user = sender.objects.get(pk=instance.pk)
            instance._old_xmpp = old_user.xmpp
            instance._old_avatar_id = old_user.avatar_id
        except sender.DoesNotExist:
            instance._old_xmpp = None
            instance._old_avatar_id = None
    else:
        instance._old_xmpp = None
        instance._old_avatar_id = None


def _sync_vcard(user_pk):
    """Sync a user's vCard (full name + avatar) to ejabberd. Runs in a daemon thread."""
    from .ejabberd import set_vcard
    from .models import User

    try:
        user = User.objects.get(pk=user_pk)
    except User.DoesNotExist:
        return

    if not user.xmpp:
        return

    localpart = user.xmpp.split("@")[0]
    full_name = f"{user.first_name} {user.last_name}".strip() or user.username
    set_vcard(localpart, full_name, avatar_file=user.avatar)


@receiver(post_save, sender="intern.User")
def sync_xmpp_on_user_save(sender, instance, created, **kwargs):
    """
    Handle XMPP-related changes on User save:
    - Log when xmpp JID is set or changed
    - Sync vCard when avatar changes and user has an xmpp account
    """
    if getattr(_migrating, "active", False):
        return
    if not settings.EJABBERD_ENABLED:
        return

    new_xmpp = instance.xmpp or ""
    old_xmpp = getattr(instance, "_old_xmpp", None)

    if new_xmpp != old_xmpp and new_xmpp and "@" in new_xmpp:
        logger.info(
            "ejabberd: user %s set XMPP JID %s",
            instance.username,
            new_xmpp,
        )

    # Sync vCard when avatar changes and user has an xmpp account
    old_avatar_id = getattr(instance, "_old_avatar_id", None)
    if instance.xmpp and instance.avatar_id != old_avatar_id:
        threading.Thread(
            target=_sync_vcard,
            args=(instance.pk,),
            daemon=True,
        ).start()
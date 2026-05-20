"""
Django signals for the XMPP/ejabberd integration and audit logging.

Handles:
1. Auto-assigning MUC JIDs when new Forum threads are created
2. Syncing vCard (name + avatar) to ejabberd when User.avatar changes
3. Writing ChangeLog audit entries for key model saves
"""

import logging
import threading
from datetime import datetime

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .apps import _migrating
from .app_settings import get_config, get_config_bool

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
    if not get_config_bool("EJABBERD_ENABLED"):
        return
    if instance.xmpp_muc_jid:
        return

    muc_jid = f"forum-{instance.pk}@{get_config('EJABBERD_MUC_SERVICE', '')}"
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
    Capture the current xmpp, avatar, and audit-relevant field values before a
    save so the post_save handler can detect changes.
    """
    if instance.pk:
        try:
            old_user = sender.objects.get(pk=instance.pk)
            instance._old_xmpp = old_user.xmpp
            instance._old_avatar_id = old_user.avatar_id
            instance._audit_old = {f: getattr(old_user, f, None) for f in _AUDIT_FIELDS.get("User", [])}
        except sender.DoesNotExist:
            instance._old_xmpp = None
            instance._old_avatar_id = None
            instance._audit_old = None
    else:
        instance._old_xmpp = None
        instance._old_avatar_id = None
        instance._audit_old = None


def _sync_vcard(user_pk):
    """Sync a user's vCard (full name + avatar) to ejabberd. Runs in a daemon thread."""
    import time

    from django.db import OperationalError

    from .ejabberd import set_vcard
    from .models import User

    for attempt in range(3):
        try:
            user = User.objects.get(pk=user_pk)
            break
        except OperationalError:
            if attempt == 2:
                logger.warning("ejabberd: vcard sync for user %s gave up after DB lock", user_pk)
                return
            time.sleep(0.5 * (attempt + 1))

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
    - Write audit ChangeLog entry
    """
    if getattr(_migrating, "active", False):
        return

    if get_config_bool("EJABBERD_ENABLED"):
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

    _write_audit_log(instance, created, "User")


@receiver(post_delete, sender="intern.User")
def _audit_user_delete(sender, instance, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _log_change(instance, getattr(instance, "_audit_user", None), "delete")


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

_AUDIT_FIELDS = {
    "User": [
        "first_name", "last_name", "stimme", "is_active", "email",
        "xmpp", "strasse", "plz", "ort", "telefon", "telefon_mobil",
        "geburtstag", "avatar_id",
    ],
    "Termin": ["kurz", "datum", "datum_bis", "lang", "ort_id", "anwesenheit", "repertoire"],
    "Lied": ["titel", "aktiv", "tempo", "beats", "hymne", "acapella", "weihnacht", "komponist",
             "original_id", "aufnahme_id", "pdf_id", "noten_id"],
    "Zusage": ["option"],
    "Forum": ["thema", "aktiv", "bild_id"],
    "Ort": ["name", "beschreibung", "strasse", "plz", "ort", "breite", "laenge"],
}


def _log_change(instance, user, action, old_values=None):
    """Write a ChangeLog row. Never raises — audit failures must not block saves."""
    from .models import ChangeLog

    try:
        model_name = instance.__class__.__name__
        allowed = _AUDIT_FIELDS.get(model_name, [])
        changes = {}
        if old_values is not None and action == ChangeLog.ACTION_UPDATE:
            for field in allowed:
                old = old_values.get(field)
                new = getattr(instance, field, None)
                if old != new:
                    changes[field] = [
                        str(old) if old is not None else None,
                        str(new) if new is not None else None,
                    ]
        elif action == ChangeLog.ACTION_CREATE:
            for field in allowed:
                val = getattr(instance, field, None)
                if val is not None and val != "" and val is not False:
                    changes[field] = [None, str(val)]
        elif action == ChangeLog.ACTION_DELETE:
            for field in allowed:
                val = getattr(instance, field, None)
                if val is not None and val != "" and val is not False:
                    changes[field] = [str(val), None]
        ChangeLog.objects.create(
            timestamp=datetime.now(),
            user=user,
            action=action,
            model_name=model_name,
            object_id=instance.pk,
            object_repr=str(instance)[:200],
            changes=changes,
        )
    except Exception:
        logger.exception(
            "audit: failed to write ChangeLog for %s #%s",
            instance.__class__.__name__,
            getattr(instance, "pk", "?"),
        )


def _capture_audit_old(sender, instance, model_key):
    """Capture old field values before a save for the given model key."""
    if not instance.pk:
        instance._audit_old = None
        return
    try:
        old = sender.objects.get(pk=instance.pk)
        instance._audit_old = {f: getattr(old, f, None) for f in _AUDIT_FIELDS.get(model_key, [])}
    except sender.DoesNotExist:
        instance._audit_old = None


def _write_audit_log(instance, created, model_key):
    """Write ChangeLog entry after a save."""
    from .models import ChangeLog

    user = getattr(instance, "_audit_user", None)
    action = ChangeLog.ACTION_CREATE if created else ChangeLog.ACTION_UPDATE
    _log_change(
        instance,
        user,
        action,
        old_values=getattr(instance, "_audit_old", None),
    )


# --- Termin ---
@receiver(pre_save, sender="intern.Termin")
def _audit_termin_pre(sender, instance, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _capture_audit_old(sender, instance, "Termin")


@receiver(post_save, sender="intern.Termin")
def _audit_termin_post(sender, instance, created, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _write_audit_log(instance, created, "Termin")


@receiver(post_delete, sender="intern.Termin")
def _audit_termin_delete(sender, instance, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _log_change(instance, getattr(instance, "_audit_user", None), "delete")


# --- Lied ---
@receiver(pre_save, sender="intern.Lied")
def _audit_lied_pre(sender, instance, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _capture_audit_old(sender, instance, "Lied")


@receiver(post_save, sender="intern.Lied")
def _audit_lied_post(sender, instance, created, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _write_audit_log(instance, created, "Lied")


@receiver(post_delete, sender="intern.Lied")
def _audit_lied_delete(sender, instance, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _log_change(instance, getattr(instance, "_audit_user", None), "delete")


# Zusage: no signal handlers — user is injected directly from the view via _log_change()
# because update_or_create fires post_save before the view can set _audit_user.

# --- Forum ---
@receiver(pre_save, sender="intern.Forum")
def _audit_forum_pre(sender, instance, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _capture_audit_old(sender, instance, "Forum")


@receiver(post_save, sender="intern.Forum")
def _audit_forum_post(sender, instance, created, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _write_audit_log(instance, created, "Forum")


@receiver(post_delete, sender="intern.Forum")
def _audit_forum_delete(sender, instance, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _log_change(instance, getattr(instance, "_audit_user", None), "delete")


# --- Ort ---
@receiver(pre_save, sender="intern.Ort")
def _audit_ort_pre(sender, instance, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _capture_audit_old(sender, instance, "Ort")


@receiver(post_save, sender="intern.Ort")
def _audit_ort_post(sender, instance, created, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _write_audit_log(instance, created, "Ort")


@receiver(post_delete, sender="intern.Ort")
def _audit_ort_delete(sender, instance, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _log_change(instance, getattr(instance, "_audit_user", None), "delete")

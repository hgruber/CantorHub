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

from django.core.signals import request_finished, request_started
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.contrib.auth.signals import user_logged_out

from .apps import _migrating
from .anfragespeicher import anlegen as anfrage_anlegen
from .anfragespeicher import leeren as anfrage_leeren
from .anfragespeicher import verwerfen as anfrage_verwerfen
from .app_settings import (
    cache_anlegen,
    cache_leeren,
    cache_verwerfen,
    get_config,
    is_ejabberd_configured,
)

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
    3. is_ejabberd_configured() (EJABBERD_HOST + EJABBERD_BOT_JID must be set)
    4. instance.xmpp_muc_jid already set
    """
    if not created:
        return
    if getattr(instance, "_skip_ejabberd_signal", False):
        return
    if getattr(_migrating, "active", False):
        return
    if not is_ejabberd_configured():
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
            instance._old_last_login = old_user.last_login
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

    if is_ejabberd_configured():
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

    # Django's automatic password hash upgrade during authentication:
    # check_password() calls user.save(update_fields=["password"]) when the stored
    # hash uses a weaker algorithm (e.g. php_sha256 → PBKDF2). Treat this as a
    # password change initiated by the user themselves.
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and set(update_fields) == {"password"}:
        if not getattr(instance, "_audit_password_changed", False):
            instance._audit_password_changed = True
            if not getattr(instance, "_audit_user", None):
                instance._audit_user = instance

    # Detect login: Django updates only last_login when a user logs in.
    # The instance itself is the acting user, so set _audit_user if not already set.
    old_last_login = getattr(instance, "_old_last_login", None)
    if not created and instance.last_login != old_last_login:
        instance._audit_is_login = True
        if not getattr(instance, "_audit_user", None):
            instance._audit_user = instance

    _write_audit_log(instance, created, "User")

    # Welcome / reactivation mail when admin activates a user. The data
    # re-confirmation re-enables its own lock: no mail and no Eintrittsdatum then.
    old_vals = getattr(instance, "_audit_old", None) or {}
    if (
        not created
        and old_vals.get("is_active") is False
        and instance.is_active
        and instance.email
        and not getattr(instance, "_ohne_aktivierungsmail", False)
    ):
        _send_activation_mail(instance)


def _send_activation_mail(user):
    """Send welcome or reactivation mail after a user is activated. Never raises."""
    try:
        from django.utils import timezone
        from .app_settings import get_base_url, get_config_bool, get_vereinsname

        if not get_config_bool("MAIL_BEI_AKTIVIERUNG"):
            return
        from .mail import send_config_mail
        from .mitgliedschaft import ist_erstaufnahme, ist_mitglied
        from .models import User

        vereinsname = get_vereinsname()
        # Nur eine echte Aufnahme ins Vereinsleben bekommt Willkommensmail und
        # Eintrittsdatum. Ein Konto ohne Tag „Mitglied" (Chorleiter, Gast) hat nie
        # eines gehabt und gilt beim Wiedereinschalten als Reaktivierung.
        first_activation = ist_erstaufnahme(user.date_joined, ist_mitglied(user))
        if first_activation:
            User.objects.filter(pk=user.pk).update(date_joined=timezone.now())
            text_key = "MAIL_WILLKOMMEN"
            subject = f"Willkommen bei {vereinsname}"
        else:
            text_key = "MAIL_REAKTIVIERT"
            subject = f"Dein Konto bei {vereinsname} wurde wieder aktiviert"

        portal_url = get_base_url()
        login_url = f"{portal_url}/intern/login/" if portal_url else None
        send_config_mail(
            subject=subject,
            to=user.email,
            key=text_key,
            user=user,
            link=login_url,
            context={"mail_title": subject},
        )
    except Exception:
        logger.exception("mail: failed to send activation mail to user %s", user.pk)


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
        "first_name", "last_name", "stimme", "is_active", "is_superuser", "email",
        "xmpp", "strasse", "plz", "ort", "telefon", "telefon_mobil",
        "geburtstag", "avatar_id", "private_fields", "adressbuch_verborgen",
        "notify_enabled",
    ],
    "Termin": ["kurz", "datum", "datum_bis", "lang", "extern", "ort_id", "anwesenheit", "repertoire"],
    "Lied": ["titel", "aktiv", "tempo", "tonart", "beats", "hymne", "acapella", "weihnacht", "komponist",
             "original_id", "aufnahme_id", "pdf_id", "noten_id"],
    "Zusage": ["option"],
    "Forum": ["thema", "aktiv", "bild_id", "xmpp_muc_jid"],
    "Ort": ["name", "beschreibung", "strasse", "plz", "ort", "breite", "laenge"],
    "Artikel": ["name", "version", "kommentar"],
    "Mitteilung": ["mitteilung"],
    "Konfiguration": ["value", "description"],
}

# Konfiguration-Schlüssel, die auf ein Geheimnis hindeuten — deren Wert wird im
# Änderungsprotokoll nie im Klartext abgelegt (siehe _log_change).
_KONFIG_SECRET_MARKERS = ("PASSWORD", "SECRET", "TOKEN")


_THUMBNAIL_SIZES = [
    {"size": (32, 32), "crop": True, "quality": 85},
    {"size": (120, 120), "crop": True, "quality": 85},
    {"size": (200, 200), "quality": 85},
    {"size": (400, 400), "crop": True, "quality": 85},
]

# Cap concurrent thumbnail threads so bulk imports don't exhaust MySQL connections.
_thumb_semaphore = threading.Semaphore(4)


def _process_filer_file(file_pk):
    """Index and pre-generate thumbnails for a newly uploaded filer File.
    Runs in a daemon thread so the upload response is not delayed.
    """
    with _thumb_semaphore:
        try:
            from django.db import connection
            from easy_thumbnails.files import get_thumbnailer
            from filer.models import File as FilerFile

            from .fileindex import index_file

            f = FilerFile.objects.get(pk=file_pk)
            index_file(f)
            for opts in _THUMBNAIL_SIZES:
                try:
                    get_thumbnailer(f.file).get_thumbnail(opts)
                except Exception:
                    pass
        except Exception:
            logger.exception("filer post-save: index/thumbnail failed for file pk=%s", file_pk)
        finally:
            try:
                from django.db import connection
                connection.close()
            except Exception:
                pass


@receiver(post_save, sender="filer.File")
def on_filer_file_saved(sender, instance, created, **kwargs):
    if not created or getattr(_migrating, "active", False):
        return
    file_pk = instance.pk

    def _start():
        threading.Thread(target=_process_filer_file, args=(file_pk,), daemon=True).start()

    from django.db import transaction
    transaction.on_commit(_start)


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
        elif action in (ChangeLog.ACTION_CREATE, ChangeLog.ACTION_APPLICATION):
            for field in allowed:
                val = getattr(instance, field, None)
                if val is not None and val != "" and val is not False:
                    changes[field] = [None, str(val)]
        elif action == ChangeLog.ACTION_DELETE:
            for field in allowed:
                val = getattr(instance, field, None)
                if val is not None and val != "" and val is not False:
                    changes[field] = [str(val), None]
        if model_name == "Konfiguration" and "value" in changes:
            key = (getattr(instance, "key", "") or "").upper()
            if any(marker in key for marker in _KONFIG_SECRET_MARKERS):
                changes["value"] = [
                    "***" if changes["value"][0] is not None else None,
                    "***" if changes["value"][1] is not None else None,
                ]
        if getattr(instance, "_audit_password_changed", False):
            changes["password"] = [None, "geändert"]
            instance._audit_password_changed = False
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
    if getattr(instance, "_audit_is_login", False):
        action = ChangeLog.ACTION_LOGIN
    elif created and getattr(instance, "_audit_application", False):
        action = ChangeLog.ACTION_APPLICATION
    else:
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


# --- Mitteilung ---
@receiver(pre_save, sender="intern.Mitteilung")
def _audit_mitteilung_pre(sender, instance, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _capture_audit_old(sender, instance, "Mitteilung")


@receiver(post_save, sender="intern.Mitteilung")
def _audit_mitteilung_post(sender, instance, created, **kwargs):
    if getattr(_migrating, "active", False):
        return
    # Inject _audit_user from sender FK if not already set
    if not getattr(instance, "_audit_user", None) and instance.sender_id:
        from .models import User as UserModel
        instance._audit_user = UserModel.objects.get(pk=instance.sender_id)
    _write_audit_log(instance, created, "Mitteilung")


@receiver(post_delete, sender="intern.Mitteilung")
def _audit_mitteilung_delete(sender, instance, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _log_change(instance, getattr(instance, "_audit_user", None), "delete")


# --- Artikel ---
@receiver(pre_save, sender="intern.Artikel")
def _audit_artikel_pre(sender, instance, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _capture_audit_old(sender, instance, "Artikel")


@receiver(post_save, sender="intern.Artikel")
def _audit_artikel_post(sender, instance, created, **kwargs):
    if getattr(_migrating, "active", False):
        return
    # Artikel saves are triggered by article_edit; inject _audit_user from autor
    if not getattr(instance, "_audit_user", None) and instance.autor_id:
        instance._audit_user = instance.autor
    _write_audit_log(instance, created, "Artikel")


@receiver(post_delete, sender="intern.Artikel")
def _audit_artikel_delete(sender, instance, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _log_change(instance, getattr(instance, "_audit_user", None), "delete")


# --- Konfiguration ---
@receiver(pre_save, sender="intern.Konfiguration")
def _audit_konfiguration_pre(sender, instance, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _capture_audit_old(sender, instance, "Konfiguration")


@receiver(post_save, sender="intern.Konfiguration")
def _audit_konfiguration_post(sender, instance, created, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _write_audit_log(instance, created, "Konfiguration")


@receiver(post_delete, sender="intern.Konfiguration")
def _audit_konfiguration_delete(sender, instance, **kwargs):
    if getattr(_migrating, "active", False):
        return
    _log_change(instance, getattr(instance, "_audit_user", None), "delete")


# --- Konfigurations-Zwischenspeicher ---
# Lebensdauer und Begründung stehen in app_settings.py. Die Verbindung gehört
# hierher, weil apps.ready() dieses Modul ohnehin importiert — app_settings wird
# von überall her importiert, auch von Kommandos ohne Anfragezyklus, und dürfte
# sich nicht schon beim Import an Signale hängen.
request_started.connect(cache_anlegen, dispatch_uid="intern_konfig_cache_an")
request_finished.connect(cache_verwerfen, dispatch_uid="intern_konfig_cache_aus")

# --- Anfrage-Zwischenspeicher (anfragespeicher.py) ---
# Dieselbe Lebensdauer, andere Werte: sichtbare Ordner und die Fallback-Avatare.
# Eine geänderte Ordnerberechtigung verschiebt die Sichtbarkeit, deshalb leert sie
# den Speicher — wer innerhalb einer Anfrage schreibt, muss danach seinen eigenen
# Stand sehen.
request_started.connect(anfrage_anlegen, dispatch_uid="intern_anfrage_cache_an")
request_finished.connect(anfrage_verwerfen, dispatch_uid="intern_anfrage_cache_aus")
post_save.connect(
    anfrage_leeren, sender="intern.FolderPermission",
    dispatch_uid="intern_anfrage_cache_fp_save",
)
post_delete.connect(
    anfrage_leeren, sender="intern.FolderPermission",
    dispatch_uid="intern_anfrage_cache_fp_delete",
)
post_save.connect(
    cache_leeren, sender="intern.Konfiguration", dispatch_uid="intern_konfig_cache_save"
)
post_delete.connect(
    cache_leeren, sender="intern.Konfiguration", dispatch_uid="intern_konfig_cache_delete"
)


# --- User logout ---
@receiver(user_logged_out)
def _audit_logout(sender, request, user, **kwargs):
    """Write a ChangeLog entry when a user logs out."""
    if getattr(_migrating, "active", False):
        return
    if user is None:
        return
    from .models import ChangeLog
    ChangeLog.objects.create(
        timestamp=datetime.now(),
        user=user,
        action=ChangeLog.ACTION_LOGOUT,
        model_name="User",
        object_id=user.pk,
        object_repr=str(user)[:200],
        changes={},
    )

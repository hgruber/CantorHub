import json
import logging
import threading

from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.core.mail import get_connection
from django.db import connections
from django.db.models import Count, OuterRef
from django.http import HttpResponseForbidden, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django_tables2 import RequestConfig
from ._decorators import tabellenzustand
from ._pagination import ist_nachladen, nachlade_antwort, paginate_ordered, parse_offset

from filer.models import File, Folder

from intern import ejabberd, folders
from intern.app_settings import (
    get_config_bool, get_map_center, get_vereinsname_lang, is_ejabberd_configured,
    konfiguration_gepuffert,
)
from intern.mail import neu_verbinden, send_config_mail, versende_serie

from ..forms import MitgliedAddForm, MitgliedInviteForm, UserEditForm
from ..models import Abstimmung, Artikel, Mitteilung, PRIVACY_FIELDS, User, Zusage
from ..tables import MitgliederFilter, MitgliederTabelle
from .auth import make_invite_token
from .files import _get_file_extension, besitz_uebertragen

logger = logging.getLogger(__name__)

_PAGE_SIZE = 50

__all__ = [
    "mitglied_list",
    "mitglied_emails",
    "mitglied_view",
    "mitglied_edit",
    "mitglied_add",
    "mitglied_invite",
    "mitglied_delete",
    "mitglied_benachrichtigen",
    "mitglied_benachrichtigen_files",
]


@login_required
@tabellenzustand
def mitglied_list(request):
    can_manage = request.user.has_perm("intern.change_user")
    base_qs = User.objects.all() if can_manage else User.objects.filter(is_active=True)
    queryset = (
        base_qs
        .annotate(
            mitteilungen=Mitteilung.objects.filter(sender=OuterRef("pk"))
            .values("sender")
            .annotate(cnt=Count("*"))
            .values("cnt"),
            _stimme_pos=User.stimme_order_case(),
        )
        .prefetch_related("groups")
        .order_by("last_name", "first_name")
    )
    filter_data = request.GET
    if can_manage and "aktiv" not in filter_data:
        filter_data = filter_data.copy()
        filter_data["aktiv"] = "true"
    mitglieder_filter = MitgliederFilter(filter_data, queryset=queryset, can_manage=can_manage)
    from .files import visible_fields

    fields = visible_fields(request, "MitgliederTabelle")
    if not can_manage:
        fields = [f for f in fields if f not in ("aktiv", "gruppen")]

    offset = parse_offset(request)

    probe = MitgliederTabelle(mitglieder_filter.qs, visible_fields=fields, viewer=None)
    page, has_more = paginate_ordered(request, probe, offset, _PAGE_SIZE)
    table = MitgliederTabelle(page, visible_fields=fields, viewer=request.user, counter_offset=offset)
    RequestConfig(request, paginate=False).configure(table)

    if ist_nachladen(request):
        return nachlade_antwort("table_rows.html", {"table": table},
                                has_more, offset + _PAGE_SIZE)

    column_choices = [
        {
            "name": name,
            "label": table.columns[name].header,
            "checked": name in fields,
        }
        for name in table.base_columns
        if can_manage or name not in ("aktiv", "gruppen")
    ]

    return render(
        request,
        "table.html",
        {
            "table": table,
            "column_choices": column_choices,
            "filter": mitglieder_filter,
            "showfilter": True,
            "seitentitel": "Mitgliederliste",
            "topbar_icon": '<svg class="topbar-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
            "add": "mitglied_add" if request.user.has_perm("intern.add_user") else None,
            "add_form": MitgliedAddForm() if request.user.has_perm("intern.add_user") else None,
            "invite_form": MitgliedInviteForm() if request.user.has_perm("intern.add_user") else None,
            "add_panel_include": "mitglied_add_panel.html" if request.user.has_perm("intern.add_user") else None,
            "add_label": "Neues Mitglied",
            "has_more": has_more,
            "next_offset": offset + _PAGE_SIZE,
            "show_email_copy": "email" in fields,
            "notify_url": reverse("mitglied_benachrichtigen") if request.user.has_perm("intern.notify_user") else None,
            # Nur wenn der Dienst freigeschaltet ist — sonst führte der Hinweis
            # ins Leere (jede CardDAV-URL antwortet dann 404).
            "carddav_url": (
                request.build_absolute_uri("/carddav/")
                if get_config_bool("CARDDAV_AKTIV", False) else None
            ),
        },
    )


@login_required
def mitglied_view(request, id):
    user = get_object_or_404(User.objects.prefetch_related("solist", "dirigent", "groups"), id=id)
    can_edit = (
        request.user.id == id
        or request.user.has_perm("intern.change_user")
    )
    can_view_history = request.user.has_perm("intern.change_user")
    visible = {f: user.field_visible_to(request.user, f) for f in PRIVACY_FIELDS}
    map_center = get_map_center()
    context = {
        "user": user,
        "seitentitel": f"{user.first_name} {user.last_name} ({user.stimme})",
        "up": "mitglied_list",
        "edit": "mitglied_edit" if can_edit else None,
        "history": "mitglied_aenderungen" if can_view_history else None,
        "id": id,
        "visible": visible,
        "carddav_aktiv": get_config_bool("CARDDAV_AKTIV", False),
        "map_center_lat": str(map_center[0]),
        "map_center_lng": str(map_center[1]),
        "member_groups": list(user.groups.order_by("name")),
    }
    return render(request, "mitglied.html", context)


@login_required
def mitglied_edit(request, id):
    if (
        request.user.id != id
        and not request.user.has_perm("intern.change_user")
    ):
        return redirect("mitglied_view", id=id)
    user = get_object_or_404(User.objects.prefetch_related("groups"), id=id)
    ist_selbst = request.user.id == id
    # Solange der Dienst aus ist, gaebe es nichts zu widersprechen — dann wird das
    # Feld gar nicht erst gebaut, und ein gespeichertes True ueberlebt unangetastet.
    carddav_aktiv = get_config_bool("CARDDAV_AKTIV", False)

    if request.method == "POST":
        if request.POST.get("action") == "deactivate" and request.user.has_perm("intern.change_user"):
            user.is_active = not user.is_active
            user._audit_user = request.user
            user.save(update_fields=["is_active"])
            if user.is_active:
                messages.success(request, "Mitgliedschaft reaktiviert.")
            else:
                messages.success(request, "Mitgliedschaft ist jetzt ruhend.")
            return redirect("mitglied_edit", id=id)

        form = UserEditForm(
            request.POST, request.FILES, instance=user,
            with_privacy=ist_selbst,
            mit_adressbuch=ist_selbst and carddav_aktiv,
        )
        if form.is_valid():
            # Move dropzone-uploaded avatar to the Profilbilder folder and rename.
            # The avatar text input (set by JS on upload) holds the new filer ID;
            # if it differs from the original, the file was just uploaded.
            new_avatar_id = request.POST.get("avatar")
            old_avatar_id = str(user.avatar_id) if user.avatar_id else ""
            if new_avatar_id and new_avatar_id != old_avatar_id:
                try:
                    f = File.objects.get(pk=int(new_avatar_id))
                    folder_id = folders.avatare()
                    if folder_id:
                        f.folder_id = folder_id
                    ext = _get_file_extension(f.original_filename or f.name or "")
                    new_name = f"{id}{ext}"
                    f.original_filename = new_name
                    f.name = new_name
                    f.save()
                except (File.DoesNotExist, ValueError):
                    pass
            instance = form.save(commit=False)
            instance._audit_user = request.user
            instance.save()
            form.save_m2m()
            return redirect("mitglied_view", id=id)
    else:
        form = UserEditForm(
            instance=user,
            with_privacy=ist_selbst,
            mit_adressbuch=ist_selbst and carddav_aktiv,
        )

    context = {
        "form": form,
        "user": user,
        "seitentitel": f"bearbeiten: {user.first_name} {user.last_name}",
        "view": "mitglied_view",
        "upload_folder_id": folders.avatare(),
        "upload_folder_name": folders.PROFILBILDER,
        "upload_rename_to": id,
        "id": id,
        "can_manage": request.user.has_perm("intern.change_user"),
        "can_set_privacy": ist_selbst,
        "carddav_aktiv": carddav_aktiv,
        "privacy_fields": PRIVACY_FIELDS,
        "member_groups": list(user.groups.order_by("name")),
    }
    return render(request, "mitglied_edit.html", context)


@permission_required("intern.delete_user", raise_exception=True)
@require_POST
def mitglied_delete(request, id):
    member = get_object_or_404(User, id=id)

    # Cannot delete/anonymize yourself
    if member.pk == request.user.pk:
        return redirect("mitglied_edit", id=id)

    # Unregister from XMPP before any data is cleared
    if is_ejabberd_configured() and member.xmpp:
        try:
            ejabberd.unregister_user(ejabberd.localpart_from_username(member.username))
        except Exception as exc:
            logger.error("ejabberd: failed to unregister %s: %s", member.username, exc)

    # Delete avatar in both cases
    if member.avatar_id:
        avatar_file = member.avatar
        member.avatar = None
        member.save(update_fields=["avatar"])
        try:
            avatar_file.delete()
        except Exception:
            pass

    # Files and folders go to the owner of the folder above them, so nothing in
    # the file area points at the member afterwards — which is also why file
    # ownership is no longer part of has_history below.
    besitz_uebertragen(member, fallback=request.user)

    # Determine whether history exists that must be preserved
    has_history = (
        Mitteilung.objects.filter(sender=member).exists()
        or Artikel.objects.filter(autor=member).exists()
        or Abstimmung.objects.filter(person=member).exists()
    )

    if has_history:
        # Anonymize: erase all PII, keep first_name and last_name
        member.username          = f"geloescht_{member.id}"
        member.email             = None
        member.xmpp              = None
        member.telefon           = None
        member.telefon_job       = None
        member.telefon_mobil     = None
        member.telefon_job_mobil = None
        member.fax               = None
        member.geburtstag        = None
        member.strasse           = None
        member.plz               = None
        member.ort               = None
        member.breite            = None
        member.laenge            = None
        member.legacy_id         = None
        member.text              = None
        member.private_fields    = []
        # adressbuch_verborgen wird bewusst NICHT zurueckgesetzt: das waere ein
        # stiller Widerruf des zuletzt geaeusserten Willens. is_active = False
        # nimmt die Person ohnehin aus dem Adressbuch.
        member.stimme            = "N"
        member.is_active         = False
        member.is_staff          = False
        member.is_superuser      = False
        member.set_unusable_password()
        member.groups.clear()
        member.user_permissions.clear()
        # Remove attendance, solo, and conductor roles
        Zusage.objects.filter(person=member).delete()
        member.solist.clear()
        member.dirigent.clear()
        member._audit_user = request.user
        member.save()
    else:
        member._audit_user = request.user
        member.delete()

    return redirect("mitglied_list")


@login_required
def mitglied_emails(request):
    can_manage = request.user.has_perm("intern.change_user")
    base_qs = User.objects.all() if can_manage else User.objects.filter(is_active=True)
    queryset = (
        base_qs
        .annotate(_stimme_pos=User.stimme_order_case())
        .order_by("_stimme_pos", "last_name", "first_name")
    )
    filter_data = request.GET
    if can_manage and "aktiv" not in filter_data:
        filter_data = filter_data.copy()
        filter_data["aktiv"] = "true"
    mitglieder_filter = MitgliederFilter(filter_data, queryset=queryset, can_manage=can_manage)
    entries = []
    for user in mitglieder_filter.qs:
        if user.field_visible_to(request.user, "email") and user.email:
            name = f"{user.first_name} {user.last_name}".strip()
            entries.append(f"{name} <{user.email}>")
    return JsonResponse({"emails": entries})


@permission_required("intern.add_user", raise_exception=True)
@require_POST
def mitglied_invite(request):
    """Verschickt eine Einladung mit signiertem Beitritts-Link an eine E-Mail."""
    form = MitgliedInviteForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Bitte gib eine gültige E-Mail-Adresse ein.")
        return redirect("mitglied_list")

    email = form.cleaned_data["email"]
    if User.objects.filter(email__iexact=email).exists():
        messages.warning(
            request, f"Es existiert bereits ein Mitglied mit der E-Mail {email}."
        )

    token = make_invite_token(email)
    link = request.build_absolute_uri(reverse("mitglied_beitritt", args=[token]))
    send_config_mail(
        f"Einladung zu {get_vereinsname_lang()}",
        email,
        "MAIL_EINLADUNG",
        link=link,
    )
    messages.success(request, f"Einladung an {email} verschickt.")
    return redirect("mitglied_list")


@permission_required("intern.add_user", raise_exception=True)
def mitglied_add(request):
    if request.method == "POST":
        form = MitgliedAddForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user._audit_user = request.user
            user.save()
            return redirect("mitglied_view", id=user.id)
    else:
        form = MitgliedAddForm()
    context = {
        "form": form,
        "seitentitel": "Neues Mitglied",
    }
    return render(request, "mitglied_add.html", context)


def _notify_groups(user):
    """Gruppen des Users, die ihm intern.notify_user verleihen."""
    from django.contrib.auth.models import Permission
    try:
        perm = Permission.objects.get(codename="notify_user", content_type__app_label="intern")
    except Permission.DoesNotExist:
        return []
    return list(
        user.groups.filter(permissions=perm).prefetch_related("user_set").order_by("name")
    )


def _notify_groups_data(groups):
    return [
        {
            "id": g.pk,
            "name": g.name,
            "members": [
                f"{u.first_name} {u.last_name}".strip()
                for u in g.user_set.filter(is_active=True).order_by("last_name", "first_name")
            ],
        }
        for g in groups
    ]


def _log_notify(user, subject, body, sent, attachments, signature_group_name, failed=()):
    from ..models import ChangeLog
    try:
        changes = {
            "betreff": [None, subject],
            "empfaenger": [None, str(sent)],
            "text": [None, body],
        }
        if failed:
            changes["fehlgeschlagen"] = [None, ", ".join(r["name"] or r["email"] for r in failed)]
        if attachments:
            changes["anhaenge"] = [None, ", ".join(a[0] for a in attachments)]
        if signature_group_name:
            changes["gruppe"] = [None, signature_group_name]
        ChangeLog.objects.create(
            user=user,
            action=ChangeLog.ACTION_NOTIFY,
            model_name="Benachrichtigung",
            object_id=0,
            object_repr=subject[:200],
            changes=changes,
        )
    except Exception:
        logger.warning("ChangeLog für Benachrichtigung konnte nicht geschrieben werden.")


def _rundmail_versenden(user, subject, body, recipients, attachments,
                        signature_group_name, signature_members):
    """Verschickt die Rundmail — laeuft im eigenen Thread, nicht im Request.

    Synchron im Request lief der Versand in den gunicorn-Timeout (30 s): jede Mail
    baute ihre eigene SMTP-Verbindung samt TLS und Login auf, und nach etwa acht
    Empfaengern wurde der Worker abgeschossen — der Rest ging nie raus. Jetzt
    antwortet der Request sofort, alle Mails teilen sich eine Verbindung, und das
    Aenderungsprotokoll haelt fest, wie viele tatsaechlich angekommen sind.

    Der Thread ist bewusst kein Daemon: beendet gunicorn den Worker geordnet,
    wartet der Prozess, bis der Versand durch ist (bis zum graceful timeout).
    """
    try:
        with konfiguration_gepuffert():
            connection = get_connection()
            try:
                connection.open()
            except Exception:
                logger.warning("Rundmail: SMTP-Verbindung konnte nicht geoeffnet werden.",
                               exc_info=True)

            def senden(r):
                return send_config_mail(
                    subject,
                    r["email"],
                    "MAIL_RUNDMAIL",
                    template="emails/mitglied_benachrichtigung.html",
                    context={
                        "mail_title": subject,
                        "signature_group_name": signature_group_name,
                        "signature_members": signature_members,
                    },
                    attachments=attachments or None,
                    connection=connection,
                    vorname=r["name"].split()[0] if r["name"] else "",
                    text=body,
                )

            try:
                gesendet, fehlgeschlagen = versende_serie(
                    recipients, senden, lambda: neu_verbinden(connection)
                )
            finally:
                try:
                    connection.close()
                except Exception:
                    pass

        if fehlgeschlagen:
            logger.error(
                "Rundmail '%s': %d von %d nicht zugestellt: %s", subject,
                len(fehlgeschlagen), len(recipients),
                ", ".join(r["email"] for r in fehlgeschlagen),
            )
        logger.info("Rundmail '%s': %d von %d verschickt.",
                    subject, len(gesendet), len(recipients))
        _log_notify(user, subject, body, len(gesendet), attachments, signature_group_name,
                    failed=fehlgeschlagen)
    except Exception:
        logger.exception("Rundmail '%s': Versand abgebrochen.", subject)
    finally:
        # Der Thread hat eine eigene DB-Verbindung; ohne Request schliesst sie niemand.
        connections.close_all()


def _verwaltung_tree(folder_id):
    """Rekursive Ordnerstruktur unterhalb eines Filer-Ordners als verschachtelte Liste."""
    result = []
    for sub in Folder.objects.filter(parent_id=folder_id).order_by("name"):
        children = _verwaltung_tree(sub.pk)
        result.append({"id": sub.pk, "name": sub.name, "type": "folder", "children": children})
    for f in File.objects.filter(folder_id=folder_id).order_by("original_filename", "name"):
        fname = f.original_filename or f.name or f"Datei {f.pk}"
        result.append({"id": f.pk, "name": fname, "type": "file", "mime": f.mime_type or ""})
    return result


@permission_required("intern.notify_user", raise_exception=True)
def mitglied_benachrichtigen(request):
    can_manage = request.user.has_perm("intern.change_user")
    base_qs = User.objects.all() if can_manage else User.objects.filter(is_active=True)
    queryset = (
        base_qs
        .annotate(_stimme_pos=User.stimme_order_case())
        .order_by("_stimme_pos", "last_name", "first_name")
    )
    if request.method == "POST":
        filter_params = request.POST.get("filter_params", "")
        filter_data = QueryDict(filter_params)
    else:
        filter_params = request.GET.urlencode()
        filter_data = request.GET

    if can_manage and "aktiv" not in filter_data:
        filter_data = filter_data.copy()
        filter_data["aktiv"] = "true"
    mitglieder_filter = MitgliederFilter(filter_data, queryset=queryset, can_manage=can_manage)

    recipients = [
        {"pk": u.pk, "name": f"{u.first_name} {u.last_name}".strip(), "email": u.email}
        for u in mitglieder_filter.qs
        if u.email
    ]

    notify_groups = _notify_groups(request.user)
    notify_groups_data = _notify_groups_data(notify_groups)
    valid_group_ids = {g.pk for g in notify_groups}

    if request.method == "POST":
        subject = request.POST.get("subject", "").strip()
        body = request.POST.get("body", "").strip()
        attachment_ids = request.POST.getlist("attachment_ids")
        selected_group_id = request.POST.get("group_id", "").strip()
        errors = []
        if not subject:
            errors.append("Bitte einen Betreff eingeben.")
        if not body:
            errors.append("Bitte einen Text eingeben.")
        if not recipients:
            errors.append("Keine Empfänger mit E-Mail-Adresse gefunden.")
        if len(notify_groups) > 1 and not selected_group_id:
            errors.append("Bitte eine Gruppe für die Signatur wählen.")

        signature_group_name = ""
        signature_members = []
        if selected_group_id and selected_group_id.isdigit():
            gid = int(selected_group_id)
            if gid in valid_group_ids:
                for gd in notify_groups_data:
                    if gd["id"] == gid:
                        signature_group_name = gd["name"]
                        signature_members = gd["members"]
                        break
        elif len(notify_groups) == 1:
            signature_group_name = notify_groups_data[0]["name"]
            signature_members = notify_groups_data[0]["members"]

        attachments = []
        for fid in attachment_ids:
            try:
                fobj = File.objects.get(pk=int(fid))
                with fobj.file.open("rb") as fh:
                    fbytes = fh.read()
                fname = fobj.original_filename or fobj.name or f"anhang_{fid}"
                attachments.append((fname, fbytes, fobj.mime_type or "application/octet-stream"))
            except (File.DoesNotExist, ValueError, Exception) as e:
                logger.warning("Anhang %s konnte nicht geladen werden: %s", fid, e)

        if not errors:
            threading.Thread(
                target=_rundmail_versenden,
                args=(request.user, subject, body, recipients, attachments,
                      signature_group_name, signature_members),
                name="rundmail",
            ).start()
            messages.success(
                request,
                f"E-Mail an {len(recipients)} Mitglied(er) wird im Hintergrund verschickt.",
            )
            list_url = reverse("mitglied_list")
            if filter_params:
                list_url += f"?{filter_params}"
            return redirect(list_url)

        vw_id = folders.mitglieder_verwaltung()
        verwaltung_tree = _verwaltung_tree(vw_id) if vw_id else []
        safe_ids = [int(x) for x in attachment_ids if str(x).strip().isdigit()]
        return render(request, "mitglied_benachrichtigen.html", {
            "seitentitel": "E-Mail verfassen",
            "recipients": recipients,
            "filter_params": filter_params,
            "subject": subject,
            "body": body,
            "attachment_ids_init": safe_ids,
            "verwaltung_tree": verwaltung_tree,
            "notify_groups": notify_groups,
            "notify_groups_data": notify_groups_data,
            "selected_group_id": selected_group_id,
            "errors": errors,
        })

    vw_id = folders.mitglieder_verwaltung()
    verwaltung_tree = _verwaltung_tree(vw_id) if vw_id else []
    return render(request, "mitglied_benachrichtigen.html", {
        "seitentitel": "E-Mail verfassen",
        "recipients": recipients,
        "filter_params": filter_params,
        "subject": "",
        "body": "",
        "attachment_ids_init": [],
        "verwaltung_tree": verwaltung_tree,
        "notify_groups": notify_groups,
        "notify_groups_data": notify_groups_data,
        "selected_group_id": "",
        "errors": [],
    })


@login_required
def mitglied_benachrichtigen_files(request):
    if not request.user.has_perm("intern.notify_user"):
        return HttpResponseForbidden()
    vw_id = folders.mitglieder_verwaltung()
    tree = _verwaltung_tree(vw_id) if vw_id else []
    return JsonResponse({"tree": tree})
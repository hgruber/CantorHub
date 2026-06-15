import logging
import threading

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.db.models import Count, OuterRef
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
from django_tables2 import RequestConfig

from filer.models import File

from intern import ejabberd, folders
from intern.app_settings import get_map_center, is_ejabberd_configured

from ..forms import MitgliedAddForm, UserEditForm
from ..models import Abstimmung, Artikel, Mitteilung, PRIVACY_FIELDS, User, Zusage
from ..tables import MitgliederFilter, MitgliederTabelle
from .files import _get_file_extension

logger = logging.getLogger(__name__)

_PAGE_SIZE = 50

__all__ = [
    "mitglied_list",
    "mitglied_emails",
    "mitglied_view",
    "mitglied_edit",
    "mitglied_passwd",
    "mitglied_add",
    "mitglied_delete",
]


@login_required
def mitglied_list(request):
    can_manage = request.user.has_perm("intern.change_user")
    base_qs = User.objects.all() if can_manage else User.objects.filter(is_active=True)
    queryset = (
        base_qs
        .annotate(
            mitteilungen=Mitteilung.objects.filter(sender=OuterRef("pk"))
            .values("sender")
            .annotate(cnt=Count("*"))
            .values("cnt")
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

    try:
        offset = max(0, int(request.GET.get("offset", 0)))
    except (ValueError, TypeError):
        offset = 0

    page = list(mitglieder_filter.qs[offset : offset + _PAGE_SIZE + 1])
    has_more = len(page) > _PAGE_SIZE
    if has_more:
        page = page[:_PAGE_SIZE]

    table = MitgliederTabelle(page, visible_fields=fields, viewer=request.user, counter_offset=offset)
    RequestConfig(request, paginate=False).configure(table)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        html = render_to_string("table_rows.html", {"table": table})
        return JsonResponse({
            "html": html,
            "has_more": has_more,
            "next_offset": offset + _PAGE_SIZE,
        })

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
            "add_label": "Neues Mitglied",
            "has_more": has_more,
            "next_offset": offset + _PAGE_SIZE,
            "show_email_copy": "email" in fields,
        },
    )


@login_required
def mitglied_view(request, id):
    user = get_object_or_404(User.objects.prefetch_related("solist", "dirigent"), id=id)
    can_edit = (
        request.user.id == id
        or request.user.has_perm("intern.change_user")
    )
    can_change_pass = request.user.id == id or request.user.is_superuser
    can_view_history = request.user.has_perm("intern.change_user")
    visible = {f: user.field_visible_to(request.user, f) for f in PRIVACY_FIELDS}
    map_center = get_map_center()
    context = {
        "user": user,
        "seitentitel": f"{user.first_name} {user.last_name} ({user.stimme})",
        "up": "mitglied_list",
        "edit": "mitglied_edit" if can_edit else None,
        "changepass": "mitglied_passwd" if can_change_pass else None,
        "history": "mitglied_aenderungen" if can_view_history else None,
        "id": id,
        "visible": visible,
        "map_center_lat": str(map_center[0]),
        "map_center_lng": str(map_center[1]),
    }
    return render(request, "mitglied.html", context)


@login_required
def mitglied_edit(request, id):
    if (
        request.user.id != id
        and not request.user.has_perm("intern.change_user")
    ):
        return redirect("mitglied_view", id=id)
    user = get_object_or_404(User, id=id)

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
            with_privacy=(request.user.id == id),
        )
        if form.is_valid():
            # Move dropzone-uploaded avatar to Avatare folder and rename.
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
        form = UserEditForm(instance=user, with_privacy=(request.user.id == id))

    context = {
        "form": form,
        "user": user,
        "seitentitel": f"bearbeiten: {user.first_name} {user.last_name}",
        "view": "mitglied_view",
        "changepass": "mitglied_passwd",
        "upload_folder_id": folders.avatare(),
        "upload_folder_name": "Avatare",
        "upload_rename_to": id,
        "id": id,
        "can_manage": request.user.has_perm("intern.change_user"),
        "can_set_privacy": request.user.id == id,
        "privacy_fields": PRIVACY_FIELDS,
    }
    return render(request, "mitglied_edit.html", context)


@login_required
def mitglied_passwd(request, id):
    target_user = get_object_or_404(User, id=id)

    # Prüfe, ob der aktuelle Benutzer der Zielbenutzer ist oder Superuser
    if request.user.id != target_user.id and not request.user.is_superuser:
        return redirect("mitglied_view", id=id)

    # Wer das eigene Passwort ändert, muss das aktuelle kennen — eine
    # entwendete Session reicht so nicht für eine Kontoübernahme.
    require_current = request.user.id == target_user.id
    form_context = {"user": target_user, "require_current": require_current}

    if request.method == "POST":
        new_password1 = request.POST.get("new_password1")
        new_password2 = request.POST.get("new_password2")

        if require_current and not request.user.check_password(
            request.POST.get("old_password") or ""
        ):
            messages.error(request, "Das aktuelle Passwort ist nicht korrekt.")
            return render(request, "mitglied_passwd.html", form_context)

        # Überprüfe, ob die neuen Passwörter übereinstimmen
        if new_password1 != new_password2:
            messages.error(request, "Die neuen Passwörter stimmen nicht überein.")
            return render(request, "mitglied_passwd.html", form_context)

        # Setze neues Passwort
        target_user.set_password(new_password1)
        target_user.save()

        # Sync password to ejabberd if user has an XMPP account
        if is_ejabberd_configured() and target_user.xmpp:
            localpart = target_user.xmpp.split("@")[0]
            threading.Thread(
                target=ejabberd.set_user_password,
                args=(localpart, new_password1),
                daemon=True,
            ).start()

        messages.success(request, "Das Passwort wurde erfolgreich geändert.")

        # Session gültig halten, ohne das Passwort erneut durch authenticate() zu schicken
        if request.user.id == target_user.id:
            update_session_auth_hash(request, target_user)

        return redirect("mitglied_passwd", id=id)
    else:
        context = {
            **form_context,
            "seitentitel": f"Passwort ändern: {target_user.first_name} {target_user.last_name}",
            "view": "mitglied_view",
            "edit": "mitglied_edit",
            "id": id,
        }
        return render(request, "mitglied_passwd.html", context)


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

    # Determine whether history exists that must be preserved
    has_history = (
        Mitteilung.objects.filter(sender=member).exists()
        or Artikel.objects.filter(autor=member).exists()
        or File.objects.filter(owner=member).exists()
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
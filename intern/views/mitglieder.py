import threading

from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.db.models import Count, OuterRef
from django.shortcuts import get_object_or_404, redirect, render
from django_tables2 import RequestConfig

from filer.models import File

from intern import ejabberd, folders

from ..forms import MitgliedAddForm, UserEditForm
from ..models import Mitteilung, User
from ..tables import MitgliederFilter, MitgliederTabelle
from .files import _get_file_extension

__all__ = [
    "mitglied_list",
    "mitglied_view",
    "mitglied_edit",
    "mitglied_passwd",
    "mitglied_add",
]


@login_required
def mitglied_list(request):
    queryset = (
        User.objects.filter(is_active=True)
        .annotate(
            mitteilungen=Mitteilung.objects.filter(sender=OuterRef("pk"))
            .values("sender")
            .annotate(cnt=Count("*"))
            .values("cnt")
        )
        .order_by("last_name", "first_name")
    )
    mitglieder_filter = MitgliederFilter(request.GET, queryset=queryset)
    from .files import visible_fields

    fields = visible_fields(request, "MitgliederTabelle")
    table = MitgliederTabelle(mitglieder_filter.qs, visible_fields=fields)
    column_choices = [
        {
            "name": name,
            "label": table.columns[name].header,
            "checked": name in fields,
        }
        for name in table.base_columns
    ]

    RequestConfig(request, paginate=False).configure(table)
    return render(
        request,
        "table.html",
        {
            "table": table,
            "column_choices": column_choices,
            "filter": mitglieder_filter,
            "showfilter": True,
            "seitentitel": "Mitgliederliste",
            "add": "mitglied_add" if request.user.has_perm("intern.add_user") else None,
            "add_form": MitgliedAddForm() if request.user.has_perm("intern.add_user") else None,
            "add_label": "Neues Mitglied",
        },
    )


@login_required
def mitglied_view(request, id):
    user = get_object_or_404(User, id=id)
    can_edit = (
        request.user.id == id
        or request.user.is_superuser
        or request.user.has_perm("intern.change_user")
    )
    context = {
        "user": user,
        "seitentitel": f"{user.first_name} {user.last_name} ({user.stimme})",
        "up": "mitglied_list",
        "edit": "mitglied_edit" if can_edit else None,
        "changepass": "mitglied_passwd" if can_edit else None,
        "id": id,
    }
    return render(request, "mitglied.html", context)


@login_required
def mitglied_edit(request, id):
    if (
        request.user.id != id
        and not request.user.is_superuser
        and not request.user.has_perm("intern.change_user")
    ):
        return redirect("mitglied_view", id=id)
    user = get_object_or_404(User, id=id)

    if request.method == "POST":
        form = UserEditForm(request.POST, request.FILES, instance=user)
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
            form.save()
            return redirect("mitglied_view", id=id)
    else:
        form = UserEditForm(instance=user)

    context = {
        "form": form,
        "user": user,
        "seitentitel": f"bearbeiten: {user.first_name} {user.last_name}",
        "view": "mitglied_view",
        "changepass": "mitglied_passwd",
        "upload_folder_id": folders.avatare(),
        "upload_rename_to": id,
        "upload_avatar_user_id": id,
        "id": id,
    }
    return render(request, "mitglied_edit.html", context)


@login_required
def mitglied_passwd(request, id):
    target_user = get_object_or_404(User, id=id)

    # Prüfe, ob der aktuelle Benutzer der Zielbenutzer ist oder Admin
    if (
        request.user.id != target_user.id
        and not request.user.is_superuser
        and not request.user.has_perm("intern.change_user")
    ):
        return redirect("mitglied_view", id=id)

    if request.method == "POST":
        new_password1 = request.POST.get("new_password1")
        new_password2 = request.POST.get("new_password2")

        # Überprüfe, ob die neuen Passwörter übereinstimmen
        if new_password1 != new_password2:
            messages.error(request, "Die neuen Passwörter stimmen nicht überein.")
            return render(request, "mitglied_passwd.html", {"user": target_user})

        # Überprüfe Passwortlänge
        if len(new_password1) < 5:
            messages.error(
                request, "Das neue Passwort muss mindestens 5 Zeichen lang sein."
            )
            return render(request, "mitglied_passwd.html", {"user": target_user})

        # Setze neues Passwort
        target_user.set_password(new_password1)
        target_user.save()

        # Sync password to ejabberd if user has an XMPP account
        if settings.EJABBERD_ENABLED and target_user.xmpp:
            localpart = target_user.xmpp.split("@")[0]
            threading.Thread(
                target=ejabberd.set_user_password,
                args=(localpart, new_password1),
                daemon=True,
            ).start()

        messages.success(request, "Das Passwort wurde erfolgreich geändert.")

        # Wenn der aktuelle Benutzer das Passwort geändert hat, automatisch erneut einloggen
        if request.user.id == target_user.id:
            from django.contrib.auth import authenticate, login

            # Erneutes Einloggen des Benutzers mit dem neuen Passwort
            user = authenticate(username=target_user.username, password=new_password1)
            if user is not None:
                login(request, user)

        return redirect("mitglied_passwd", id=id)
    else:
        context = {
            "user": target_user,
            "seitentitel": f"Passwort ändern: {target_user.first_name} {target_user.last_name}",
            "view": "mitglied_view",
            "edit": "mitglied_edit",
            "id": id,
        }
        return render(request, "mitglied_passwd.html", context)


@permission_required("intern.add_user", raise_exception=True)
def mitglied_add(request):
    if request.method == "POST":
        form = MitgliedAddForm(request.POST)
        if form.is_valid():
            user = form.save()
            return redirect("mitglied_view", id=user.id)
    else:
        form = MitgliedAddForm()
    context = {
        "form": form,
        "seitentitel": "Neues Mitglied",
    }
    return render(request, "mitglied_add.html", context)
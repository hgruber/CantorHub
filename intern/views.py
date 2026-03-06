from datetime import datetime

import django_tables2 as tables
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db.models import Count, F, IntegerField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce, Concat
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.crypto import get_random_string
from django.views.decorators.http import require_POST
from django_tables2 import RequestConfig
from filer.models import File, Folder

from intern.replacements import apply_replacements

from .forms import RegisterForm
from .models import (
    Artikel,
    Forum,
    Lied,
    Mitteilung,
    TabellenPreferenzen,
    Termin,
    User,
    Zusage,
)
from .tables import (
    ForumTabelle,
    MitgliederFilter,
    MitgliederTabelle,
    OrdnerTabelle,
    RepertoireFilter,
    RepertoireTabelle,
    TerminTabelle,
)


def home(request):
    return render(request, "index.html")


def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            try:
                user = User.objects.get(username=form.cleaned_data["username"])
                password = get_random_string(10)
                # user.set_password(password)
                subject = "Dein neues Passwort"
                message = f"""Du kannst Dich sofort im internen Bereich anmelden\nmit deinem Benutzer '{user.username}' und Deinem\nneuen Passwort: {password}"""
                from_email = "webmaster@example.org"
                recipient_list = [user.email]
                send_mail(subject, message, from_email, recipient_list)
                return redirect("register_success")
            except User.DoesNotExist:
                form.add_error(None, "Benutzer existiert nicht")
    else:
        form = RegisterForm()
    return render(request, "register.html", {"form": form})


def register_success(request):
    return render(request, "register_success.html")


@login_required
@require_POST
def upload(request):
    if request.FILES:
        import os

        file = request.FILES["file"]
        folder_id = request.POST.get("folder_id")
        if folder_id is None:
            folder_id = settings.ORDNER_ID_UNSORTIERT
        name, endung = os.path.splitext(file.name)
        song = None
        if endung in [".mp3", ".m4a", ".cap", ".msc", ".mscz", ".pdf"]:
            try:
                if name.startswith("JG-"):
                    song = Lied.objects.get(titel=name[3:])
                else:
                    song = Lied.objects.get(titel=name)
                if song is not None:
                    if endung in [".mp3", ".m4a"]:
                        folder_id = settings.ORDNER_ID_REPERTOIRE
                    elif endung in [".cap", ".msc", ".mscz"]:
                        folder_id = settings.ORDNER_ID_NOTENSATZ
                    else:
                        folder_id = settings.ORDNER_ID_PDF
            except:
                pass
        filer_file = File.objects.create(
            file=file,
            original_filename=file.name,
            name=file.name,
            owner=request.user,
            folder_id=folder_id,
        )
        if song is not None:
            if name.startswith("JG-") and endung in [".mp3", ".m4a"]:
                song.aufnahme_id = filer_file.id
            elif endung == ".pdf":
                song.pdf_id = filer_file.id
            elif endung in [".cap", ".msc", ".mscz"]:
                song.noten_id = filer_file.id
            elif endung in [".mp3", ".m4a"]:
                song.original_id = filer_file.id
            else:
                print("kaputte Endung")
            song.save()
        url = request.META.get("HTTP_ORIGIN") + filer_file.url
        return JsonResponse({"status": "success", "id": filer_file.id, "url": url})


def visible_fields(request, tabelle):
    visible_fields = request.POST.getlist("columns")
    if len(visible_fields) == 0:
        try:
            pref = TabellenPreferenzen.objects.get(person=request.user, tabelle=tabelle)
            return pref.sichtbare_spalten
        except:
            pref = TabellenPreferenzen.objects.get(person=None, tabelle=tabelle)
            return pref.sichtbare_spalten
    else:
        TabellenPreferenzen.objects.update_or_create(
            person=request.user,
            tabelle=tabelle,
            defaults={
                "sichtbare_spalten": visible_fields,
            },
        )
    return visible_fields


@login_required
def folder_view(request, pk):
    folder_up = []
    if pk == 0:
        pk = None
        current = None
        parent = None
        name = "/"
    else:
        current = Folder.objects.get(pk=pk)
        parent = current.parent
        if current is not None:
            folder_up = [
                {
                    "id": parent.id if parent else 0,
                    "original_name": parent.name if parent else "/",
                    "name": "..",
                    "type": "Folder",
                    "besitzer": (
                        (parent.owner.first_name + " " + parent.owner.last_name)
                        if parent
                        else ""
                    ),
                    "created": parent.created_at if parent else None,
                    "modified": parent.modified_at if parent else None,
                }
            ]
        name = current.name

    folderfiles = (
        File.objects.filter(folder=OuterRef("pk"))
        .values("folder")
        .annotate(
            total_size=Sum("_file_size"),
            file_count=Count("id"),
        )
    )
    folders = (
        Folder.objects.filter(parent_id=pk)
        .values(
            "id",
            "name",
            "owner_id",
            besitzer=Concat(
                Coalesce("owner__first_name", Value("")),
                Value(" "),
                Coalesce("owner__last_name", Value("")),
            ),
            type=Value("Folder"),
            created=F("created_at"),
            modified=F("modified_at"),
        )
        .annotate(
            size=Coalesce(
                Subquery(folderfiles.values("total_size"), output_field=IntegerField()),
                0,
            ),
            count=Coalesce(
                Subquery(folderfiles.values("file_count"), output_field=IntegerField()),
                0,
            ),
        )
    )
    files = File.objects.filter(folder_id=pk).values(
        "id",
        "name",
        "original_filename",
        "owner_id",
        link=F("file"),
        besitzer=Concat(
            Coalesce("owner__first_name", Value("")),
            Value(" "),
            Coalesce("owner__last_name", Value("")),
        ),
        type=Value("File"),
        mime=F("mime_type"),
        size=F("_file_size"),
        created=F("uploaded_at"),
        modified=F("modified_at"),
    )
    table = OrdnerTabelle(folder_up + list(folders) + list(files))
    RequestConfig(request, paginate=False).configure(table)

    return render(
        request,
        "table.html",
        {
            "seitentitel": f"Ordner: {name}",
            "folder_id": pk,
            "table": table,
        },
    )


@login_required
def forum_list(request):
    foren = Forum.objects.extra_data().order_by("-zugriff")
    table = ForumTabelle(foren)
    RequestConfig(request, paginate=False).configure(table)
    return render(
        request, "table.html", {"table": table, "seitentitel": "Foren", "folder_id": 3}
    )


@login_required
def forum_view(request, forum):
    messages = Mitteilung.objects.filter(forum_id=forum)[:25]
    last_id = max(msg.id for msg in messages)
    oldest_id = min(msg.id for msg in messages)
    return render(
        request,
        "forum.html",
        {
            "seitentitel": f"Forum: {Forum.objects.get(id=forum).thema}",
            "forum": forum,
            "last_id": last_id,
            "oldest_id": oldest_id,
            "messages": messages,
            "folder_id": 3,
            "up": "forum_list",
            "edit": "forum_edit",
            "id": forum,
        },
    )


@login_required
def forum_get(request, forum, last_id=0):
    if last_id == 0:
        last_id = request.GET.get("last_id", 0)
    messages = Mitteilung.objects.filter(forum_id=forum, id__gt=last_id)
    if messages:
        last_id = max(msg.id for msg in messages)
    return render(
        request,
        "_messages.html",
        {"forum": forum, "last_id": last_id, "messages": messages},
    )


@login_required
def forum_more(request, forum):
    """Return älterer Nachrichten (30 Stück) als HTML‑Snippet."""
    # Wir brauchen die ID der ältesten geladenen Nachricht (Client‑seitig sendet `last_id`).
    oldest_id = request.GET.get("oldest_id", 0)
    last_id = request.GET.get("last_id", 0)
    messages = Mitteilung.objects.filter(forum_id=forum, id__lt=oldest_id)
    return render(
        request,
        "_messages.html",
        {
            "forum": forum,
            "last_id": last_id,
            "oldest_id": oldest_id,
            "messages": messages,
        },
    )


@login_required
@require_POST
def forum_send(request, forum):
    mitteilung = request.POST.get("mitteilung", "").strip()
    last_id = request.POST.get("last_id", 0)
    if mitteilung:
        Mitteilung.objects.create(
            sender_id=request.user.id,
            forum_id=forum,
            mitteilung=mitteilung,
            datum=datetime.now(),
        )
    return forum_get(request, forum, last_id)


@login_required
def titel_list(request):
    queryset = Lied.objects.order_by("titel")
    konzerte = request.GET.getlist("konzert")
    repertoire_filter = RepertoireFilter(request.GET, queryset=queryset)
    fields = visible_fields(request, "RepertoireTabelle")
    if len(konzerte) == 1:
        qs = (
            repertoire_filter.qs.annotate(position=F("konzert__position"))
            .distinct()
            .order_by("position")
        )
        fields.append("position")
    else:
        qs = repertoire_filter.qs
    table = RepertoireTabelle(
        qs,
        visible_fields=fields,
    )
    column_choices = [
        {
            "name": name,
            "label": table.columns[name].header,
            "checked": name in fields,
        }
        for name in table.base_columns
        if name != "position"
    ]
    RequestConfig(request, paginate=False).configure(table)
    if len(konzerte) == 1:
        seitentitel = f"Ablauf {Termin.objects.get(id=konzerte[0])}"
    else:
        seitentitel = "Repertoire"

    return render(
        request,
        "table.html",
        {
            "table": table,
            "column_choices": column_choices,
            "visible_fields": fields,
            "filter": repertoire_filter,
            "seitentitel": seitentitel,
            "folder_id": 5,
            "search": True,
            "order": len(konzerte) == 1,
        },
    )


@login_required
def termin_list(request):
    # Erweitere das QuerySet um die Anwesenheitsinformationen für den eingeloggten Benutzer
    termin_queryset = Termin.objects.filter(datum__gt=datetime.now()).order_by("datum")

    # Füge die Anwesenheitsinformationen für den aktuellen Benutzer hinzu
    if request.user.is_authenticated:
        termin_queryset = termin_queryset.annotate(
            anwesenheit_option=Coalesce(
                Subquery(
                    Zusage.objects.filter(
                        termin=OuterRef("pk"), person=request.user
                    ).values("option")[:1]
                ),
                Value(""),
            )
        )

    table = TerminTabelle(termin_queryset)
    RequestConfig(request, paginate=False).configure(table)
    return render(request, "table.html", {"table": table, "seitentitel": "Termine"})


@login_required
def member_list(request):
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
            "search": True,
            "seitentitel": "Mitgliederliste",
        },
    )


@login_required
def member_view(request, id):
    user = get_object_or_404(User, id=id)
    context = {
        "user": user,
        "seitentitel": f"{user.first_name} {user.last_name} ({user.stimme})",
        "up": "member_list",
        "edit": "member_edit",
        "folder_id": 4,
        "id": id,
    }
    return render(request, "mitglied.html", context)


@login_required
def article_list(request):
    artikel = Artikel.objects.values_list("name", flat=True).distinct()
    context = {
        "seitentitel": "Alle Artikel",
        "artikel": artikel,
    }
    return render(request, "wiki.html", context)


@login_required
def article_edit(request, name):
    artikel = Artikel.objects.filter(name=name).order_by("-id").first()
    context = {
        "artikel": artikel,
        "text": "<pre><code>" + artikel.text + "</code></pre>" if artikel else "",
        "seitentitel": f"bearbeiten: {name}",
        "up": "article_list",
        "view": "article_view",
        "id": artikel,
        "back": "",
    }
    return render(request, "artikel.html", context)


@login_required
def article_view(request, name):
    artikel = Artikel.objects.filter(name=name).order_by("-id").first()
    if not artikel:
        return redirect(f"/intern/artikel/{name}/bearbeiten/")
    context = {
        "artikel": artikel,
        "text": apply_replacements(artikel.text, request),
        "seitentitel": artikel.name,
        "folder_id": 4,
        "up": "article_list",
        "edit": "article_edit",
        "id": artikel.name,
    }
    return render(request, "artikel.html", context)


def dummy(request, *args, **kwargs):
    context = {
        "seitentitel": "Nicht implementiert",
        "args": args,
        "kwargs": kwargs,
    }
    return render(request, "dummy.html", context)

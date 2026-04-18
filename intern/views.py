import difflib
import json
import logging
import os
import secrets
import threading
from datetime import date, datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required, permission_required
from django.core.mail import send_mail
from django.db.models import Count, F, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce, Concat
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.utils.timezone import now
from django.views.decorators.http import require_POST
from django_tables2 import RequestConfig
from filer.models import File, Folder
from icalendar import Calendar, Event

from intern import ejabberd, folders
from intern.replacements import apply_replacements

from .forms import RegisterForm, UserEditForm
from .models import (
    Artikel,
    Forum,
    Konzert,
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

logger = logging.getLogger(__name__)


def _provision_xmpp_user(user_pk, password):
    """Create an ejabberd account for a user and set their vCard. Runs in a daemon thread."""
    from .models import User

    try:
        user = User.objects.get(pk=user_pk)
    except User.DoesNotExist:
        return

    if user.xmpp:
        return

    jid = ejabberd.register_user(user.username, password)
    if not jid:
        return

    User.objects.filter(pk=user_pk).update(xmpp=jid)

    full_name = f"{user.first_name} {user.last_name}".strip() or user.username
    localpart = jid.split("@")[0]
    ejabberd.set_vcard(localpart, full_name, avatar_file=user.avatar)


class CantorLoginView(auth_views.LoginView):
    """Login view that provisions ejabberd accounts on first login."""

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.get_user()
        if settings.EJABBERD_ENABLED and not user.xmpp:
            password = form.cleaned_data["password"]
            threading.Thread(
                target=_provision_xmpp_user,
                args=(user.pk, password),
                daemon=True,
            ).start()
        return response


def home(request):
    return render(request, "index.html")


def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            try:
                user = User.objects.get(username=form.cleaned_data["username"])
                password = get_random_string(10)
                user.set_password(password)
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


def _get_file_extension(filename):
    """Extract file extension from filename"""
    return os.path.splitext(filename)[1].lower()


def _get_file_type_config(extension):
    """Get file type config for given extension"""
    for file_type, config in settings.FILE_TYPE_CONFIG.items():
        if extension in config["extensions"]:
            return file_type, config
    return None, None


def _get_lied_by_filename(filename):
    """Look up Lied object by filename (with JG- prefix support)"""
    name, _ = os.path.splitext(filename)
    try:
        if name.startswith("JG-"):
            return Lied.objects.get(titel=name[3:])
        return Lied.objects.get(titel=name)
    except Lied.DoesNotExist:
        return None


@login_required
@require_POST
def upload(request):
    if request.FILES:
        file = request.FILES["file"]
        preferred_folder_id = request.POST.get("folder_id")

        # Extract extension
        extension = _get_file_extension(file.name)

        # Get file type config if extension is special
        file_type, file_type_config = _get_file_type_config(extension)

        # Look up song if filename matches
        song = _get_lied_by_filename(file.name)

        # Determine folder_id
        # If file is found in Lied table, use the folder_id from the appropriate field
        if song and file_type and file_type_config:
            folder_id = folders._get(file_type_config["folder_name"])
        elif song and hasattr(song, f"{file_type}_id"):
            # Use the folder_id from the song's specific field
            field_name = f"{file_type}_id"
            folder_id = getattr(song, field_name)
        else:
            folder_id = preferred_folder_id or folders.unsortiert()

        # Create file record
        filer_file = File.objects.create(
            file=file,
            original_filename=file.name,
            name=file.name,
            owner=request.user,
            folder_id=folder_id,
        )

        # Update song if applicable
        if song and file_type:
            # Update song with appropriate file field
            field_name = settings.FILE_TYPE_LIED_MAP.get(file_type)
            if field_name:
                setattr(song, field_name, filer_file)
                song.save()

        # Return response
        url = request.META.get("HTTP_ORIGIN") + filer_file.url
        return JsonResponse({"status": "success", "id": filer_file.id, "url": url})


def visible_fields(request, tabelle):
    visible_fields = request.POST.getlist("columns")
    if len(visible_fields) == 0:
        try:
            pref = TabellenPreferenzen.objects.get(person=request.user, tabelle=tabelle)
            return pref.sichtbare_spalten
        except TabellenPreferenzen.DoesNotExist:
            try:
                pref = TabellenPreferenzen.objects.get(person=None, tabelle=tabelle)
                return pref.sichtbare_spalten
            except TabellenPreferenzen.DoesNotExist:
                return []
    else:
        TabellenPreferenzen.objects.update_or_create(
            person=request.user,
            tabelle=tabelle,
            defaults={
                "sichtbare_spalten": visible_fields,
            },
        )
    return visible_fields


def _build_folder_flat(exclude_pk=None):
    """Return all folders as a flat list with full path strings, for the folder picker."""
    all_fldrs = list(Folder.objects.order_by("name").values("id", "name", "parent_id"))
    folder_map = {f["id"]: f for f in all_fldrs}

    def path_of(f):
        parts = [f["name"]]
        cur = f
        seen = set()
        while cur["parent_id"] and cur["parent_id"] not in seen:
            seen.add(cur["id"])
            par = folder_map.get(cur["parent_id"])
            if not par:
                break
            parts.append(par["name"])
            cur = par
        return " / ".join(reversed(parts))

    return [
        {"id": f["id"], "path": path_of(f)} for f in all_fldrs if f["id"] != exclude_pk
    ]


def _folder_breadcrumb(folder):
    """Walk parent chain and return list of {name, pk} from root → current."""
    crumbs = []
    cur = folder
    while cur:
        crumbs.append({"name": cur.name, "pk": cur.pk})
        cur = cur.parent
    crumbs.reverse()
    return crumbs


@login_required
def folder_view(request, pk):
    original_pk = pk  # 0 means root; keep for URLs
    folder_up = []
    if pk == 0:
        pk = None
        current = None
        parent = None
        name = "/"
        breadcrumb = []
    else:
        current = Folder.objects.get(pk=pk)
        parent = current.parent
        breadcrumb = _folder_breadcrumb(current)
        if current is not None:
            folder_up = [
                {
                    "id": parent.id if parent else 0,
                    "original_name": parent.name if parent else "/",
                    "name": "..",
                    "type": "Folder",
                    "besitzer": (
                        (parent.owner.first_name + " " + parent.owner.last_name)
                        if parent and parent.owner
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

    path_str = " / ".join(c["name"] for c in breadcrumb) if breadcrumb else "/"
    return render(
        request,
        "table.html",
        {
            "seitentitel": f"Ordner: {path_str}",
            "breadcrumb": breadcrumb,
            "folder_id": pk,
            "table": table,
            "show_file_actions": True,
            "new_folder_pk": original_pk,
            "current_pk": original_pk,
            "all_folders_flat": _build_folder_flat(),
        },
    )


@permission_required("filer.add_folder", raise_exception=True)
@require_POST
def folder_create(request, pk):
    name = request.POST.get("name", "").strip()
    if name:
        Folder.objects.create(
            name=name,
            parent_id=pk if pk != 0 else None,
            owner=request.user,
        )
        folders.invalidate()
    return redirect("folder_view", pk=pk)


def _parse_items(post):
    """Parse 'item' list of 'Type:id' strings from POST data."""
    items = []
    for raw in post.getlist("item"):
        if ":" in raw:
            t, _, i = raw.partition(":")
            items.append((t, int(i)))
    return items


@permission_required("filer.add_folder", raise_exception=True)
@require_POST
def folder_delete(request):
    referer_pk = int(request.POST.get("referer_pk", 0))
    for item_type, item_id in _parse_items(request.POST):
        if item_type == "Folder":
            Folder.objects.filter(pk=item_id).delete()
        else:
            File.objects.filter(pk=item_id).delete()
    return redirect("folder_view", pk=referer_pk)


@permission_required("filer.add_folder", raise_exception=True)
@require_POST
def folder_move(request):
    referer_pk = int(request.POST.get("referer_pk", 0))
    raw_target = request.POST.get("target_pk", "")
    target_id = int(raw_target) if raw_target and raw_target != "0" else None
    for item_type, item_id in _parse_items(request.POST):
        if item_type == "Folder":
            Folder.objects.filter(pk=item_id).update(parent_id=target_id)
        else:
            File.objects.filter(pk=item_id).update(folder_id=target_id)
    return redirect("folder_view", pk=referer_pk)


@permission_required("filer.add_folder", raise_exception=True)
@require_POST
def folder_copy(request):
    referer_pk = int(request.POST.get("referer_pk", 0))
    raw_target = request.POST.get("target_pk", "")
    target_id = int(raw_target) if raw_target and raw_target != "0" else None
    for item_type, item_id in _parse_items(request.POST):
        if item_type == "File":
            try:
                f = File.objects.get(pk=item_id)
                File.objects.create(
                    file=f.file,
                    original_filename=f.original_filename,
                    name=f.name,
                    owner=request.user,
                    folder_id=target_id,
                    mime_type=f.mime_type,
                )
            except File.DoesNotExist:
                pass
    return redirect("folder_view", pk=referer_pk)


@login_required
def forum_list(request):
    foren = Forum.objects.extra_data().order_by("-zugriff")
    table = ForumTabelle(foren)
    RequestConfig(request, paginate=False).configure(table)
    return render(
        request,
        "table.html",
        {"table": table, "seitentitel": "Foren", "folder_id": folders.forum()},
    )


@login_required
def forum_view(request, forum):
    messages = Mitteilung.objects.filter(forum_id=forum)[:25]
    last_id = max((msg.id for msg in messages), default=0)
    oldest_id = min((msg.id for msg in messages), default=0)
    return render(
        request,
        "forum.html",
        {
            "seitentitel": f"Forum: {Forum.objects.get(id=forum).thema}",
            "forum": forum,
            "last_id": last_id,
            "oldest_id": oldest_id,
            "messages": messages,
            "folder_id": folders.forum(),
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
        msg = Mitteilung.objects.create(
            sender_id=request.user.id,
            forum_id=forum,
            mitteilung=mitteilung,
            datum=datetime.now(),
        )
        # Forward to XMPP MUC in background thread
        if settings.EJABBERD_ENABLED:
            threading.Thread(
                target=_forward_to_xmpp,
                args=(msg,),
                daemon=True,
            ).start()
    return forum_get(request, forum, last_id)


def _forward_to_xmpp(msg):
    """Forward a forum message to the corresponding XMPP MUC room."""
    try:
        forum = msg.forum
        if not forum.xmpp_muc_jid:
            return
        if not settings.EJABBERD_ENABLED:
            return
        sender_name = str(msg.sender) if msg.sender else "Anonymous"
        text = f"*{sender_name}*: {msg.mitteilung}"
        ejabberd.send_muc_message(forum.xmpp_muc_jid, text)
    except Exception as exc:
        logger.error("ejabberd: failed to forward message %s to MUC: %s", msg.id, exc)


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
    remaining_table = []
    if len(konzerte) == 1:
        seitentitel = f"Ablauf {Termin.objects.get(id=konzerte[0])}"
        remaining_qs = (
            Lied.objects.exclude(konzert__termin__id=konzerte[0])
            .annotate(
                position=Value("-"),
                cnt=Count(
                    1,
                    filter=Q(konzert__termin__datum__gt=date(2015, 12, 23)),
                ),
            )
            .order_by("-cnt", "titel")
        )
        remaining_table = RepertoireTabelle(
            remaining_qs, visible_fields=["position", "titel"]
        )
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
            "pool": remaining_table,
            "seitentitel": seitentitel,
            "folder_id": folders.musik(),
            "showfilter": True,
            "order": len(konzerte) == 1,
        },
    )


@permission_required("intern.change_lied", raise_exception=True)
@require_POST
def update_order(request):
    try:
        data = json.loads(request.body)
        konzert_id = data.get("konzert_id")
        order = data.get("order", [])
        Konzert.objects.filter(termin__id=konzert_id).delete()
        k = [
            Konzert(position=position, lied_id=lied_id, termin_id=konzert_id)
            for position, lied_id in enumerate(order)
        ]
        Konzert.objects.bulk_create(k)
        return JsonResponse({"status": "success"})

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


def calendar_ics(request, secret):
    if not secrets.compare_digest(secret, settings.ICAL_SECRET):
        raise Http404
    cutoff = datetime.now() - timedelta(days=180)
    termine = Termin.objects.filter(datum__gte=cutoff).select_related("ort").order_by("datum")
    cal = Calendar()
    cal.add("prodid", "-//CantorHub//DE")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "CantorHub")
    for t in termine:
        ev = Event()
        ev.add("uid", f"termin-{t.pk}@cantorhub")
        ev.add("summary", t.kurz)
        ev.add("dtstart", t.datum)
        ev.add("dtend", t.datum_bis or t.datum + timedelta(hours=2))
        if t.lang:
            ev.add("description", t.lang)
        if t.ort:
            parts = [t.ort.name, t.ort.strasse, f"{t.ort.plz or ''} {t.ort.ort or ''}".strip()]
            ev.add("location", ", ".join(p for p in parts if p))
            if t.ort.breite is not None and t.ort.laenge is not None:
                ev.add("geo", (t.ort.breite, t.ort.laenge))
        cal.add_component(ev)
    return HttpResponse(cal.to_ical(), content_type="text/calendar; charset=utf-8")


@login_required
def termin_list(request):
    # Erweite das QuerySet um die Anwesenheitsinformationen für den eingeloggten Benutzer
    termin_queryset = (
        Termin.objects.filter(datum__gt=datetime.now())
        .order_by("datum")
        .annotate(
            anwesenheit_option=Coalesce(
                Subquery(
                    Zusage.objects.filter(
                        termin=OuterRef("pk"), person=request.user
                    ).values("option")[:1]
                ),
                Value(""),
            ),
            anzahl_songs=Count("konzert", distinct=True),
            anzahl_zusagen_sopran=Count(
                "zusage",
                filter=Q(zusage__person__stimme="S", zusage__option="1"),
                distinct=True,
            ),
            anzahl_zusagen_alt=Count(
                "zusage",
                filter=Q(zusage__person__stimme="A", zusage__option="1"),
                distinct=True,
            ),
            anzahl_zusagen_tenor=Count(
                "zusage",
                filter=Q(zusage__person__stimme="T", zusage__option="1"),
                distinct=True,
            ),
            anzahl_zusagen_bass=Count(
                "zusage",
                filter=Q(zusage__person__stimme="B", zusage__option="1"),
                distinct=True,
            ),
            anzahl_vielleicht=Count(
                "zusage",
                filter=Q(zusage__option="3"),
                distinct=True,
            ),
            anzahl_absagen=Count(
                "zusage",
                filter=Q(zusage__option="2"),
                distinct=True,
            ),
        )
    )

    table = TerminTabelle(termin_queryset)
    RequestConfig(request, paginate=False).configure(table)
    ical_path = reverse("calendar_ics", args=[settings.ICAL_SECRET])
    ical_url = request.build_absolute_uri(ical_path)
    webcal_url = "webcal://" + request.get_host() + ical_path
    return render(
        request,
        "table.html",
        {
            "table": table,
            "seitentitel": "Termine",
            "ical_url": ical_url,
            "webcal_url": webcal_url,
        },
    )


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
            "showfilter": True,
            "seitentitel": "Mitgliederliste",
        },
    )


@login_required
def member_view(request, id):
    user = get_object_or_404(User, id=id)
    can_edit = (
        request.user.id == id
        or request.user.is_superuser
        or request.user.has_perm("intern.change_user")
    )
    context = {
        "user": user,
        "seitentitel": f"{user.first_name} {user.last_name} ({user.stimme})",
        "up": "member_list",
        "edit": "member_edit" if can_edit else None,
        "changepass": "member_passwd" if can_edit else None,
        "folder_id": folders.artikel(),
        "id": id,
    }
    return render(request, "mitglied.html", context)


@login_required
def member_edit(request, id):
    if (
        request.user.id != id
        and not request.user.is_superuser
        and not request.user.has_perm("intern.change_user")
    ):
        return redirect("member_view", id=id)
    user = get_object_or_404(User, id=id)

    if request.method == "POST":
        form = UserEditForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            form.save()
            return redirect("member_view", id=id)
    else:
        form = UserEditForm(instance=user)

    context = {
        "form": form,
        "user": user,
        "seitentitel": f"bearbeiten: {user.first_name} {user.last_name}",
        "view": "member_view",
        "changepass": "member_passwd",
        "folder_id": folders.artikel(),
        "id": id,
    }
    return render(request, "member_edit.html", context)


@login_required
def member_passwd(request, id):
    target_user = get_object_or_404(User, id=id)

    # Prüfe, ob der aktuelle Benutzer der Zielbenutzer ist oder Admin
    if (
        request.user.id != target_user.id
        and not request.user.is_superuser
        and not request.user.has_perm("intern.change_user")
    ):
        return redirect("member_view", id=id)

    if request.method == "POST":
        new_password1 = request.POST.get("new_password1")
        new_password2 = request.POST.get("new_password2")

        # Überprüfe, ob die neuen Passwörter übereinstimmen
        if new_password1 != new_password2:
            messages.error(request, "Die neuen Passwörter stimmen nicht überein.")
            return render(request, "member_passwd.html", {"user": target_user})

        # Überprüfe Passwortlänge
        if len(new_password1) < 5:
            messages.error(
                request, "Das neue Passwort muss mindestens 5 Zeichen lang sein."
            )
            return render(request, "member_passwd.html", {"user": target_user})

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

        return redirect("member_passwd", id=id)
    else:
        context = {
            "user": target_user,
            "seitentitel": f"Passwort ändern: {target_user.first_name} {target_user.last_name}",
            "view": "member_view",
            "edit": "member_edit",
            "id": id,
        }
        return render(request, "member_passwd.html", context)


@login_required
def article_list(request):
    artikel = Artikel.objects.values_list("name", flat=True).distinct()
    context = {
        "seitentitel": "Alle Artikel",
        "artikel": artikel,
    }
    return render(request, "wiki.html", context)


@permission_required("intern.change_artikel", raise_exception=True)
def article_edit(request, name):
    artikel = Artikel.objects.filter(name=name).order_by("-id").first()

    if request.method == "POST":
        text = request.POST.get("text", "")
        kommentar = request.POST.get("kommentar", "")
        next_version = (artikel.version + 1) if artikel else 1
        Artikel.objects.create(
            name=name,
            version=next_version,
            datum=now(),
            autor=request.user,
            kommentar=kommentar,
            text=text,
        )
        return redirect("article_view", name=name)

    context = {
        "artikel": artikel,
        "edit_text": artikel.text if artikel else "",
        "seitentitel": f"bearbeiten: {name}",
        "up": "article_list",
        "view": "article_view",
        "history": "article_history",
        "id": name,
        "back": "",
    }
    return render(request, "artikel.html", context)


@login_required
def article_view(request, name):
    latest = Artikel.objects.filter(name=name).order_by("-version").first()
    if not latest:
        return redirect(f"/intern/artikel/{name}/bearbeiten/")

    version_param = request.GET.get("version")
    if version_param:
        artikel = get_object_or_404(Artikel, name=name, version=version_param)
        is_outdated = artikel.version < latest.version
    else:
        artikel = latest
        is_outdated = False

    context = {
        "artikel": artikel,
        "text": apply_replacements(artikel.text, request),
        "seitentitel": f"{artikel.name} (vom {artikel.datum.strftime('%-d.%-m.%Y')})"
        if is_outdated
        else artikel.name,
        "is_outdated": is_outdated,
        "latest_version": latest.version,
        "folder_id": folders.artikel(),
        "up": "article_list",
        "edit": "article_edit"
        if request.user.has_perm("intern.change_artikel")
        else None,
        "history": "article_history",
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


@login_required
def article_history(request, name):
    versions = list(Artikel.objects.filter(name=name).order_by("version"))
    if not versions:
        return redirect("article_list")

    rows = []
    for i, v in enumerate(versions):
        if i == 0:
            lines_added = len(v.text.splitlines())
            lines_removed = 0
        else:
            prev = versions[i - 1]
            diff = list(
                difflib.unified_diff(
                    prev.text.splitlines(), v.text.splitlines(), lineterm=""
                )
            )
            lines_added = sum(
                1 for l in diff if l.startswith("+") and not l.startswith("+++")
            )
            lines_removed = sum(
                1 for l in diff if l.startswith("-") and not l.startswith("---")
            )
        rows.append(
            {
                "version": v,
                "lines_added": lines_added,
                "lines_removed": lines_removed,
            }
        )
    rows.reverse()

    context = {
        "seitentitel": f"Versionen: {name}",
        "name": name,
        "rows": rows,
        "up": "article_list",
        "view": "article_view",
        "edit": "article_edit",
        "id": name,
    }
    return render(request, "artikel_history.html", context)


@login_required
def article_diff(request, name):
    try:
        v1 = int(request.GET.get("v1", ""))
        v2 = int(request.GET.get("v2", ""))
    except (TypeError, ValueError):
        return redirect("article_history", name=name)

    if v1 > v2:
        v1, v2 = v2, v1

    old = get_object_or_404(Artikel, name=name, version=v1)
    new = get_object_or_404(Artikel, name=name, version=v2)

    old_lines = old.text.splitlines()
    new_lines = new.text.splitlines()

    mode = request.GET.get("mode", "unified")

    side_table = None
    if mode == "side":
        differ = difflib.HtmlDiff(wrapcolumn=80)
        side_table = differ.make_table(
            old_lines,
            new_lines,
            fromdesc=f"Version {v1} – {old.datum.strftime('%d.%m.%Y %H:%M')} ({old.autor})",
            todesc=f"Version {v2} – {new.datum.strftime('%d.%m.%Y %H:%M')} ({new.autor})",
            context=True,
            numlines=3,
        )

    unified_lines = []
    raw = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=3))
    for line in raw[2:]:  # skip --- / +++ header
        if line.startswith("@@"):
            unified_lines.append(("hunk", line))
        elif line.startswith("+"):
            unified_lines.append(("add", line[1:]))
        elif line.startswith("-"):
            unified_lines.append(("del", line[1:]))
        else:
            unified_lines.append(("ctx", line[1:] if line.startswith(" ") else line))

    context = {
        "seitentitel": f"Diff: {name} v{v1}→v{v2}",
        "name": name,
        "old": old,
        "new": new,
        "v1": v1,
        "v2": v2,
        "mode": mode,
        "side_table": side_table,
        "unified_lines": unified_lines,
        "up": "article_list",
        "view": "article_view",
        "edit": "article_edit",
        "history": "article_history",
        "id": name,
    }
    return render(request, "artikel_diff.html", context)

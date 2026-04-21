import logging
import threading
from datetime import datetime

from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.core.mail import send_mail
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django_tables2 import RequestConfig

from filer.models import File

from intern import ejabberd, folders

from ..forms import ForumEditForm
from ..models import Forum, Mitteilung, User
from ..tables import ForumTabelle

__all__ = [
    "forum_list",
    "forum_view",
    "forum_get",
    "forum_more",
    "forum_send",
    "forum_edit",
    "forum_invite",
    "forum_add",
]

logger = logging.getLogger(__name__)


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


def _forum_user_lists(forum_obj):
    """Compute invited, attending, without_invitation, without_xmpp user lists for a forum."""
    active_users = list(User.objects.filter(is_active=True).order_by("last_name", "first_name"))

    if settings.EJABBERD_ENABLED and forum_obj.xmpp_muc_jid:
        from . import ejabberd as xmpp

        room_members = xmpp.get_room_members(forum_obj.xmpp_muc_jid)
        member_jids = {jid.lower() for jid, _aff in room_members}

        room_occupants = xmpp.get_room_occupants(forum_obj.xmpp_muc_jid)
        occupant_jids = {jid.split("/")[0].lower() for jid, _nick in room_occupants}

        invited = [u for u in active_users if u.xmpp and u.xmpp.lower() in member_jids]
        attending = [u for u in active_users if u.xmpp and u.xmpp.lower() in occupant_jids]
        with_xmpp = {u.xmpp.lower() for u in active_users if u.xmpp}
        without_invitation = [u for u in active_users if u.xmpp and u.xmpp.lower() not in member_jids]
        without_xmpp = [u for u in active_users if not u.xmpp]
    else:
        sender_ids = set(
            Mitteilung.objects.filter(forum=forum_obj)
            .values_list("sender_id", flat=True)
        )
        invited = [u for u in active_users if u.id in sender_ids]
        attending = invited
        without_invitation = [u for u in active_users if u.id not in sender_ids]
        without_xmpp = []

    return {
        "invited": invited,
        "attending": attending,
        "without_invitation": without_invitation,
        "without_xmpp": without_xmpp,
    }


@login_required
def forum_list(request):
    foren = Forum.objects.extra_data().order_by("-zugriff")
    table = ForumTabelle(foren)
    RequestConfig(request, paginate=False).configure(table)
    add = "forum_add" if request.user.has_perm("intern.add_forum") else None
    return render(
        request,
        "table.html",
        {
            "table": table,
            "seitentitel": "Foren",
            "upload_folder_id": folders.forum(),
            "add": add,
            "add_form": ForumEditForm() if request.user.has_perm("intern.add_forum") else None,
            "add_form_multipart": True,
            "add_label": "Neues Forum",
        },
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
            "upload_folder_id": folders.forum(),
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
    """Return älterer Nachrichten (30 Stück) als HTML-Snippet."""
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


@login_required
def forum_edit(request, forum):
    forum_obj = get_object_or_404(Forum, id=forum)

    if request.method == "POST":
        form = ForumEditForm(request.POST, request.FILES, instance=forum_obj)
        if form.is_valid():
            # Move dropzone-uploaded bild to Forum folder
            new_bild_id = request.POST.get("bild")
            old_bild_id = str(forum_obj.bild_id) if forum_obj.bild_id else ""
            if new_bild_id and new_bild_id != old_bild_id:
                try:
                    f = File.objects.get(pk=int(new_bild_id))
                    folder_id = folders.forum()
                    if folder_id:
                        f.folder_id = folder_id
                        f.save()
                except (File.DoesNotExist, ValueError):
                    pass
            form.save()
            return redirect("forum_view", forum=forum)
    else:
        form = ForumEditForm(instance=forum_obj)

    user_lists = _forum_user_lists(forum_obj)

    context = {
        "form": form,
        "seitentitel": f"bearbeiten: {forum_obj.thema}",
        "view": "forum_view",
        "id": forum,
        **user_lists,
    }
    return render(request, "forum_edit.html", context)


@login_required
@require_POST
def forum_invite(request, forum, user_id):
    forum_obj = get_object_or_404(Forum, id=forum)
    user = get_object_or_404(User, id=user_id)

    if settings.EJABBERD_ENABLED and forum_obj.xmpp_muc_jid and user.xmpp:
        from . import ejabberd as xmpp

        xmpp.send_invitation(forum_obj.xmpp_muc_jid, user.xmpp)
        xmpp.set_room_affiliation(forum_obj.xmpp_muc_jid, user.xmpp, "member")
    else:
        # Fallback: send email invitation
        if user.email:
            subject = f"Einladung: {forum_obj.thema}"
            message = f"Hallo {user.first_name},\n\nDu wurdest zum Forum \"{forum_obj.thema}\" eingeladen.\n\nBesuche das Forum unter: {request.build_absolute_uri(reverse('forum_view', args=[forum]))}"
            send_mail(subject, message, "webmaster@example.org", [user.email])

    return redirect("forum_edit", forum=forum)


@permission_required("intern.add_forum", raise_exception=True)
def forum_add(request):
    if request.method == "POST":
        form = ForumEditForm(request.POST, request.FILES)
        if form.is_valid():
            forum = form.save(commit=False)
            filer_id = request.POST.get("bild_filer_id")
            if filer_id:
                try:
                    f = File.objects.get(pk=int(filer_id))
                    folder_id = folders.forum()
                    if folder_id:
                        f.folder_id = folder_id
                        f.save()
                    forum.bild = f
                except (File.DoesNotExist, ValueError):
                    pass
            forum.save()
            return redirect("forum_view", forum=forum.id)
    else:
        form = ForumEditForm()
    context = {
        "form": form,
        "seitentitel": "Neues Forum",
    }
    return render(request, "forum_edit.html", context)
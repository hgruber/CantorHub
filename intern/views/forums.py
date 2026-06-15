import logging
from django.utils.timezone import now as timezone_now

from django.contrib.auth.decorators import login_required, permission_required
from django.core.mail import send_mail
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django_tables2 import RequestConfig

from filer.models import File

from intern import ejabberd, folders
from intern.app_settings import get_config, get_config_bool, get_from_email

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
    "forum_delete",
]

logger = logging.getLogger(__name__)

FORUM_SEARCH_LIMIT = 200


def _sync_forum_avatar(forum_obj):
    """Push Forum.bild as MUC room avatar. Best-effort: logs errors, never raises."""
    if not get_config_bool("EJABBERD_ENABLED"):
        return
    if not forum_obj.bild:
        return
    muc_jid = _get_muc_jid(forum_obj)
    if not muc_jid:
        return
    ejabberd.set_room_vcard(muc_jid, forum_obj.bild, name=forum_obj.thema)


def _get_muc_jid(forum_obj):
    """Return the MUC JID for a forum, deriving it from config if not explicitly set."""
    if forum_obj.xmpp_muc_jid:
        return forum_obj.xmpp_muc_jid
    muc_service = get_config("EJABBERD_MUC_SERVICE", "")
    if muc_service:
        return f"forum-{forum_obj.pk}@{muc_service}"
    return None


def _forum_user_lists(forum_obj):
    """Compute XMPP-based user lists and room info. Returns empty dicts when EJABBERD disabled."""
    empty = {
        "invited": [],
        "attending": [],
        "without_invitation": [],
        "without_xmpp": [],
        "strangers": [],
        "room_info": None,
        "muc_jid": None,
    }
    if not get_config_bool("EJABBERD_ENABLED"):
        return empty

    muc_jid = _get_muc_jid(forum_obj)
    if not muc_jid:
        return empty

    active_users = list(User.objects.filter(is_active=True).order_by("last_name", "first_name"))

    room_members = ejabberd.get_room_members(muc_jid)
    member_jids = {jid.lower() for jid, aff in room_members if aff in ("member", "admin", "owner")}

    room_occupants = ejabberd.get_room_occupants(muc_jid)
    occupant_jids = {jid.split("/")[0].lower() for jid, _nick in room_occupants}

    options = ejabberd.get_room_options(muc_jid)
    bot_jid = get_config("EJABBERD_BOT_JID", "").lower()
    owners = [jid for jid, aff in room_members if aff == "owner"]
    is_true = ejabberd.option_is_true
    room_info = {
        "exists": options is not None,
        "persistent": is_true(options, "persistent"),
        "members_only": is_true(options, "members_only"),
        "public": is_true(options, "public"),
        "moderated": is_true(options, "moderated"),
        "anonymous": is_true(options, "anonymous"),
        "allow_user_invites": is_true(options, "allow_user_invites"),
        "lang": (options or {}).get("lang", ""),
        "title": (options or {}).get("title", ""),
        "owners": owners,
        "owner_is_bot": bool(bot_jid) and any(bot_jid == jid.lower() for jid in owners),
        "bot_present": bool(bot_jid) and any(bot_jid in jid.lower() for jid in occupant_jids),
    }

    user_jids = {u.xmpp.lower() for u in active_users if u.xmpp}
    seen_bare = set()
    strangers = []
    for full_jid, nick in room_occupants:
        bare = full_jid.split("/")[0].lower()
        if bare in seen_bare:
            continue
        seen_bare.add(bare)
        if bare in user_jids:
            continue
        if bot_jid and bare == bot_jid:
            continue
        strangers.append({"jid": bare, "nick": nick})

    return {
        "invited": [u for u in active_users if u.xmpp and u.xmpp.lower() in member_jids],
        "attending": [u for u in active_users if u.xmpp and u.xmpp.lower() in occupant_jids],
        "without_invitation": [u for u in active_users if u.xmpp and u.xmpp.lower() not in member_jids],
        "without_xmpp": [u for u in active_users if not u.xmpp],
        "strangers": strangers,
        "room_info": room_info,
        "muc_jid": muc_jid,
    }


@login_required
def forum_list(request):
    q = (request.GET.get("q") or "").strip()
    add = "forum_add" if request.user.has_perm("intern.add_forum") else None

    if len(q) >= 2:
        messages = (
            Mitteilung.objects.filter(mitteilung__icontains=q)
            .select_related("forum", "sender")
            .order_by("-datum")[:FORUM_SEARCH_LIMIT]
        )
        return render(
            request,
            "forum_search.html",
            {
                "seitentitel": f"Forensuche: „{q}“",
                "messages": messages,
                "add": add,
                "show_search": True,
                "search_query": q,
            },
        )

    foren = Forum.objects.extra_data().order_by("-zugriff")
    table = ForumTabelle(foren)
    RequestConfig(request, paginate=False).configure(table)
    return render(
        request,
        "table.html",
        {
            "table": table,
            "seitentitel": "Foren",
            "topbar_icon": '<svg class="topbar-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
            "upload_folder_id": folders.forum(),
            "upload_folder_name": "Forum",
            "add": add,
            "add_form": ForumEditForm() if request.user.has_perm("intern.add_forum") else None,
            "add_form_multipart": True,
            "add_label": "Neues Forum",
            "show_search": True,
            "search_query": "",
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
            "upload_folder_name": "Forum",
            "up": "forum_list",
            "edit": "forum_edit" if request.user.has_perm("intern.change_forum") else None,
            "history": "forum_aenderungen" if request.user.has_perm("intern.change_forum") else None,
            "id": forum,
        },
    )


@login_required
def forum_get(request, forum, last_id=0):
    if last_id == 0:
        last_id = request.GET.get("last_id", 0)
    last_id = int(last_id or 0)
    messages = Mitteilung.objects.filter(forum_id=forum, id__gt=last_id)
    if messages:
        # Keep last_id monotonic so an in-flight poll never lowers it.
        last_id = max(last_id, max(msg.id for msg in messages))
    return render(
        request,
        "_messages.html",
        {"forum": forum, "last_id": last_id, "messages": messages},
    )


FORUM_MORE_BATCH = 20


@login_required
def forum_more(request, forum):
    """Return älterer Nachrichten (20 Stück) als HTML-Snippet mit neuem Sentinel."""
    oldest_id = request.GET.get("oldest_id", 0)
    messages = list(
        Mitteilung.objects.filter(forum_id=forum, id__lt=oldest_id)[:FORUM_MORE_BATCH]
    )
    new_oldest_id = min((msg.id for msg in messages), default=0)
    has_more = (
        len(messages) == FORUM_MORE_BATCH
        and Mitteilung.objects.filter(forum_id=forum, id__lt=new_oldest_id).exists()
    )
    return render(
        request,
        "_forum_more.html",
        {
            "forum": forum,
            "oldest_id": new_oldest_id,
            "messages": messages,
            "has_more": has_more,
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
            datum=timezone_now(),
        )
        # The persistent ejabberd_bot picks this up and relays it to the MUC room
        # over its live session (see CantorBot._relay_messages).
    return forum_get(request, forum, last_id)


@permission_required("intern.change_forum", raise_exception=True)
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
            instance = form.save(commit=False)
            instance._audit_user = request.user
            instance.save()
            form.save_m2m()
            _sync_forum_avatar(instance)
            return redirect("forum_view", forum=forum)
    else:
        form = ForumEditForm(instance=forum_obj)

    user_lists = _forum_user_lists(forum_obj)

    context = {
        "form": form,
        "forum_obj": forum_obj,
        "seitentitel": f"bearbeiten: {forum_obj.thema}",
        "view": "forum_view",
        "id": forum,
        "ejabberd_enabled": get_config_bool("EJABBERD_ENABLED"),
        **user_lists,
    }
    return render(request, "forum_edit.html", context)


@permission_required("intern.change_forum", raise_exception=True)
@require_POST
def forum_invite(request, forum, user_id):
    forum_obj = get_object_or_404(Forum, id=forum)
    user = get_object_or_404(User, id=user_id)

    muc_jid = _get_muc_jid(forum_obj)
    if get_config_bool("EJABBERD_ENABLED") and muc_jid and user.xmpp:
        if not forum_obj.xmpp_muc_jid:
            forum_obj.xmpp_muc_jid = muc_jid
            forum_obj.save(update_fields=["xmpp_muc_jid"])
        ejabberd.set_room_affiliation(muc_jid, user.xmpp, "member")

    return redirect("forum_edit", forum=forum)


@permission_required("intern.delete_forum", raise_exception=True)
@require_POST
def forum_delete(request, forum):
    forum_obj = get_object_or_404(Forum, id=forum)
    if get_config_bool("EJABBERD_ENABLED") and forum_obj.xmpp_muc_jid:
        try:
            ejabberd.destroy_room(forum_obj.xmpp_muc_jid)
        except Exception as exc:
            logger.error("ejabberd: failed to destroy room %s: %s", forum_obj.xmpp_muc_jid, exc)
    forum_obj._audit_user = request.user
    forum_obj.delete()  # cascades: all Mitteilung rows deleted
    return redirect("forum_list")


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
            forum._audit_user = request.user
            forum.save()
            _sync_forum_avatar(forum)
            return redirect("forum_view", forum=forum.id)
    else:
        form = ForumEditForm()
    context = {
        "form": form,
        "seitentitel": "Neues Forum",
    }
    return render(request, "forum_edit.html", context)
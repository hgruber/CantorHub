import logging
from django.utils.timezone import now as timezone_now

from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db.models import Count
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST
from django_tables2 import RequestConfig

from filer.models import File

from intern import ejabberd, folders
from intern.app_settings import get_config, get_from_email, is_ejabberd_configured
from intern.forum_gelesen import (
    hat_aeltere_ungelesene,
    lese_bis_id,
    markiere_gelesen,
    sichere_ausgangspunkt,
    trenner_id,
)

from ..forms import ForumEditForm
from ..models import (
    ChangeLog,
    Forum,
    ForumPermission,
    Mitteilung,
    Reaktion,
    User,
    ab_stichtag,
)
from ..tables import ForumTabelle
from ._auswahl import chip_eintraege
from ._decorators import tabellenzustand

__all__ = [
    "forum_list",
    "forum_view",
    "forum_get",
    "forum_more",
    "forum_send",
    "forum_react",
    "forum_reactions",
    "forum_edit",
    "forum_invite",
    "forum_add",
    "forum_delete",
    "forum_permissions",
]

logger = logging.getLogger(__name__)

FORUM_SEARCH_LIMIT = 200


def _forum_access(user, forum_id):
    """True if the user may read this forum.

    Holders of manage_forum_permissions always have access.
    A deactivated forum (``Forum.aktiv`` False) is closed to everyone else.
    No ForumPermission row for the forum → open to everyone (default).
    Otherwise the user must be in one of the permitted groups.
    """
    if user.has_perm("intern.manage_forum_permissions"):
        return True
    if Forum.objects.filter(pk=forum_id, aktiv=False).exists():
        return False
    perms = ForumPermission.objects.filter(forum_id=forum_id)
    if not perms.exists():
        return True
    gids = user.groups.values_list("id", flat=True)
    return perms.filter(group_id__in=gids).exists()


def _hidden_forum_ids(user):
    """Set of forum IDs the user may NOT read: group restrictions plus
    deactivated forums (both lifted by manage_forum_permissions)."""
    if user.has_perm("intern.manage_forum_permissions"):
        return set()
    inaktiv = set(Forum.objects.filter(aktiv=False).values_list("id", flat=True))
    restricted = set(
        ForumPermission.objects.values_list("forum_id", flat=True).distinct()
    )
    if not restricted:
        return inaktiv
    gids = user.groups.values_list("id", flat=True)
    readable = set(
        ForumPermission.objects.filter(group_id__in=gids)
        .values_list("forum_id", flat=True)
    )
    return (restricted - readable) | inaktiv


def _allowed_reader_jids(forum_obj):
    """Lowercased XMPP JIDs of active users allowed to read this forum.

    Returns None when the forum is unrestricted (everyone allowed)."""
    group_ids = list(
        ForumPermission.objects.filter(forum=forum_obj).values_list(
            "group_id", flat=True
        )
    )
    if not group_ids:
        return None
    users = (
        User.objects.filter(is_active=True, groups__id__in=group_ids)
        .exclude(xmpp=None)
        .exclude(xmpp="")
        .distinct()
    )
    return {u.xmpp.lower() for u in users}


def _sync_forum_avatar(forum_obj):
    """Push Forum.bild as MUC room avatar. Best-effort: logs errors, never raises."""
    if not is_ejabberd_configured():
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
    if not is_ejabberd_configured():
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
@tabellenzustand
def forum_list(request):
    q = (request.GET.get("q") or "").strip()
    add = "forum_add" if request.user.has_perm("intern.add_forum") else None
    hidden = _hidden_forum_ids(request.user)

    if len(q) >= 2:
        messages = (
            Mitteilung.objects.filter(mitteilung__icontains=q)
            .exclude(forum_id__in=hidden)
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

    sichere_ausgangspunkt(request.user)
    foren = (
        Forum.objects.extra_data()
        .mit_ungelesen(request.user)
        .exclude(id__in=hidden)
        .order_by("-zugriff")
    )
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
            "upload_folder_name": folders.FORENBILDER,
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
    if not _forum_access(request.user, forum):
        raise PermissionDenied
    messages = (
        Mitteilung.objects.filter(forum_id=forum)
        .select_related("sender", "sender__avatar")[:25]
    )
    last_id = max((msg.id for msg in messages), default=0)
    oldest_id = min((msg.id for msg in messages), default=0)
    # Read the old marker before raising it: the divider shows what was new on arrival.
    alt_bis_id = lese_bis_id(request.user, forum)
    if alt_bis_id is None:
        # Wer als allererste Forumsaktion ein Forum direkt öffnet, hätte danach
        # genau eine Zeile — und ``sichere_ausgangspunkt`` käme wegen seines
        # ``exists()``-Kurzschlusses für die übrigen Foren nie mehr zum Zug. Nur
        # in diesem Fall, sonst kostete es jeden Forumsaufruf eine Abfrage.
        sichere_ausgangspunkt(request.user)
    trenner_nach = trenner_id(
        [(msg.id, msg.sender_id) for msg in messages],
        alt_bis_id,
        request.user.id,
        # Unterhalb des Fensters (erste 25) noch Ungelesene? Dann lässt sich die Linie
        # nicht wahrheitsgemäß platzieren und bleibt weg — docs/forum.md, „none if it
        # lies further back".
        aeltere_ungelesen=(
            alt_bis_id is not None
            and oldest_id
            and hat_aeltere_ungelesene(request.user, forum, oldest_id, alt_bis_id)
        ),
    )
    markiere_gelesen(request.user, forum, last_id)
    permissions_url = (
        reverse("forum_permissions", args=[forum])
        if request.user.has_perm("intern.manage_forum_permissions")
        else None
    )
    return render(
        request,
        "forum.html",
        {
            "seitentitel": f"Forum: {Forum.objects.get(id=forum).thema}",
            "forum": forum,
            "last_id": last_id,
            "oldest_id": oldest_id,
            "messages": messages,
            "trenner_nach": trenner_nach,
            # Für die Sentinel-Kette von forum_more: ohne Lesestand wird 0 gereicht.
            "alt_bis_id": alt_bis_id or 0,
            "upload_folder_id": folders.forum(),
            "upload_folder_name": folders.FORENBILDER,
            "up": "forum_list",
            "edit": "forum_edit" if request.user.has_perm("intern.change_forum") else None,
            "history": "forum_aenderungen" if request.user.has_perm("intern.change_forum") else None,
            "permissions_url": permissions_url,
            "id": forum,
        },
    )


@login_required
def forum_get(request, forum, last_id=0):
    if not _forum_access(request.user, forum):
        raise PermissionDenied
    if last_id == 0:
        last_id = request.GET.get("last_id", 0)
    last_id = int(last_id or 0)
    messages = Mitteilung.objects.filter(
        forum_id=forum, id__gt=last_id
    ).select_related("sender", "sender__avatar")
    if messages:
        # Keep last_id monotonic so an in-flight poll never lowers it.
        last_id = max(last_id, max(msg.id for msg in messages))
        # What arrives while the forum is open counts as read.
        markiere_gelesen(request.user, forum, last_id)
    # Bewusst ohne ``request``: das Teilstueck braucht nur ``user`` (siehe
    # _message.html), und ``render()`` liesse den Kontextprozessor mitlaufen —
    # alle fuenf Sekunden pro offenem Forum-Tab.
    return HttpResponse(render_to_string(
        "_messages.html",
        {"forum": forum, "last_id": last_id, "messages": messages,
         "user": request.user},
    ))


FORUM_MORE_BATCH = 20


@login_required
def forum_more(request, forum):
    """Return älterer Nachrichten (20 Stück) als HTML-Snippet mit neuem Sentinel."""
    if not _forum_access(request.user, forum):
        raise PermissionDenied
    oldest_id = request.GET.get("oldest_id", 0)
    # Der Lesestand vor dem Seitenaufruf: forum_view hat den Marker längst auf last_id
    # angehoben, der Sentinel-Kette ist der einzige Weg, ihn hierher zu bringen.
    alt_bis_id = int(request.GET.get("bis_id") or 0) or None
    messages = list(
        Mitteilung.objects.filter(forum_id=forum, id__lt=oldest_id)
        .select_related("sender", "sender__avatar")[:FORUM_MORE_BATCH]
    )
    new_oldest_id = min((msg.id for msg in messages), default=0)
    has_more = (
        len(messages) == FORUM_MORE_BATCH
        and Mitteilung.objects.filter(forum_id=forum, id__lt=new_oldest_id).exists()
    )
    trenner_nach = None
    if alt_bis_id is not None:
        trenner_nach = trenner_id(
            [(msg.id, msg.sender_id) for msg in messages],
            alt_bis_id,
            request.user.id,
            # Liegt der älteste Ungelesene noch unterhalb dieses Batches, bleibt die
            # Linie weiter weg — sie würde sonst eine Lüge über noch nicht Geladenes
            # zeichnen. Gleiche Regel wie in forum_view.
            aeltere_ungelesen=(
                new_oldest_id
                and hat_aeltere_ungelesene(request.user, forum, new_oldest_id, alt_bis_id)
            ),
        )
    return render(
        request,
        "_forum_more.html",
        {
            "forum": forum,
            "oldest_id": new_oldest_id,
            "messages": messages,
            "has_more": has_more,
            "bis_id": alt_bis_id or 0,
            "trenner_nach": trenner_nach,
        },
    )


@login_required
@require_POST
def forum_send(request, forum):
    if not _forum_access(request.user, forum):
        raise PermissionDenied
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


def _reactions_payload(forum_id, user, message_ids=None):
    """Aggregate reactions per message for a forum into a JSON-serialisable dict
    ``{message_id: [{emoji, count, mine, who}]}``. ``mine`` flags the requesting
    user's own (web) reaction so the UI can highlight it."""
    qs = Reaktion.objects.filter(
        ab_stichtag(), mitteilung__forum_id=forum_id
    ).select_related("sender")
    if message_ids is not None:
        qs = qs.filter(mitteilung_id__in=message_ids)

    data: dict[str, dict[str, dict]] = {}
    for r in qs:
        bucket = data.setdefault(str(r.mitteilung_id), {})
        entry = bucket.setdefault(
            r.emoji, {"emoji": r.emoji, "count": 0, "mine": False, "who": []}
        )
        entry["count"] += 1
        if r.sender:
            name = f"{r.sender.first_name} {r.sender.last_name}".strip() or r.sender.username
        else:
            name = r.reactor_jid or "Unbekannt"
        entry["who"].append(name)
        if r.sender_id == user.id:
            entry["mine"] = True

    return {mid: list(buckets.values()) for mid, buckets in data.items()}


@login_required
@require_POST
def forum_react(request, forum):
    """Toggle the current user's web reaction on a message and return the updated
    reaction state for that message as JSON."""
    if not _forum_access(request.user, forum):
        raise PermissionDenied

    try:
        message_id = int(request.POST.get("message_id", ""))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("invalid message_id")
    emoji = (request.POST.get("emoji") or "").strip()
    if not emoji or len(emoji) > 64:
        return HttpResponseBadRequest("invalid emoji")

    if not Mitteilung.objects.filter(pk=message_id, forum_id=forum).exists():
        return HttpResponseBadRequest("unknown message")

    existing = Reaktion.objects.filter(
        mitteilung_id=message_id, sender=request.user, emoji=emoji, origin="web"
    )
    if existing.exists():
        existing.delete()
    else:
        Reaktion.objects.create(
            mitteilung_id=message_id,
            sender=request.user,
            emoji=emoji,
            origin="web",
        )
    # The persistent ejabberd_bot relays the new web-reaction union to the MUC.
    Mitteilung.objects.filter(pk=message_id).update(reactions_dirty=True)

    payload = _reactions_payload(forum, request.user, [message_id])
    return JsonResponse({"reactions": payload.get(str(message_id), [])})


@login_required
def forum_reactions(request, forum):
    """Return all reactions for the forum's messages as JSON for the live poll."""
    if not _forum_access(request.user, forum):
        raise PermissionDenied
    return JsonResponse({"reactions": _reactions_payload(forum, request.user)})


@permission_required("intern.change_forum", raise_exception=True)
def forum_edit(request, forum):
    forum_obj = get_object_or_404(Forum, id=forum)

    if request.method == "POST":
        form = ForumEditForm(request.POST, request.FILES, instance=forum_obj)
        if form.is_valid():
            # Move dropzone-uploaded bild to the Forenbilder folder
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
        "ejabberd_enabled": is_ejabberd_configured(),
        **user_lists,
    }
    return render(request, "forum_edit.html", context)


@permission_required("intern.change_forum", raise_exception=True)
@require_POST
def forum_invite(request, forum, user_id):
    forum_obj = get_object_or_404(Forum, id=forum)
    user = get_object_or_404(User, id=user_id)

    # Don't invite a non-reader into a restricted forum — that would contradict
    # the read restriction the moment they joined the linked MUC room.
    if not _forum_access(user, forum):
        return redirect("forum_edit", forum=forum)

    muc_jid = _get_muc_jid(forum_obj)
    if is_ejabberd_configured() and muc_jid and user.xmpp:
        if not forum_obj.xmpp_muc_jid:
            forum_obj.xmpp_muc_jid = muc_jid
            forum_obj.save(update_fields=["xmpp_muc_jid"])
        ejabberd.set_room_affiliation(muc_jid, user.xmpp, "member")

    return redirect("forum_edit", forum=forum)


@permission_required("intern.delete_forum", raise_exception=True)
@require_POST
def forum_delete(request, forum):
    forum_obj = get_object_or_404(Forum, id=forum)
    if is_ejabberd_configured() and forum_obj.xmpp_muc_jid:
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


def _reconcile_forum_muc(forum_obj):
    """Sync MUC affiliations with the forum's read restriction. Best-effort:
    logs errors, never raises. Unrestricted forums are left untouched."""
    if not is_ejabberd_configured():
        return
    muc_jid = _get_muc_jid(forum_obj)
    if not muc_jid:
        return
    allowed = _allowed_reader_jids(forum_obj)
    if allowed is None:
        # Forum is open again — don't strip anyone; the bot re-invites everyone.
        return
    bot_jid = get_config("EJABBERD_BOT_JID", "").lower()
    try:
        members = ejabberd.get_room_members(muc_jid)
    except Exception as exc:
        logger.error("ejabberd: failed to read members of %s: %s", muc_jid, exc)
        return
    current = {jid.lower() for jid, _aff in members}
    # Remove members who may no longer read (keep the bot).
    for jid in current:
        if jid == bot_jid or jid in allowed:
            continue
        try:
            ejabberd.set_room_affiliation(muc_jid, jid, "none")
        except Exception as exc:
            logger.error("ejabberd: failed to remove %s from %s: %s", jid, muc_jid, exc)
    # Ensure permitted readers are members.
    for jid in allowed:
        if jid in current:
            continue
        try:
            ejabberd.set_room_affiliation(muc_jid, jid, "member")
        except Exception as exc:
            logger.error("ejabberd: failed to add %s to %s: %s", jid, muc_jid, exc)


def _audit_forum_permissions(forum_obj, user, old_ids, new_ids, groups):
    """Write a ChangeLog entry under the Forum when its read groups change, so it
    surfaces in forum_aenderungen alongside thema/bild changes. Never raises."""
    old_ids, new_ids = set(old_ids), set(new_ids)
    if old_ids == new_ids:
        return
    names = {g.id: g.name for g in groups}

    def label(ids):
        if not ids:
            return "Alle Mitglieder"
        return ", ".join(sorted(names.get(i, str(i)) for i in ids))

    try:
        ChangeLog.objects.create(
            user=user,
            action=ChangeLog.ACTION_UPDATE,
            model_name="Forum",
            object_id=forum_obj.pk,
            object_repr=str(forum_obj)[:200],
            changes={"berechtigungen": [label(old_ids), label(new_ids)]},
        )
    except Exception:
        logger.exception("audit: failed to log forum permission change for #%s", forum_obj.pk)


@login_required
def forum_permissions(request, forum):
    if not request.user.has_perm("intern.manage_forum_permissions"):
        raise PermissionDenied

    forum_obj = get_object_or_404(Forum, id=forum)

    groups = Group.objects.all().order_by("name")
    existing_group_ids = set(
        ForumPermission.objects.filter(forum=forum_obj).values_list(
            "group_id", flat=True
        )
    )
    read_restricted = bool(existing_group_ids)

    if request.method == "POST":
        read_mode = request.POST.get("read_mode")  # "all" or "restricted"
        valid_ids = {g.id for g in groups}
        read_groups = {int(x) for x in request.POST.getlist("read_groups")} & valid_ids

        ForumPermission.objects.filter(forum=forum_obj).delete()
        new_group_ids = read_groups if read_mode == "restricted" else set()
        for gid in new_group_ids:
            ForumPermission.objects.create(forum=forum_obj, group_id=gid)

        _audit_forum_permissions(
            forum_obj, request.user, existing_group_ids, new_group_ids, groups
        )
        _reconcile_forum_muc(forum_obj)
        return redirect("forum_view", forum=forum)

    group_members = {
        g.id: [
            f"{u.first_name} {u.last_name}".strip() or u.username
            for u in g.user_set.filter(is_active=True).order_by("first_name", "last_name")
        ]
        for g in groups
    }
    return render(request, "forum_zugriff.html", {
        "seitentitel": f"Zugriffskontrolle: {forum_obj.thema}",
        "forum_obj": forum_obj,
        "groups": groups,
        "read_restricted": read_restricted,
        "read_eintraege": chip_eintraege(groups, existing_group_ids),
        "group_members": group_members,
        "up": "forum_list",
        "id": forum,
    })
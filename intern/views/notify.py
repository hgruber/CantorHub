"""
Site-wide notification endpoint — polls recent ChangeLog entries for
Lied, Termin, Forum, Mitteilung, and Artikel changes and returns them
as JSON for the notification bubble system.
"""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from ..models import ChangeLog, Forum, Lied, Mitteilung, Termin

__all__ = ["site_notify", "notify_toggle"]

# Models whose changes produce notification bubbles
_NOTIFY_MODELS = {"Lied", "Termin", "Forum", "Mitteilung", "Artikel", "User"}

# For User, only notify on login/logout — not on every profile edit
_NOTIFY_USER_ACTIONS = {"login", "logout"}

# Map model_name → URL pattern name for detail links
_MODEL_VIEW = {
    "Lied": "titel_view",
    "Termin": "termin_view",
    "Forum": "forum_view",
    "Artikel": "article_view",
    "User": "mitglied_view",
}

# Map model_name → display label
_MODEL_LABEL = {
    "Lied": "Lied",
    "Termin": "Termin",
    "Forum": "Forum",
    "Mitteilung": "Nachricht",
    "Artikel": "Artikel",
    "User": "Mitglied",
}

_ACTION_LABEL = {
    "create": "erstellt",
    "update": "geändert",
    "delete": "gelöscht",
    "login": "eingeloggt",
    "logout": "ausgeloggt",
}


@login_required
def site_notify(request):
    """Return recent ChangeLog entries as JSON for site-wide notification bubbles."""
    since = request.GET.get("since", 0)
    try:
        since = int(since)
    except (ValueError, TypeError):
        since = 0

    # Return the current max id so the client can initialise its baseline
    # even when there are no new entries to report.
    latest_id = ChangeLog.objects.order_by("-id").values_list("id", flat=True).first() or 0

    entries = (
        ChangeLog.objects.filter(id__gt=since, model_name__in=_NOTIFY_MODELS)
        .exclude(user_id=request.user.id)
        .select_related("user")
        .order_by("id")[:30]
    )

    # For User model, only include login/logout actions (not profile edits)
    entries = [e for e in entries
               if e.model_name != "User" or e.action in _NOTIFY_USER_ACTIONS]

    # Don't leak restricted forums: drop Forum/Mitteilung bubbles the user
    # isn't allowed to read.
    from .forums import _hidden_forum_ids
    hidden = _hidden_forum_ids(request.user)
    if hidden:
        msg_forum = dict(
            Mitteilung.objects.filter(
                pk__in=[e.object_id for e in entries if e.model_name == "Mitteilung"]
            ).values_list("pk", "forum_id")
        )
        entries = [
            e for e in entries
            if not (
                (e.model_name == "Forum" and e.object_id in hidden)
                or (e.model_name == "Mitteilung" and msg_forum.get(e.object_id) in hidden)
            )
        ]

    data = []
    for e in entries:
        item = {
            "id": e.id,
            "model": e.model_name,
            "action": e.action,
            "action_label": _ACTION_LABEL.get(e.action, e.action),
            "object_id": e.object_id,
            "object_repr": e.object_repr,
            "model_label": _MODEL_LABEL.get(e.model_name, e.model_name),
            "user": str(e.user) if e.user else "?",
        }

        # Special: for Mitteilung, include forum id and snippet so the
        # bubble can link directly to the forum and show the message text
        if e.model_name == "Mitteilung":
            try:
                msg = Mitteilung.objects.select_related("forum", "sender").get(pk=e.object_id)
                item["forum"] = msg.forum_id
                item["thema"] = msg.forum.thema
                item["snippet"] = (msg.mitteilung or "")[:120]
                if msg.sender and msg.sender.avatar:
                    item["avatar"] = msg.sender.avatar.url
            except Mitteilung.DoesNotExist:
                pass

        # For Forum creates/edits, link to the forum
        if e.model_name == "Forum" and e.action != "delete":
            item["forum"] = e.object_id

        # For User login/logout, include avatar
        if e.model_name == "User" and e.user and e.user.avatar:
            item["avatar"] = e.user.avatar.url

        data.append(item)

    return JsonResponse({"entries": data, "latest_id": latest_id})


@login_required
@require_POST
def notify_toggle(request):
    """Toggle the notify_enabled preference for the current user."""
    request.user.notify_enabled = not request.user.notify_enabled
    # Record the acting user in the audit log; otherwise the ChangeLog entry
    # falls back to "System".
    request.user._audit_user = request.user
    request.user.save(update_fields=["notify_enabled"])
    return JsonResponse({"notify_enabled": request.user.notify_enabled})
"""Unread markers for forums: how far each member has read each forum.

One `ForumGelesen` row per (member, forum) holds the id of the newest message the member
has seen. The first half of this module is pure logic and tested with `SimpleTestCase`;
the second half is the thin DB wrapper the views and the context processor call.

A member without any row yet (feature just deployed, fresh database, new member) gets a
starting point at the current state of every forum, so years of old messages don't show
up as new. A forum that appears later without a row — newly created, or newly readable
after a permission change — counts from 0: its messages really are new to the member.
"""

from django.db.models import F, Max, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce


# --- Pure logic -------------------------------------------------------------------------

def ist_ungelesen(nachricht_id, sender_id, bis_id, user_id):
    """A message is unread when it lies above the read marker and someone else wrote it."""
    return nachricht_id > bis_id and sender_id != user_id


def trenner_id(nachrichten, alt_bis_id, user_id, aeltere_ungelesen=False):
    """Id of the oldest unread message among `nachrichten` (`(id, sender_id)` pairs), or None.

    The divider „Neu seit Deinem letzten Besuch" is rendered below that message. Without a
    previous marker (`alt_bis_id is None`) there is no last visit and therefore no divider.
    The same goes for `aeltere_ungelesen`: when unread messages lie below the loaded window
    (the first 25), the divider could not be placed truthfully there — pages loaded by
    `forum_more` would show as read below it.
    """
    if alt_bis_id is None or aeltere_ungelesen:
        return None
    ungelesen = [
        nid for nid, sender_id in nachrichten
        if ist_ungelesen(nid, sender_id, alt_bis_id, user_id)
    ]
    return min(ungelesen, default=None)


# --- DB wrapper -------------------------------------------------------------------------

def hat_aeltere_ungelesene(user, forum_id, aeltere_grenze, alt_bis_id):
    """True when an unread foreign message lies below the loaded window (first 25).

    Mirrors `ist_ungelesen`'s sender rule: `exclude(sender=user)` would also drop rows with
    `sender=None` (unmapped JIDs count as foreign), so the Q combination is explicit —
    same as `ForumQuerySet.mit_ungelesen`.
    """
    from .models import Mitteilung

    return (
        Mitteilung.objects.filter(
            forum_id=forum_id, id__lt=aeltere_grenze, id__gt=alt_bis_id
        )
        .filter(Q(sender__isnull=True) | ~Q(sender=user))
        .exists()
    )


def lese_bis_id(user, forum_id):
    """The member's read marker for a forum, or None if there is none yet."""
    from .models import ForumGelesen

    return (
        ForumGelesen.objects.filter(user=user, forum_id=forum_id)
        .values_list("bis_id", flat=True)
        .first()
    )


def markiere_gelesen(user, forum_id, bis_id):
    """Raise the read marker to `bis_id`. Never lowers it — an in-flight poll carrying an
    older `last_id` must not undo a later visit."""
    from .models import ForumGelesen

    bis_id = int(bis_id or 0)
    if ForumGelesen.objects.filter(
        user=user, forum_id=forum_id, bis_id__lt=bis_id
    ).update(bis_id=bis_id):
        return
    ForumGelesen.objects.get_or_create(
        user=user, forum_id=forum_id, defaults={"bis_id": bis_id}
    )


def sichere_ausgangspunkt(user):
    """Create the starting point for a member who has no read marker at all yet."""
    from .models import Forum, ForumGelesen

    if ForumGelesen.objects.filter(user=user).exists():
        return
    stand = Forum.objects.annotate(bis=Max("mitteilung__id")).values_list("id", "bis")
    ForumGelesen.objects.bulk_create(
        [ForumGelesen(user=user, forum_id=fid, bis_id=bis or 0) for fid, bis in stand],
        ignore_conflicts=True,
    )


def hat_ungelesene(user):
    """True if any forum the member may read holds a message they haven't read."""
    from .models import ForumGelesen, Mitteilung
    from .views.forums import _hidden_forum_ids

    sichere_ausgangspunkt(user)
    bis_id = ForumGelesen.objects.filter(
        forum=OuterRef("forum_id"), user=user
    ).values("bis_id")[:1]
    return (
        Mitteilung.objects.alias(_gelesen_bis=Coalesce(Subquery(bis_id), Value(0)))
        .filter(id__gt=F("_gelesen_bis"))
        .filter(Q(sender__isnull=True) | ~Q(sender=user))
        .exclude(forum_id__in=_hidden_forum_ids(user))
        .exists()
    )

"""Per-folder access control built on top of the FolderPermission model.

Three axes — read, write, delete — each decided on its own. An axis is *ruled* on
a folder when at least one of its FolderPermission rows carries that axis's flag;
the rule then admits exactly the groups whose rows carry it.

Inheritance is dynamic and per axis: a folder without a rule on an axis takes the
rule of its nearest ancestor that has one. Without any, the default applies —
read and write open, delete closed. An own rule replaces the inherited one, it may
also widen it. Read is additionally bounded by the chain: a folder is visible only
if every read rule on the way to the root admits the user.

Write and delete require read. Delete is granted by the global
`intern.delete_folder` permission or by a delete rule naming one of the user's
groups. The root (folder None) is open for read and write; delete there needs the
global permission. Superusers may everything, anonymous users nothing.

`rechte()` and `sichtbare_ordner()` hold the rule without DB access; the
functions below them load the data. See „Folder permissions" in docs/files.md.
"""

from filer.models import Folder

from .anfragespeicher import gemerkt
from .models import FolderPermission

_LESEN, _SCHREIBEN, _LOESCHEN = 1, 2, 3   # positions of the flags in a rule row


def _zugelassen(regeln, achse):
    """The group ids an axis admits on one folder, or None if it has no rule there."""
    if not any(r[achse] for r in regeln):
        return None
    return {r[0] for r in regeln if r[achse]}


def _naechste_regel(kette, achse):
    """The rule of the nearest folder in `kette` that rules `achse`, or None."""
    for regeln in kette:
        gruppen = _zugelassen(regeln, achse)
        if gruppen is not None:
            return gruppen
    return None


def rechte(kette, gruppen, *, global_loeschen=False):
    """Return (lesen, schreiben, loeschen) for a member of `gruppen`.

    `kette` lists the rule rows from the folder up to the top level, one list of
    `(group_id, can_read, can_write, can_delete)` per folder; `[]` is the root."""
    gruppen = set(gruppen)
    lesen = all(
        (zugelassen := _zugelassen(regeln, _LESEN)) is None or gruppen & zugelassen
        for regeln in kette
    )
    if not lesen:
        return False, False, False
    schreiben = _naechste_regel(kette, _SCHREIBEN)
    loeschen = _naechste_regel(kette, _LOESCHEN)
    return (
        True,
        schreiben is None or bool(gruppen & schreiben),
        global_loeschen or (loeschen is not None and bool(gruppen & loeschen)),
    )


def _kette(folder_id, eltern, regeln):
    """The rule rows from `folder_id` up to the top level (see `rechte()`)."""
    kette = []
    gesehen = set()
    while folder_id is not None and folder_id not in gesehen:
        gesehen.add(folder_id)
        kette.append(regeln.get(folder_id, []))
        folder_id = eltern.get(folder_id)
    return kette


def sichtbare_ordner(eltern, regeln, gruppen):
    """The ids among `eltern` (id → parent id) a member of `gruppen` can read.

    `regeln` maps a folder id to its rule rows; folders without rows may be missing."""
    return {
        folder_id
        for folder_id in eltern
        if rechte(_kette(folder_id, eltern, regeln), gruppen)[0]
    }


def _ordnerdaten():
    """(eltern, regeln) for all folders — once per request, see ``anfragespeicher``.

    A changed folder or permission empties the store (``signals.py``)."""
    def laden():
        eltern = dict(Folder.objects.values_list("id", "parent_id"))
        regeln = {}
        for zeile in FolderPermission.objects.values_list(
            "folder_id", "group_id", "can_read", "can_write", "can_delete"
        ):
            regeln.setdefault(zeile[0], []).append(zeile[1:])
        return eltern, regeln
    return gemerkt(("ordnerrechte",), laden)


def _gruppen(user):
    return gemerkt(
        ("gruppen", user.pk), lambda: set(user.groups.values_list("id", flat=True))
    )


def folder_access(user, folder):
    """Return (can_read, can_write, can_delete) for `user` on `folder`.

    Includes inheritance and the ancestors' read rules, so `can_read` is the
    visibility of the folder."""
    if user is None or not user.is_authenticated:
        return False, False, False
    if user.is_superuser:
        return True, True, True
    eltern, regeln = _ordnerdaten()
    kette = _kette(folder.pk if folder is not None else None, eltern, regeln)
    return rechte(
        kette, _gruppen(user), global_loeschen=user.has_perm("intern.delete_folder")
    )


def visible_folder_ids(user):
    """Return the set of folder ids that `user` can browse.

    Das Ergebnis wird je Anfrage einmal ermittelt (``anfragespeicher``): die
    Ordneransicht fragt dreimal danach. Eine geänderte Berechtigung leert den
    Speicher (siehe ``signals.py``)."""
    if user is None or not user.is_authenticated:
        return set()
    return gemerkt(("sichtbare_ordner", user.pk), lambda: _visible_folder_ids(user))


def _visible_folder_ids(user):
    eltern, regeln = _ordnerdaten()
    if user.is_superuser:
        return set(eltern)
    return sichtbare_ordner(eltern, regeln, _gruppen(user))


def is_folder_visible(user, folder):
    """True if `user` can browse `folder` (own read rule + all ancestors')."""
    if folder is None:
        return True   # root
    return folder_access(user, folder)[0]

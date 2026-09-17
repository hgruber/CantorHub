"""Per-folder access control built on top of the FolderPermission model.

A folder with no FolderPermission rows is open for read and write, but NOT for delete.
A folder with rows is restricted: only matching groups have the listed flags.

Delete access requires either the global `intern.delete_folder` permission OR a
FolderPermission row with can_delete=True for one of the user's groups.

A folder is *visible* (browsable) only if the user has can_read on it AND on every
ancestor up to the root. Folders without read access vanish entirely from the tree.
"""

from filer.models import Folder

from .anfragespeicher import gemerkt
from .models import FolderPermission


def folder_access(user, folder):
    """Return (can_read, can_write, can_delete) for `user` on `folder`.

    Considers only this folder's own FolderPermission rows — not ancestors.
    Use `is_folder_visible()` for the parent-chain visibility check."""
    if user is None or not user.is_authenticated:
        return False, False, False
    if user.is_superuser:
        return True, True, True
    if folder is None:
        return True, True, True   # root: open
    perms = list(FolderPermission.objects.filter(folder=folder))
    if not perms:
        return True, True, False  # no rows: open for read/write, closed for delete
    group_ids = set(user.groups.values_list("id", flat=True))
    matches = [p for p in perms if p.group_id in group_ids]
    return (
        any(p.can_read   for p in matches),
        any(p.can_write  for p in matches),
        any(p.can_delete for p in matches),
    )


def visible_folder_ids(user):
    """Return the set of folder ids that `user` can browse.

    A folder is included only if can_read holds on it AND on every ancestor.

    Das Ergebnis wird je Anfrage einmal ermittelt (``anfragespeicher``): die
    Ordneransicht fragt dreimal danach, und die drei Abfragen samt Aufstieg durch
    den Baum wachsen mit der Zahl der Ordner. Eine geänderte Berechtigung leert
    den Speicher (siehe ``signals.py``)."""
    if user is None or not user.is_authenticated:
        return set()
    return gemerkt(("sichtbare_ordner", user.pk), lambda: _visible_folder_ids(user))


def _visible_folder_ids(user):
    all_folders = dict(Folder.objects.values_list("id", "parent_id"))
    if user.is_superuser:
        return set(all_folders.keys())

    restricted_ids = set(
        FolderPermission.objects.values_list("folder_id", flat=True).distinct()
    )
    group_ids = list(user.groups.values_list("id", flat=True))
    user_readable_restricted = set(
        FolderPermission.objects.filter(
            group_id__in=group_ids, can_read=True
        ).values_list("folder_id", flat=True).distinct()
    )

    # Direct can_read: open folders (no rows) + restricted folders where user has can_read
    direct_readable = (set(all_folders.keys()) - restricted_ids) | user_readable_restricted

    # Apply ancestor check: a folder is visible only if all ancestors are direct_readable.
    visible = set()
    for folder_id in direct_readable:
        cur = folder_id
        seen = set()
        ok = True
        while cur is not None:
            if cur in seen:
                break  # cycle guard
            seen.add(cur)
            if cur not in direct_readable:
                ok = False
                break
            cur = all_folders.get(cur)
        if ok:
            visible.add(folder_id)
    return visible


def is_folder_visible(user, folder):
    """True if `user` can browse `folder` (own can_read + all ancestors can_read)."""
    if folder is None:
        return True   # root
    if user is None or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    cur = folder
    seen = set()
    while cur is not None:
        if cur.pk in seen:
            break
        seen.add(cur.pk)
        cr, _, _ = folder_access(user, cur)
        if not cr:
            return False
        cur = cur.parent
    return True

"""Write protection for profile pictures.

The `Profilbilder` folder carries no FolderPermission rows, so by the rule in
`folder_access.py` every logged-in member has write access to it — which would let
anyone overwrite, rename or restore an old revision of someone else's profile
picture. Folder permissions cannot fix this: restricting the folder would also block
the self-service upload in `mitglied_edit`, which goes through `upload()` and is
checked against `folder_access()`.

Hence this second axis: a file that *is* a member's avatar may only be changed by that
member, or by a holder of `intern.change_user` (the same permission `mitglied_edit`
already requires for editing someone else's profile).

Every write path on files has to consult `darf_avatar_aendern()` — see the call sites
listed in docs/files.md under "Avatars are write-protected against other members".
"""

from . import folders
from .models import User


def avatar_mitglied(f):
    """The member whose profile picture `f` is, or None.

    Ownership is the `User.avatar` FK, not the `<id>.jpg` naming convention — the
    name is merely what the upload path happens to produce. The lookup spans all
    linked rows: a file linked into a second folder is a separate `File` row with
    its own PK but shares the blob and the version chain, so acting on the sibling
    would swap the avatar just the same.
    """
    from .views.files import verknuepfte_dateien

    pks = list(verknuepfte_dateien(f).values_list("pk", flat=True))
    if not pks:
        return None
    return User.objects.filter(avatar_id__in=pks).first()


def darf_avatar_aendern(user, f):
    """False when `f` is another member's profile picture.

    True for everything that is not an avatar at all — normal files keep their
    unchanged behaviour and are governed by the folder permissions alone.
    """
    if user is None or not user.is_authenticated:
        return False
    if user.is_superuser or user.has_perm("intern.change_user"):
        return True

    mitglied = avatar_mitglied(f)
    if mitglied is not None:
        return mitglied.pk == user.pk

    # No owner to be found, but the file sits in Profilbilder: a leftover `<id>.jpg`
    # of a member who has no avatar set any more, version history included.
    # Only the membership administration touches those.
    from .views.files import verknuepfte_dateien

    avatare_id = folders.avatare()
    if avatare_id is not None:
        if verknuepfte_dateien(f).filter(folder_id=avatare_id).exists():
            return False
    return True

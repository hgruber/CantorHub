"""
Well-known folder registry.

The folders the portal files into on its own sit under ``Backstage`` — most
members never need to browse them. Only ``Mitglieder-Verwaltung`` stays at the
root. See „Standard folders" in docs/files.md.

Looks up folders by their path from the root on first use, then caches the
result in-process. No dependency on auto-increment IDs — only folder names
matter.

Usage:
    from intern import folders
    folder_id = folders.artikel()   # returns int or None
    folders.invalidate()            # clear cache (e.g. after folder rename)
"""

from django.db.utils import OperationalError

BACKSTAGE = "Backstage"
MITGLIEDER_VERWALTUNG = "Mitglieder-Verwaltung"
EINGANG = "Eingang"
FORENBILDER = "Forenbilder"
PROFILBILDER = "Profilbilder"
REPERTOIRE = "Repertoire"
HOERBEISPIELE = "Hörbeispiele"
NOTENBLAETTER = "Notenblätter"
NOTENSATZ = "Notensatz-Dateien"
PROBENMITSCHNITTE = "Probenmitschnitte"
TERMIN_ANHAENGE = "Termin-Anhänge"
WIKI_ANHAENGE = "Wiki-Anhänge"

# Logical name -> path from the root. Parents come before their children, so
# creating the folders in this order always finds the parent already there.
PFADE: dict[str, tuple[str, ...]] = {
    "backstage":             (BACKSTAGE,),
    "mitglieder_verwaltung": (MITGLIEDER_VERWALTUNG,),
    "unsortiert":            (BACKSTAGE, EINGANG),
    "forum":                 (BACKSTAGE, FORENBILDER),
    "avatare":               (BACKSTAGE, PROFILBILDER),
    "artikel":               (BACKSTAGE, WIKI_ANHAENGE),
    "termine":               (BACKSTAGE, TERMIN_ANHAENGE),
    "musik":                 (BACKSTAGE, REPERTOIRE),
    "repertoire":            (BACKSTAGE, REPERTOIRE, HOERBEISPIELE),
    "pdf":                   (BACKSTAGE, REPERTOIRE, NOTENBLAETTER),
    "notensatz":             (BACKSTAGE, REPERTOIRE, NOTENSATZ),
    "andere":                (BACKSTAGE, REPERTOIRE, PROBENMITSCHNITTE),
}

_cache: dict[str, int] = {}


def _get(*pfad: str) -> int | None:
    key = "/".join(pfad)
    if key in _cache:
        return _cache[key]
    try:
        from filer.models import Folder

        parent_id = None
        for name in pfad:
            folder = Folder.objects.filter(name=name, parent_id=parent_id).first()
            if folder is None:
                return None
            parent_id = folder.pk
    except OperationalError:
        return None  # DB not yet initialised (e.g. during migrate)
    _cache[key] = parent_id
    return parent_id


def backstage()             -> int | None: return _get(*PFADE["backstage"])
def mitglieder_verwaltung() -> int | None: return _get(*PFADE["mitglieder_verwaltung"])
def avatare()               -> int | None: return _get(*PFADE["avatare"])
def unsortiert()            -> int | None: return _get(*PFADE["unsortiert"])
def forum()                 -> int | None: return _get(*PFADE["forum"])
def artikel()               -> int | None: return _get(*PFADE["artikel"])
def musik()                 -> int | None: return _get(*PFADE["musik"])
def termine()               -> int | None: return _get(*PFADE["termine"])
def repertoire()            -> int | None: return _get(*PFADE["repertoire"])
def pdf()                   -> int | None: return _get(*PFADE["pdf"])
def notensatz()             -> int | None: return _get(*PFADE["notensatz"])
def andere()                -> int | None: return _get(*PFADE["andere"])


def invalidate() -> None:
    """Clear the cache — call after creating or renaming a well-known folder."""
    _cache.clear()

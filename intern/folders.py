"""
Well-known folder registry.

Looks up folders by their logical name on first use, then caches the result
in-process. No dependency on auto-increment IDs — only folder names matter.

Usage:
    from intern import folders
    folder_id = folders.artikel()   # returns int or None
    folders.invalidate()            # clear cache (e.g. after folder rename)
"""

from django.db.utils import OperationalError

_cache: dict[str, int] = {}


def _get(name: str, parent_name: str | None = None) -> int | None:
    key = f"{parent_name}/{name}" if parent_name else name
    if key in _cache:
        return _cache[key]
    try:
        from filer.models import Folder

        qs = Folder.objects.filter(name=name)
        if parent_name:
            qs = qs.filter(parent__name=parent_name)
        else:
            qs = qs.filter(parent=None)
        folder = qs.first()
        if folder:
            _cache[key] = folder.pk
            return folder.pk
    except OperationalError:
        pass  # DB not yet initialised (e.g. during migrate)
    return None


def verwaltung() -> int | None: return _get("Verwaltung")
def avatare()    -> int | None: return _get("Avatare")
def unsortiert() -> int | None: return _get("Unsortiert")
def forum()      -> int | None: return _get("Forum")
def artikel()    -> int | None: return _get("Artikel")
def musik()      -> int | None: return _get("Musik")
def termine()    -> int | None: return _get("Termine")
def extern()     -> int | None: return _get("Extern")
def repertoire() -> int | None: return _get("Repertoire", parent_name="Musik")
def pdf()        -> int | None: return _get("PDF",        parent_name="Musik")
def notensatz()  -> int | None: return _get("Notensatz",  parent_name="Musik")


def invalidate() -> None:
    """Clear the cache — call after creating or renaming a well-known folder."""
    _cache.clear()

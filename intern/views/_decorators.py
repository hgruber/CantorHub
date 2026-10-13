"""Gemeinsame View-Decorators."""

import hashlib
from functools import wraps
from urllib.parse import quote, unquote, urlsplit

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect, QueryDict
from django.shortcuts import redirect

from ._pagination import ist_nachladen

# Wie lange eine Liste sich Sortierung und Filter merkt.
_ZUSTAND_MAX_AGE = 365 * 24 * 60 * 60


def perm_or_home(perm, superuser_ok=True):
    """Zutritt nur mit ``perm`` (oder als Superuser); sonst zurück auf „Aktuell".

    ``perm`` darf auch ein Tupel sein — dann genügt eines der Rechte.

    Bewusst nicht ``permission_required``: das antwortet je nach Aufruf mit 403
    oder schickt auf die Login-Seite. Die Verwaltungsseiten dahinter sollen
    stattdessen wortlos auf die Startseite zurückfallen — wer das Recht nicht
    hat, sieht den Menüpunkt gar nicht erst, ein 403 wäre also nur verwirrend.

    Enthält ``login_required``, denn ohne Anmeldung gibt es keine Rechte zu
    prüfen; die Views brauchen es nicht zusätzlich.
    """

    rechte = (perm,) if isinstance(perm, str) else tuple(perm)

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            erlaubt = any(request.user.has_perm(p) for p in rechte) or (
                superuser_ok and request.user.is_superuser
            )
            if not erlaubt:
                return redirect("article_view", name="Aktuell")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def zustand_cookie(pfad):
    """Name des Cookies, in dem sich die Liste unter ``pfad`` ihren Zustand merkt.

    Ein fester Name ginge nicht: ``Path`` matcht als Präfix, der Browser
    schickte dann mehrere gleichnamige Cookies und Django nähme irgendeins.
    Den Pfad selbst verbietet die Cookie-Syntax (``/``), daher der Hash.
    """
    return "liste_" + hashlib.sha256(pfad.encode()).hexdigest()[:16]


# Parameter, die nur diesen einen Aufruf betreffen und nie gemerkt werden:
# `offset` (Nachladen) und `datei` (Sprung zu einer Datei im Ordner).
_FLUECHTIG = ("offset", "datei")


def _ohne_offset(query):
    query = query.copy()
    for name in _FLUECHTIG:
        query.pop(name, None)
    return query


def tabellenzustand(view):
    """Eine Liste merkt sich pro Gerät ihre letzte Sortierung und ihre Filter.

    Wer die Liste ohne Parameter aufruft — meist über das Menü —, wird auf den
    gemerkten Zustand umgeleitet, *bevor* die View rendert. Früher erledigte das
    ein Skript am Seitenende: Der Server baute erst die ungefilterte Liste, dann
    lud der Browser die gefilterte nach, und die Liste sprang.

    Kommt der Aufruf ohne Parameter von derselben Liste („Zurücksetzen", letzter
    Filter-Chip entfernt, Menüklick auf der Liste selbst), wird der Zustand
    vergessen. Nachladen per Infinite Scroll und POST (Spaltenauswahl) laufen
    unverändert durch; ``offset`` und ``datei`` werden nie gemerkt.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.method != "GET" or ist_nachladen(request):
            return view(request, *args, **kwargs)

        pfad = request.path
        cookie = zustand_cookie(pfad)
        query = _ohne_offset(request.GET)

        if query:
            response = view(request, *args, **kwargs)
            if response.status_code == 200:
                response.set_cookie(
                    cookie, quote(query.urlencode(), safe=""),
                    max_age=_ZUSTAND_MAX_AGE, path=pfad, samesite="Lax",
                    httponly=True, secure=request.is_secure(),
                )
            return response

        if urlsplit(request.META.get("HTTP_REFERER", "")).path == pfad:
            response = view(request, *args, **kwargs)
            if cookie in request.COOKIES:
                response.delete_cookie(cookie, path=pfad, samesite="Lax")
            return response

        gemerkt = _ohne_offset(QueryDict(unquote(request.COOKIES.get(cookie, ""))))
        if gemerkt:
            # Ein Sprung zur Datei überlebt die Umleitung auf den gemerkten Zustand.
            if request.GET.get("datei"):
                gemerkt = gemerkt.copy()
                gemerkt["datei"] = request.GET["datei"]
            # Neu codiert statt den Cookie-Wert durchzureichen; das Ziel bleibt
            # immer dieselbe Liste.
            return HttpResponseRedirect(pfad + "?" + gemerkt.urlencode())
        return view(request, *args, **kwargs)

    return wrapper

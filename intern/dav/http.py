"""Antwortbausteine, die jede DAV-View braucht.

Reine HTTP- und XML-Formsachen, keine Fachlichkeit: was in einem 207 steht,
entscheidet die View des jeweiligen Diensts.
"""

import logging
from urllib.parse import unquote

from django.http import Http404, HttpResponse, HttpResponseNotAllowed

from ..app_settings import get_base_url
from .auth import ALLOW_HEADER, dav_kopfzeilen
from .xml import NS_DAV as D, element, multistatus

logger = logging.getLogger(__name__)

__all__ = [
    "multistatus_antwort", "options", "nicht_erlaubt", "aufteilen",
    "privilegien", "collection", "href", "supported_report", "tiefe",
    "schlechte_anfrage", "basis", "ressourcen_id", "pruefe_eigentuemer",
]

GELESEN = ("OPTIONS", "GET", "HEAD", "PROPFIND", "REPORT")


def multistatus_antwort(eintraege):
    """207-Antwort.

    ``text/xml``, nicht ``application/xml``: das senden sabre/dav und Radicale,
    und ältere iOS-Fassungen sind hier eigen.
    """
    return HttpResponse(
        multistatus(eintraege),
        status=207,
        content_type="text/xml; charset=utf-8",
    )


def options():
    r = HttpResponse(status=200)
    r["Allow"] = ALLOW_HEADER
    r["Content-Length"] = "0"
    return r


def nicht_erlaubt():
    # Die DAV-Kopfzeilen setzt der Decorator; hier zählt nur, dass Allow
    # ausdrücklich keine schreibende Methode nennt.
    r = HttpResponseNotAllowed(GELESEN)
    r["Allow"] = ALLOW_HEADER
    return r


def aufteilen(angefragt, verfuegbar):
    """Teilt die angefragten Properties in gefunden und fehlend.

    ``angefragt is None`` heisst „alles, was diese Ressource hat". Sonst wird
    jede unbekannte Property ausdrücklich als 404 gemeldet — sie einfach
    wegzulassen ist der häufigste Fehler selbstgebauter Server.
    """
    if angefragt is None:
        return dict(verfuegbar), []
    gefunden, fehlend = {}, []
    for name in angefragt:
        if name in verfuegbar:
            gefunden[name] = verfuegbar[name]
        else:
            fehlend.append(name)
    return gefunden, fehlend


def privilegien():
    """``current-user-privilege-set`` mit ausschliesslich ``<D:read/>``.

    Daran erkennt iOS „schreibgeschützt" und versucht gar nicht erst zu
    speichern. Fehlt es, zeigt die Kontakte-App beim Öffnen einer Karte
    Speicherfehler — die Kalender-App beim Öffnen eines Termins ebenso.
    """
    return [element(D, "privilege", kinder=[element(D, "read")])]


def collection(*extra):
    """``resourcetype`` einer Sammlung, optional mit Zusatzelementen."""
    kinder = [element(D, "collection")]
    kinder.extend(extra)
    return kinder


def href(pfad):
    """Property-Wert, der aus genau einem ``<D:href>`` besteht."""
    return [element(D, "href", pfad)]


def supported_report(ns, name):
    """Ein Eintrag für ``<D:supported-report-set>``."""
    return element(D, "supported-report",
                   kinder=[element(D, "report", kinder=[element(ns, name)])])


def tiefe(request):
    """``Depth``-Kopf; fehlt er, gilt 0. ``infinity`` behandeln wir wie 1."""
    roh = (request.META.get("HTTP_DEPTH") or "0").strip().lower()
    if roh == "infinity":
        return 1
    return 1 if roh == "1" else 0


def schlechte_anfrage(grund, dienst):
    logger.info("%s: Anfrage abgewiesen (%s)", dienst.name, grund)
    return dav_kopfzeilen(
        HttpResponse("Bad Request", status=400,
                     content_type="text/plain; charset=utf-8"),
        dienst,
    )


def basis(request):
    """Basis-URL für die ``URL:``-Zeilen in den ausgelieferten Daten."""
    return get_base_url() or f"{request.scheme}://{request.get_host()}"


def ressourcen_id(roh_href, endung):
    """``…/12.vcf`` → ``12``; ``None``, wenn es keine unserer Ressourcen ist.

    Der Client schickt die hrefs zurück, die er von uns bekommen hat; ``unquote``
    sorgt dafür, dass eine prozentkodierte Fassung genauso trifft.
    """
    name = unquote(roh_href).rstrip("/").rsplit("/", 1)[-1]
    if not name.endswith(endung):
        return None
    stamm = name[: -len(endung)]
    return int(stamm) if stamm.isdigit() else None


def pruefe_eigentuemer(request, pk):
    """Stellt sicher, dass der Pfad zum angemeldeten Mitglied gehört.

    Http404 statt 403, wie bei ``views/media.py``: eine fremde ID soll sich
    nicht dadurch bestätigen lassen, dass sie einen anderen Fehler erzeugt.
    """
    if request.dav_user.pk != pk:
        raise Http404
    return request.dav_user

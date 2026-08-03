"""Die CardDAV-Endpunkte.

Alle Views sind Funktionen, keine Klassen: das URL-Auflösen ist von der Methode
unabhängig und ``request.method`` nur ein String, also funktionieren PROPFIND und
REPORT hier ohne Zutun — eine ``View``-Klasse bräuchte erweiterte
``http_method_names`` plus kleingeschriebene Handler.

Alle Views sind ``csrf_exempt``. CardDAV-Clients senden weder Cookie noch Origin
oder Referer; die Prüfung würde jedes PROPFIND mit 403 beantworten. Die
Autorisierung leistet vollständig HTTP-Basic in :mod:`~intern.carddav.auth`.
"""

import logging
from urllib.parse import unquote

from django.http import (
    Http404, HttpResponse, HttpResponseNotAllowed, HttpResponsePermanentRedirect,
)
from django.views.decorators.csrf import csrf_exempt

from ..app_settings import get_base_url
from . import dav, daten
from .auth import ALLOW_HEADER, carddav_basic_auth, dav_kopfzeilen
from .dav import NS_CARDDAV as C, NS_CS as CS, NS_DAV as D, element, qn

logger = logging.getLogger(__name__)

__all__ = [
    "well_known", "dav_root", "principal", "home_set", "adressbuch", "kontakt",
]

_GELESEN = ("OPTIONS", "GET", "HEAD", "PROPFIND", "REPORT")


# --------------------------------------------------------------------------
# Pfade
# --------------------------------------------------------------------------

def _p_principal(pk):
    return f"/carddav/principal/{pk}/"


def _p_home(pk):
    return f"/carddav/adressbuch/{pk}/"


def _p_buch(pk):
    return f"/carddav/adressbuch/{pk}/mitglieder/"


def _p_karte(pk, mid):
    return f"/carddav/adressbuch/{pk}/mitglieder/{mid}.vcf"


# --------------------------------------------------------------------------
# Antworten
# --------------------------------------------------------------------------

def _multistatus(eintraege):
    """207-Antwort.

    ``text/xml``, nicht ``application/xml``: das senden sabre/dav und Radicale,
    und ältere iOS-Fassungen sind hier eigen.
    """
    return HttpResponse(
        dav.multistatus(eintraege),
        status=207,
        content_type="text/xml; charset=utf-8",
    )


def _options():
    r = HttpResponse(status=200)
    r["Allow"] = ALLOW_HEADER
    r["Content-Length"] = "0"
    return r


def _nicht_erlaubt():
    # Die DAV-Kopfzeilen setzt der Decorator; hier zählt nur, dass Allow
    # ausdrücklich keine schreibende Methode nennt.
    r = HttpResponseNotAllowed(_GELESEN)
    r["Allow"] = ALLOW_HEADER
    return r


def _aufteilen(angefragt, verfuegbar):
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


def _privilegien():
    """``current-user-privilege-set`` mit ausschliesslich ``<D:read/>``.

    Daran erkennt iOS „schreibgeschützt" und versucht gar nicht erst zu
    speichern. Fehlt es, zeigt die Kontakte-App beim Öffnen einer Karte
    Speicherfehler.
    """
    return [element(D, "privilege", kinder=[element(D, "read")])]


def _user_principal(pk):
    return [element(D, "href", _p_principal(pk))]


def _home_set(pk):
    return [element(D, "href", _p_home(pk))]


def _collection(*extra):
    kinder = [element(D, "collection")]
    kinder.extend(extra)
    return kinder


def _reports():
    """``supported-report-set``. ``sync-collection`` steht bewusst nicht drin."""
    def r(ns, name):
        return element(D, "supported-report",
                       kinder=[element(D, "report",
                                       kinder=[element(ns, name)])])
    return [r(C, "addressbook-multiget"), r(C, "addressbook-query")]


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------

@csrf_exempt
def well_known(request):
    """RFC 6764: ``/.well-known/carddav`` → das Dienstwurzelverzeichnis.

    301 und nicht 302 — so sieht es der RFC vor, und beide Zielclients folgen
    ihm. Ohne Anmeldung, weil die Weiterleitung nichts verrät: iOS fragt beim
    Einrichten nur nach dem Hostnamen und findet den Dienst allein hierüber.
    """
    return HttpResponsePermanentRedirect("/carddav/")


def _eigenes_buch(request, pk):
    """Stellt sicher, dass der Pfad zum angemeldeten Mitglied gehört.

    Http404 statt 403, wie bei ``views/media.py``: eine fremde ID soll sich
    nicht dadurch bestätigen lassen, dass sie einen anderen Fehler erzeugt.
    """
    if request.carddav_user.pk != pk:
        raise Http404
    return request.carddav_user


@csrf_exempt
@carddav_basic_auth
def dav_root(request):
    """Dienstwurzel — hier sucht der Client ``current-user-principal``."""
    if request.method == "OPTIONS":
        return _options()
    if request.method != "PROPFIND":
        return _nicht_erlaubt()

    pk = request.carddav_user.pk
    verfuegbar = {
        qn(D, "current-user-principal"): _user_principal(pk),
        qn(D, "principal-URL"): _user_principal(pk),
        qn(C, "addressbook-home-set"): _home_set(pk),
        qn(D, "resourcetype"): _collection(),
        qn(D, "displayname"): "CantorHub",
        qn(D, "current-user-privilege-set"): _privilegien(),
    }
    try:
        angefragt = dav.parse_propfind(request.body)
    except ValueError as exc:
        return _schlechte_anfrage(exc)
    gefunden, fehlend = _aufteilen(angefragt, verfuegbar)
    return _multistatus([("/carddav/", gefunden, fehlend)])


@csrf_exempt
@carddav_basic_auth
def principal(request, pk):
    """Das Principal des angemeldeten Mitglieds."""
    if request.method == "OPTIONS":
        return _options()
    if request.method != "PROPFIND":
        return _nicht_erlaubt()
    user = _eigenes_buch(request, pk)

    verfuegbar = {
        qn(D, "current-user-principal"): _user_principal(pk),
        qn(D, "principal-URL"): _user_principal(pk),
        qn(D, "principal-collection-set"): [element(D, "href", "/carddav/")],
        qn(C, "addressbook-home-set"): _home_set(pk),
        qn(D, "resourcetype"): [element(D, "principal")],
        qn(D, "displayname"): str(user),
        qn(D, "owner"): _user_principal(pk),
        qn(D, "supported-report-set"): [],
        qn(D, "current-user-privilege-set"): _privilegien(),
    }
    if user.email:
        verfuegbar[qn(CS, "email-address-set")] = [
            element(CS, "email-address", user.email)
        ]
    try:
        angefragt = dav.parse_propfind(request.body)
    except ValueError as exc:
        return _schlechte_anfrage(exc)
    gefunden, fehlend = _aufteilen(angefragt, verfuegbar)
    return _multistatus([(_p_principal(pk), gefunden, fehlend)])


def _buch_properties(pk, kontakte):
    """Die Properties der Adressbuch-Sammlung selbst."""
    return {
        qn(D, "current-user-principal"): _user_principal(pk),
        qn(D, "resourcetype"): _collection(element(C, "addressbook")),
        qn(D, "displayname"): daten.adressbuch_name(),
        qn(D, "owner"): _user_principal(pk),
        qn(CS, "getctag"): daten.ctag(kontakte),
        qn(D, "supported-report-set"): _reports(),
        qn(C, "supported-address-data"): [
            element(C, "address-data-type", **{
                "content-type": "text/vcard", "version": "3.0",
            })
        ],
        qn(C, "addressbook-description"): daten.adressbuch_name(),
        qn(C, "max-resource-size"): "10485760",
        qn(D, "current-user-privilege-set"): _privilegien(),
    }


@csrf_exempt
@carddav_basic_auth
def home_set(request, pk):
    """Das Sammlungsverzeichnis: enthält genau ein Adressbuch."""
    if request.method == "OPTIONS":
        return _options()
    if request.method != "PROPFIND":
        return _nicht_erlaubt()
    _eigenes_buch(request, pk)

    try:
        angefragt = dav.parse_propfind(request.body)
    except ValueError as exc:
        return _schlechte_anfrage(exc)

    eigen = {
        qn(D, "current-user-principal"): _user_principal(pk),
        qn(D, "resourcetype"): _collection(),
        qn(D, "displayname"): "Adressbücher",
        qn(D, "owner"): _user_principal(pk),
        qn(D, "current-user-privilege-set"): _privilegien(),
    }
    gefunden, fehlend = _aufteilen(angefragt, eigen)
    eintraege = [(_p_home(pk), gefunden, fehlend)]

    if _tiefe(request) > 0:
        kontakte = daten.kontakt_liste(
            request.carddav_user, basis_url=_basis(request)
        )
        g, f = _aufteilen(angefragt, _buch_properties(pk, kontakte))
        eintraege.append((_p_buch(pk), g, f))
    return _multistatus(eintraege)


@csrf_exempt
@carddav_basic_auth
def adressbuch(request, pk):
    """Das Adressbuch: Sammlungs-Properties, ETag-Liste und die Reports."""
    if request.method == "OPTIONS":
        return _options()
    if request.method not in ("PROPFIND", "REPORT"):
        return _nicht_erlaubt()
    _eigenes_buch(request, pk)

    kontakte = daten.kontakt_liste(
        request.carddav_user, basis_url=_basis(request)
    )

    try:
        if request.method == "REPORT":
            art, angefragt, hrefs, limit = dav.parse_report(request.body)
            return _report(pk, kontakte, art, angefragt, hrefs, limit)
        angefragt = dav.parse_propfind(request.body)
    except ValueError as exc:
        return _schlechte_anfrage(exc)

    gefunden, fehlend = _aufteilen(angefragt, _buch_properties(pk, kontakte))
    eintraege = [(_p_buch(pk), gefunden, fehlend)]

    if _tiefe(request) > 0:
        will_daten = angefragt is not None and qn(C, "address-data") in angefragt
        for m, kdaten, tag in kontakte:
            g, f = _aufteilen(
                angefragt,
                _karten_properties(m, kdaten, tag, mit_daten=will_daten),
            )
            eintraege.append((_p_karte(pk, m.pk), g, f))
    return _multistatus(eintraege)


def _karten_properties(mitglied, kdaten, tag, *, mit_daten=False):
    """Properties einer einzelnen Karte.

    ``address-data`` und ``getcontentlength`` verlangen die fertige vCard samt
    Foto; sie werden nur gebaut, wenn wirklich danach gefragt wurde.
    """
    props = {
        qn(D, "getetag"): tag,
        qn(D, "getcontenttype"): "text/vcard; charset=utf-8",
        qn(D, "resourcetype"): [],
        qn(D, "current-user-privilege-set"): _privilegien(),
    }
    if mit_daten:
        from . import vcard as _v

        text = _v.vcard_text(kdaten, daten.foto_bytes(mitglied))
        props[qn(C, "address-data")] = text
        props[qn(D, "getcontentlength")] = str(len(text.encode("utf-8")))
    return props


def _report(pk, kontakte, art, angefragt, hrefs, limit):
    """``addressbook-multiget`` und ``addressbook-query``.

    Der Filter des ``addressbook-query`` wird nicht ausgewertet — bei einem
    read-only Dienst ist Über-Lieferung folgenlos, und Clients nutzen den Report
    ohnehin vor allem, um alle ETags zu bekommen.
    """
    if art is None:
        return _schlechte_anfrage("unbekannter Report")

    will_daten = angefragt is None or qn(C, "address-data") in angefragt

    ausgewaehlt = kontakte
    if art == "multiget":
        # Der Client schickt die hrefs zurück, die er von uns bekommen hat;
        # unquote, damit eine prozentkodierte Fassung genauso trifft.
        gesucht = set()
        for href in hrefs:
            name = unquote(href).rstrip("/").rsplit("/", 1)[-1]
            if name.endswith(".vcf") and name[:-4].isdigit():
                gesucht.add(int(name[:-4]))
        ausgewaehlt = [k for k in kontakte if k[0].pk in gesucht]
    elif limit:
        ausgewaehlt = kontakte[:limit]

    eintraege = []
    for m, kdaten, tag in ausgewaehlt:
        verfuegbar = _karten_properties(m, kdaten, tag, mit_daten=will_daten)
        g, f = _aufteilen(angefragt, verfuegbar)
        eintraege.append((_p_karte(pk, m.pk), g, f))

    if art == "multiget":
        # Angefragte, aber nicht vorhandene Karten müssen als 404 auftauchen —
        # sonst wartet der Client ewig auf eine Antwort, die nie kommt.
        vorhanden = {m.pk for m, _d, _t in ausgewaehlt}
        for href in hrefs:
            name = unquote(href).rstrip("/").rsplit("/", 1)[-1]
            if not (name.endswith(".vcf") and name[:-4].isdigit()):
                continue
            mid = int(name[:-4])
            if mid not in vorhanden:
                eintraege.append((_p_karte(pk, mid), {}, angefragt or []))
    return _multistatus(eintraege)


@csrf_exempt
@carddav_basic_auth
def kontakt(request, pk, mid):
    """Eine einzelne Karte als ``text/vcard``."""
    if request.method == "OPTIONS":
        return _options()
    if request.method not in ("GET", "HEAD", "PROPFIND"):
        return _nicht_erlaubt()
    _eigenes_buch(request, pk)

    basis = _basis(request)
    mitglied = daten.mitglieder_qs(request.carddav_user).filter(pk=mid).first()
    if mitglied is None:
        # Deckt auch die eigene Karte ab: mitglieder_qs schliesst sie aus, also
        # ist sie hier zu Recht nicht auffindbar.
        raise Http404

    kdaten = daten.kontakt_daten(mitglied, basis_url=basis)
    from . import vcard as _v

    tag = _v.etag(kdaten)

    if request.method == "PROPFIND":
        try:
            angefragt = dav.parse_propfind(request.body)
        except ValueError as exc:
            return _schlechte_anfrage(exc)
        will_daten = angefragt is not None and qn(C, "address-data") in angefragt
        g, f = _aufteilen(
            angefragt,
            _karten_properties(mitglied, kdaten, tag, mit_daten=will_daten),
        )
        return _multistatus([(_p_karte(pk, mid), g, f)])

    text = _v.vcard_text(kdaten, daten.foto_bytes(mitglied))
    r = HttpResponse(
        b"" if request.method == "HEAD" else text.encode("utf-8"),
        content_type="text/vcard; charset=utf-8",
    )
    r["ETag"] = tag
    # GZipMiddleware schwächt einen starken ETag zu W/"…" ab (gzip.py). Der
    # Client sähe hier also einen anderen Wert als im 207 und lüde endlos neu.
    # Ein gesetztes Content-Encoding lässt die Middleware abbrechen.
    r["Content-Encoding"] = "identity"
    return r


# --------------------------------------------------------------------------
# Kleinkram
# --------------------------------------------------------------------------

def _basis(request):
    """Basis-URL für die ``URL:``-Zeile der Karten."""
    return get_base_url() or f"{request.scheme}://{request.get_host()}"


def _tiefe(request):
    """``Depth``-Kopf; fehlt er, gilt 0. ``infinity`` behandeln wir wie 1."""
    roh = (request.META.get("HTTP_DEPTH") or "0").strip().lower()
    if roh == "infinity":
        return 1
    return 1 if roh == "1" else 0


def _schlechte_anfrage(grund):
    logger.info("CardDAV: Anfrage abgewiesen (%s)", grund)
    return dav_kopfzeilen(
        HttpResponse("Bad Request", status=400,
                     content_type="text/plain; charset=utf-8")
    )

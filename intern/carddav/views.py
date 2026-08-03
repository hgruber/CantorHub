"""Die CardDAV-Endpunkte.

Alle Views sind Funktionen, keine Klassen: das URL-Auflösen ist von der Methode
unabhängig und ``request.method`` nur ein String, also funktionieren PROPFIND und
REPORT hier ohne Zutun — eine ``View``-Klasse bräuchte erweiterte
``http_method_names`` plus kleingeschriebene Handler.

Alle Views sind ``csrf_exempt``. CardDAV-Clients senden weder Cookie noch Origin
oder Referer; die Prüfung würde jedes PROPFIND mit 403 beantworten. Die
Autorisierung leistet vollständig HTTP-Basic in :mod:`intern.dav.auth`.
"""

import logging

from django.http import Http404, HttpResponse, HttpResponsePermanentRedirect
from django.views.decorators.csrf import csrf_exempt

from ..dav import http, verweise, xml as dav
from ..dav.auth import Dienst, dav_basic_auth
from ..dav.xml import NS_CARDDAV as C, NS_CS as CS, NS_DAV as D, element, qn
from . import daten

logger = logging.getLogger(__name__)

__all__ = [
    "well_known", "dav_root", "principal", "home_set", "adressbuch", "kontakt",
]

DIENST = Dienst(
    name="carddav",
    realm="CantorHub Adressbuch",
    dav_header="1, 3, addressbook",
    prefix="CARDDAV",
)

basic_auth = dav_basic_auth(DIENST)


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
# Bausteine
# --------------------------------------------------------------------------

def _reports():
    """``supported-report-set``. ``sync-collection`` steht bewusst nicht drin."""
    return [
        http.supported_report(C, "addressbook-multiget"),
        http.supported_report(C, "addressbook-query"),
    ]


def _fehler(grund):
    return http.schlechte_anfrage(grund, DIENST)


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


@csrf_exempt
@basic_auth
def dav_root(request):
    """Dienstwurzel — hier sucht der Client ``current-user-principal``."""
    if request.method == "OPTIONS":
        return http.options()
    if request.method != "PROPFIND":
        return http.nicht_erlaubt()

    pk = request.dav_user.pk
    verfuegbar = {
        qn(D, "current-user-principal"): http.href(_p_principal(pk)),
        qn(D, "principal-URL"): http.href(_p_principal(pk)),
        qn(D, "resourcetype"): http.collection(),
        qn(D, "displayname"): "CantorHub",
        qn(D, "current-user-privilege-set"): http.privilegien(),
        # Auch das Kalender-Home-Set, sofern der Kalender läuft: dadurch genügt
        # eine einzige Basis-URL für beide Dienste.
        **verweise.home_sets(pk, "carddav"),
    }
    try:
        angefragt = dav.parse_propfind(request.body)
    except ValueError as exc:
        return _fehler(exc)
    gefunden, fehlend = http.aufteilen(angefragt, verfuegbar)
    return http.multistatus_antwort([("/carddav/", gefunden, fehlend)])


@csrf_exempt
@basic_auth
def principal(request, pk):
    """Das Principal des angemeldeten Mitglieds."""
    if request.method == "OPTIONS":
        return http.options()
    if request.method != "PROPFIND":
        return http.nicht_erlaubt()
    user = http.pruefe_eigentuemer(request, pk)

    verfuegbar = {
        qn(D, "current-user-principal"): http.href(_p_principal(pk)),
        qn(D, "principal-URL"): http.href(_p_principal(pk)),
        qn(D, "principal-collection-set"): http.href("/carddav/"),
        qn(D, "resourcetype"): [element(D, "principal")],
        qn(D, "displayname"): str(user),
        qn(D, "owner"): http.href(_p_principal(pk)),
        qn(D, "supported-report-set"): [],
        qn(D, "current-user-privilege-set"): http.privilegien(),
        **verweise.home_sets(pk, "carddav"),
    }
    if user.email:
        verfuegbar[qn(CS, "email-address-set")] = [
            element(CS, "email-address", user.email)
        ]
    try:
        angefragt = dav.parse_propfind(request.body)
    except ValueError as exc:
        return _fehler(exc)
    gefunden, fehlend = http.aufteilen(angefragt, verfuegbar)
    return http.multistatus_antwort([(_p_principal(pk), gefunden, fehlend)])


def _buch_properties(pk, kontakte):
    """Die Properties der Adressbuch-Sammlung selbst."""
    return {
        qn(D, "current-user-principal"): http.href(_p_principal(pk)),
        qn(D, "resourcetype"): http.collection(element(C, "addressbook")),
        qn(D, "displayname"): daten.adressbuch_name(),
        qn(D, "owner"): http.href(_p_principal(pk)),
        qn(CS, "getctag"): daten.ctag(kontakte),
        qn(D, "supported-report-set"): _reports(),
        qn(C, "supported-address-data"): [
            element(C, "address-data-type", **{
                "content-type": "text/vcard", "version": "3.0",
            })
        ],
        qn(C, "addressbook-description"): daten.adressbuch_name(),
        qn(C, "max-resource-size"): "10485760",
        qn(D, "current-user-privilege-set"): http.privilegien(),
    }


@csrf_exempt
@basic_auth
def home_set(request, pk):
    """Das Sammlungsverzeichnis: enthält genau ein Adressbuch."""
    if request.method == "OPTIONS":
        return http.options()
    if request.method != "PROPFIND":
        return http.nicht_erlaubt()
    http.pruefe_eigentuemer(request, pk)

    try:
        angefragt = dav.parse_propfind(request.body)
    except ValueError as exc:
        return _fehler(exc)

    eigen = {
        qn(D, "current-user-principal"): http.href(_p_principal(pk)),
        qn(D, "resourcetype"): http.collection(),
        qn(D, "displayname"): "Adressbücher",
        qn(D, "owner"): http.href(_p_principal(pk)),
        qn(D, "current-user-privilege-set"): http.privilegien(),
    }
    gefunden, fehlend = http.aufteilen(angefragt, eigen)
    eintraege = [(_p_home(pk), gefunden, fehlend)]

    if http.tiefe(request) > 0:
        kontakte = daten.kontakt_liste(
            request.dav_user, basis_url=http.basis(request)
        )
        g, f = http.aufteilen(angefragt, _buch_properties(pk, kontakte))
        eintraege.append((_p_buch(pk), g, f))
    return http.multistatus_antwort(eintraege)


@csrf_exempt
@basic_auth
def adressbuch(request, pk):
    """Das Adressbuch: Sammlungs-Properties, ETag-Liste und die Reports."""
    if request.method == "OPTIONS":
        return http.options()
    if request.method not in ("PROPFIND", "REPORT"):
        return http.nicht_erlaubt()
    http.pruefe_eigentuemer(request, pk)

    kontakte = daten.kontakt_liste(
        request.dav_user, basis_url=http.basis(request)
    )

    try:
        if request.method == "REPORT":
            return _report(pk, kontakte, dav.parse_report(request.body))
        angefragt = dav.parse_propfind(request.body)
    except ValueError as exc:
        return _fehler(exc)

    gefunden, fehlend = http.aufteilen(angefragt, _buch_properties(pk, kontakte))
    eintraege = [(_p_buch(pk), gefunden, fehlend)]

    if http.tiefe(request) > 0:
        will_daten = angefragt is not None and qn(C, "address-data") in angefragt
        for m, kdaten, tag in kontakte:
            g, f = http.aufteilen(
                angefragt,
                _karten_properties(m, kdaten, tag, mit_daten=will_daten),
            )
            eintraege.append((_p_karte(pk, m.pk), g, f))
    return http.multistatus_antwort(eintraege)


def _karten_properties(mitglied, kdaten, tag, *, mit_daten=False):
    """Properties einer einzelnen Karte.

    ``address-data`` und ``getcontentlength`` verlangen die fertige vCard samt
    Foto; sie werden nur gebaut, wenn wirklich danach gefragt wurde.
    """
    props = {
        qn(D, "getetag"): tag,
        qn(D, "getcontenttype"): "text/vcard; charset=utf-8",
        qn(D, "resourcetype"): [],
        qn(D, "current-user-privilege-set"): http.privilegien(),
    }
    if mit_daten:
        from . import vcard as _v

        text = _v.vcard_text(kdaten, daten.foto_bytes(mitglied))
        props[qn(C, "address-data")] = text
        props[qn(D, "getcontentlength")] = str(len(text.encode("utf-8")))
    return props


def _report(pk, kontakte, bericht):
    """``addressbook-multiget`` und ``addressbook-query``.

    Der Filter des ``addressbook-query`` wird nicht ausgewertet — bei einem
    read-only Dienst ist Über-Lieferung folgenlos, und Clients nutzen den Report
    ohnehin vor allem, um alle ETags zu bekommen.
    """
    if bericht.art is None:
        return _fehler("unbekannter Report")

    angefragt = bericht.props
    will_daten = angefragt is None or qn(C, "address-data") in angefragt

    gesucht = [
        mid for mid in (http.ressourcen_id(h, ".vcf") for h in bericht.hrefs)
        if mid is not None
    ]

    ausgewaehlt = kontakte
    if bericht.art == "multiget":
        ausgewaehlt = [k for k in kontakte if k[0].pk in set(gesucht)]
    elif bericht.limit:
        ausgewaehlt = kontakte[:bericht.limit]

    eintraege = []
    for m, kdaten, tag in ausgewaehlt:
        verfuegbar = _karten_properties(m, kdaten, tag, mit_daten=will_daten)
        g, f = http.aufteilen(angefragt, verfuegbar)
        eintraege.append((_p_karte(pk, m.pk), g, f))

    if bericht.art == "multiget":
        # Angefragte, aber nicht vorhandene Karten müssen als 404 auftauchen —
        # sonst wartet der Client ewig auf eine Antwort, die nie kommt.
        vorhanden = {m.pk for m, _d, _t in ausgewaehlt}
        for mid in gesucht:
            if mid not in vorhanden:
                eintraege.append((_p_karte(pk, mid), {}, angefragt or []))
    return http.multistatus_antwort(eintraege)


@csrf_exempt
@basic_auth
def kontakt(request, pk, mid):
    """Eine einzelne Karte als ``text/vcard``."""
    if request.method == "OPTIONS":
        return http.options()
    if request.method not in ("GET", "HEAD", "PROPFIND"):
        return http.nicht_erlaubt()
    http.pruefe_eigentuemer(request, pk)

    mitglied = daten.mitglieder_qs(request.dav_user).filter(pk=mid).first()
    if mitglied is None:
        # Deckt auch die eigene Karte ab: mitglieder_qs schliesst sie aus, also
        # ist sie hier zu Recht nicht auffindbar.
        raise Http404

    kdaten = daten.kontakt_daten(mitglied, basis_url=http.basis(request))
    from . import vcard as _v

    tag = _v.etag(kdaten)

    if request.method == "PROPFIND":
        try:
            angefragt = dav.parse_propfind(request.body)
        except ValueError as exc:
            return _fehler(exc)
        will_daten = angefragt is not None and qn(C, "address-data") in angefragt
        g, f = http.aufteilen(
            angefragt,
            _karten_properties(mitglied, kdaten, tag, mit_daten=will_daten),
        )
        return http.multistatus_antwort([(_p_karte(pk, mid), g, f)])

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

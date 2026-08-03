"""Die CalDAV-Endpunkte.

Aufbau wie beim Adressbuch (:mod:`intern.carddav.views`): Funktionen statt
``View``-Klassen, damit PROPFIND und REPORT ohne Zutun ankommen, und alles
``csrf_exempt``, weil DAV-Clients weder Cookie noch Origin oder Referer senden.
Die Autorisierung leistet vollständig HTTP-Basic in :mod:`intern.dav.auth`.
"""

import logging

from django.http import Http404, HttpResponse, HttpResponsePermanentRedirect
from django.views.decorators.csrf import csrf_exempt

from ..dav import http, verweise, xml as dav
from ..dav.auth import Dienst, dav_basic_auth
from ..dav.xml import NS_CALDAV as CAL, NS_CS as CS, NS_DAV as D, element, qn
from . import daten, ical

logger = logging.getLogger(__name__)

__all__ = [
    "well_known", "dav_root", "principal", "home_set", "sammlung", "eintrag",
]

DIENST = Dienst(
    name="caldav",
    realm="CantorHub Kalender",
    dav_header="1, 3, calendar-access",
    prefix="CALDAV",
)

basic_auth = dav_basic_auth(DIENST)


# --------------------------------------------------------------------------
# Pfade
# --------------------------------------------------------------------------

def _p_principal(pk):
    return f"/caldav/principal/{pk}/"


def _p_home(pk):
    return f"/caldav/kalender/{pk}/"


def _p_sammlung(pk, art):
    return f"/caldav/kalender/{pk}/{art}/"


def _p_eintrag(pk, art, eid):
    return f"/caldav/kalender/{pk}/{art}/{eid}.ics"


# --------------------------------------------------------------------------
# Bausteine
# --------------------------------------------------------------------------

def _reports():
    """``supported-report-set``. ``sync-collection`` steht bewusst nicht drin."""
    return [
        http.supported_report(CAL, "calendar-multiget"),
        http.supported_report(CAL, "calendar-query"),
    ]


def _fehler(grund):
    return http.schlechte_anfrage(grund, DIENST)


def _arten():
    """Die ausgelieferten Sammlungen, in der Reihenfolge der Anzeige."""
    if daten.geburtstage_aktiv():
        return daten.ARTEN
    return ("termine",)


def _pruefe_art(art):
    """Eine abgeschaltete Sammlung gibt es nicht — 404, nicht 403."""
    if art not in _arten():
        raise Http404
    return art


def _sammlung_properties(pk, art, liste):
    """Die Properties einer Kalendersammlung selbst."""
    name = daten.sammlung_name(art)
    props = {
        qn(D, "current-user-principal"): http.href(_p_principal(pk)),
        qn(D, "resourcetype"): http.collection(element(CAL, "calendar")),
        qn(D, "displayname"): name,
        qn(D, "owner"): http.href(_p_principal(pk)),
        qn(CS, "getctag"): daten.ctag(liste),
        qn(D, "supported-report-set"): _reports(),
        qn(CAL, "supported-calendar-component-set"): [
            element(CAL, "comp", name="VEVENT")
        ],
        qn(CAL, "supported-calendar-data"): [
            element(CAL, "calendar-data", **{
                "content-type": "text/calendar", "version": "2.0",
            })
        ],
        qn(CAL, "calendar-description"): name,
        qn(CAL, "max-resource-size"): "10485760",
        qn(D, "current-user-privilege-set"): http.privilegien(),
    }
    farbe = daten.farbe()
    if farbe:
        props[qn(CS, "calendar-color")] = farbe
    return props


def _eintrag_properties(e, *, stand, mit_daten=False):
    """Properties einer einzelnen ``.ics``.

    ``calendar-data`` und ``getcontentlength`` verlangen den fertigen Text; sie
    werden nur gebaut, wenn wirklich danach gefragt wurde.
    """
    props = {
        qn(D, "getetag"): e.tag,
        qn(D, "getcontenttype"): "text/calendar; charset=utf-8",
        qn(D, "resourcetype"): [],
        qn(D, "current-user-privilege-set"): http.privilegien(),
    }
    if mit_daten:
        text = ical.vcalendar_text(e.daten, stand=stand)
        props[qn(CAL, "calendar-data")] = text
        props[qn(D, "getcontentlength")] = str(len(text.encode("utf-8")))
    return props


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------

@csrf_exempt
def well_known(request):
    """RFC 6764: ``/.well-known/caldav`` → das Dienstwurzelverzeichnis.

    301 und ohne Anmeldung, aus denselben Gründen wie beim Adressbuch: iOS fragt
    beim Einrichten nur nach dem Hostnamen und findet den Kalender allein
    hierüber.
    """
    return HttpResponsePermanentRedirect("/caldav/")


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
        # Auch das Adressbuch-Home-Set, sofern das Adressbuch läuft: dadurch
        # genügt eine einzige Basis-URL für beide Dienste.
        **verweise.home_sets(pk, "caldav"),
    }
    try:
        angefragt = dav.parse_propfind(request.body)
    except ValueError as exc:
        return _fehler(exc)
    gefunden, fehlend = http.aufteilen(angefragt, verfuegbar)
    return http.multistatus_antwort([("/caldav/", gefunden, fehlend)])


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
        qn(D, "principal-collection-set"): http.href("/caldav/"),
        qn(D, "resourcetype"): [element(D, "principal")],
        qn(D, "displayname"): str(user),
        qn(D, "owner"): http.href(_p_principal(pk)),
        qn(D, "supported-report-set"): [],
        qn(D, "current-user-privilege-set"): http.privilegien(),
        **verweise.home_sets(pk, "caldav"),
    }
    if user.email:
        # Woran ein Client den Kalenderbenutzer erkennt; ohne Scheduling ist es
        # reine Anzeige, iOS mag es aber sehen.
        verfuegbar[qn(CAL, "calendar-user-address-set")] = http.href(
            f"mailto:{user.email}"
        )
        verfuegbar[qn(CS, "email-address-set")] = [
            element(CS, "email-address", user.email)
        ]
    try:
        angefragt = dav.parse_propfind(request.body)
    except ValueError as exc:
        return _fehler(exc)
    gefunden, fehlend = http.aufteilen(angefragt, verfuegbar)
    return http.multistatus_antwort([(_p_principal(pk), gefunden, fehlend)])


@csrf_exempt
@basic_auth
def home_set(request, pk):
    """Das Sammlungsverzeichnis: Termine und (wenn an) Geburtstage."""
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
        qn(D, "displayname"): "Kalender",
        qn(D, "owner"): http.href(_p_principal(pk)),
        qn(D, "current-user-privilege-set"): http.privilegien(),
    }
    gefunden, fehlend = http.aufteilen(angefragt, eigen)
    eintraege = [(_p_home(pk), gefunden, fehlend)]

    if http.tiefe(request) > 0:
        basis = http.basis(request)
        for art in _arten():
            liste = daten.eintraege(art, basis_url=basis)
            g, f = http.aufteilen(angefragt, _sammlung_properties(pk, art, liste))
            eintraege.append((_p_sammlung(pk, art), g, f))
    return http.multistatus_antwort(eintraege)


@csrf_exempt
@basic_auth
def sammlung(request, pk, art):
    """Eine Kalendersammlung: Properties, ETag-Liste und die Reports."""
    if request.method == "OPTIONS":
        return http.options()
    if request.method not in ("PROPFIND", "REPORT"):
        return http.nicht_erlaubt()
    http.pruefe_eigentuemer(request, pk)
    _pruefe_art(art)

    liste = daten.eintraege(art, basis_url=http.basis(request))
    stand = daten.stand()

    try:
        if request.method == "REPORT":
            return _report(pk, art, liste, dav.parse_report(request.body), stand)
        angefragt = dav.parse_propfind(request.body)
    except ValueError as exc:
        return _fehler(exc)

    gefunden, fehlend = http.aufteilen(
        angefragt, _sammlung_properties(pk, art, liste)
    )
    eintraege = [(_p_sammlung(pk, art), gefunden, fehlend)]

    if http.tiefe(request) > 0:
        will_daten = angefragt is not None and qn(CAL, "calendar-data") in angefragt
        for e in liste:
            g, f = http.aufteilen(
                angefragt,
                _eintrag_properties(e, stand=stand, mit_daten=will_daten),
            )
            eintraege.append((_p_eintrag(pk, art, e.objekt.pk), g, f))
    return http.multistatus_antwort(eintraege)


def _report(pk, art, liste, bericht, stand):
    """``calendar-multiget`` und ``calendar-query``.

    Vom Filter des ``calendar-query`` werden die beiden billigen Teile
    ausgewertet: fragt der Client nach ``VTODO`` oder ``VJOURNAL``, bekommt er
    eine leere Antwort statt ersatzweise Termine, und ein ``time-range`` grenzt
    ein. Alles Weitere wird ignoriert — bei einem read-only Dienst ist
    Über-Lieferung folgenlos.
    """
    if bericht.art is None:
        return _fehler("unbekannter Report")

    angefragt = bericht.props
    will_daten = angefragt is None or qn(CAL, "calendar-data") in angefragt

    gesucht = [
        eid for eid in (http.ressourcen_id(h, ".ics") for h in bericht.hrefs)
        if eid is not None
    ]

    if bericht.art == "multiget":
        ausgewaehlt = [e for e in liste if e.objekt.pk in set(gesucht)]
    elif bericht.komponenten and "VEVENT" not in bericht.komponenten:
        ausgewaehlt = []
    elif bericht.zeitraum:
        ausgewaehlt = daten.nach_zeitraum(liste, bericht.zeitraum)
    else:
        ausgewaehlt = liste

    eintraege = []
    for e in ausgewaehlt:
        g, f = http.aufteilen(
            angefragt, _eintrag_properties(e, stand=stand, mit_daten=will_daten)
        )
        eintraege.append((_p_eintrag(pk, art, e.objekt.pk), g, f))

    if bericht.art == "multiget":
        # Angefragte, aber nicht vorhandene Ressourcen müssen als 404
        # auftauchen — sonst wartet der Client ewig auf eine Antwort, die nie
        # kommt.
        vorhanden = {e.objekt.pk for e in ausgewaehlt}
        for eid in gesucht:
            if eid not in vorhanden:
                eintraege.append((_p_eintrag(pk, art, eid), {}, angefragt or []))
    return http.multistatus_antwort(eintraege)


@csrf_exempt
@basic_auth
def eintrag(request, pk, art, eid):
    """Ein einzelner Termin als ``text/calendar``."""
    if request.method == "OPTIONS":
        return http.options()
    if request.method not in ("GET", "HEAD", "PROPFIND"):
        return http.nicht_erlaubt()
    http.pruefe_eigentuemer(request, pk)
    _pruefe_art(art)

    e = daten.einzeln(art, eid, basis_url=http.basis(request))
    if e is None:
        raise Http404
    stand = daten.stand()

    if request.method == "PROPFIND":
        try:
            angefragt = dav.parse_propfind(request.body)
        except ValueError as exc:
            return _fehler(exc)
        will_daten = angefragt is not None and qn(CAL, "calendar-data") in angefragt
        g, f = http.aufteilen(
            angefragt,
            _eintrag_properties(e, stand=stand, mit_daten=will_daten),
        )
        return http.multistatus_antwort([(_p_eintrag(pk, art, eid), g, f)])

    text = ical.vcalendar_text(e.daten, stand=stand)
    r = HttpResponse(
        b"" if request.method == "HEAD" else text.encode("utf-8"),
        content_type="text/calendar; charset=utf-8",
    )
    r["ETag"] = e.tag
    # GZipMiddleware schwächt einen starken ETag zu W/"…" ab (gzip.py). Der
    # Client sähe hier also einen anderen Wert als im 207 und lüde endlos neu.
    # Ein gesetztes Content-Encoding lässt die Middleware abbrechen.
    r["Content-Encoding"] = "identity"
    return r

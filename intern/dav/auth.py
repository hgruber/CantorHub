"""HTTP-Basic-Authentifizierung für die DAV-Views.

Angemeldet wird sich mit dem normalen Portal-Passwort. Das ist so gewollt, hat
aber eine Kehrseite, die im Blick bleiben muss: das Passwort landet damit im
Android-AccountManager beziehungsweise im iOS-Schlüsselbund. Ein verlorenes,
entsperrtes Telefon gibt Zugang zum ganzen Portal — bei einem Vorstandsmitglied
mitsamt Verwaltungsrechten. Die Abhilfe wäre ein widerrufbares Gerätepasswort;
:func:`_pruefe_anmeldung` ist absichtlich der einzige Prüfpunkt, damit ein
solcher Pfad später dort ergänzt werden kann, ohne die Views anzufassen.

Warum kein ``@login_required``: ``LOGIN_URL`` zeigt auf ``/intern/login/``, ein
PROPFIND bekäme also 302 auf eine HTML-Seite. DAVx⁵ meldet dann „Dienst nicht
gefunden", iOS scheitert stumm. Es muss ein 401 mit ``WWW-Authenticate`` sein.

Adressbuch und Kalender teilen sich diesen Code und unterscheiden sich nur in
dem, was :class:`Dienst` festhält — insbesondere im Konfigurationspräfix, über
das jeder Dienst einzeln freigeschaltet und gedrosselt wird.
"""

import base64
import binascii
import logging
from functools import wraps
from typing import NamedTuple

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.utils.crypto import salted_hmac
from django.utils.cache import patch_vary_headers

from ..app_settings import get_config_bool, get_config_int
from ..views.auth import _client_ip

logger = logging.getLogger(__name__)

__all__ = ["Dienst", "dav_basic_auth", "dav_kopfzeilen", "ALLOW_HEADER"]

ALLOW_HEADER = "OPTIONS, GET, HEAD, PROPFIND, REPORT"


class Dienst(NamedTuple):
    """Was einen DAV-Dienst von seinem Geschwister unterscheidet.

    ``dav_header`` ist die ``DAV:``-Kopfzeile. Die 2 (LOCK) wird bewusst nicht
    behauptet — wir sperren nichts. Sollte ein Client daran Anstoss nehmen, ist
    ``"1, 2, 3, …"`` der nächste Versuch.

    ``prefix`` benennt die Konfigurationsschlüssel ``<PREFIX>_AKTIV``,
    ``<PREFIX>_AUTH_TTL`` und ``<PREFIX>_MAX_FEHLVERSUCHE_PRO_STUNDE``.
    """

    name: str
    realm: str
    dav_header: str
    prefix: str


def dav_kopfzeilen(response, dienst):
    """Setzt die Kopfzeilen, die auf **jeder** Antwort stehen müssen.

    ``DAV:`` prüft iOS mehrfach, auch auf 401 und 405. ``Vary: Authorization``
    und ``no-store`` verhindern, dass ein Zwischenspeicher die Daten des einen
    Mitglieds an ein anderes ausliefert.
    """
    response["DAV"] = dienst.dav_header
    response["Cache-Control"] = "private, no-store"
    patch_vary_headers(response, ("Authorization",))
    return response


def _challenge(dienst):
    """401 mit Aufforderung zur Basic-Anmeldung."""
    r = HttpResponse(status=401, content_type="text/plain; charset=utf-8")
    # charset="UTF-8" (RFC 7617) ist hier nicht kosmetisch: Benutzernamen dürfen
    # in diesem Projekt Leerzeichen und Umlaute enthalten (User.username setzt
    # validators=[]).
    r["WWW-Authenticate"] = f'Basic realm="{dienst.realm}", charset="UTF-8"'
    return dav_kopfzeilen(r, dienst)


def _zugangsdaten(request):
    """``(benutzer, passwort)`` aus dem Authorization-Kopf, sonst ``None``."""
    kopf = request.META.get("HTTP_AUTHORIZATION", "")
    if not kopf.startswith("Basic "):
        return None
    try:
        roh = base64.b64decode(kopf[6:].strip(), validate=True)
    except (binascii.Error, ValueError):
        return None
    try:
        text = roh.decode("utf-8")
    except UnicodeDecodeError:
        text = roh.decode("latin-1")
    if ":" not in text:
        return None
    benutzer, passwort = text.split(":", 1)
    return benutzer, passwort


def _cache_key(username, passwort):
    """Schlüssel des Verifikationszwischenspeichers.

    ``salted_hmac`` zieht den ``SECRET_KEY`` mit hinein. Wer die ``cache_table``
    liest, ohne ihn zu kennen, kann aus dem Digest nichts zurückrechnen — der
    Schlüssel steht als Umgebungsvariable ausserhalb der Datenbank.

    Der Eintrag gilt dienstübergreifend: geprüft wird ein Portal-Passwort, und
    das ist für Adressbuch und Kalender dasselbe.
    """
    roh = f"{username}\x00{passwort}"
    digest = salted_hmac("intern.dav.auth", roh, algorithm="sha256")
    return "dav-auth:" + digest.hexdigest()


def _passwort_kennung(user):
    """Kurzdigest des *gespeicherten* Hashes.

    Bindet den zwischengespeicherten Eintrag an den aktuellen Passwortstand, so
    dass eine Passwortänderung ihn sofort entwertet statt erst nach Ablauf.
    """
    return salted_hmac(
        "intern.dav.pw", user.password, algorithm="sha256"
    ).hexdigest()[:16]


def _pruefe_anmeldung(username, passwort, dienst):
    """Prüft Zugangsdaten und gibt den ``User`` zurück, sonst ``None``.

    Der Zwischenspeicher überspringt **ausschliesslich** den PBKDF2-Aufruf,
    keine Autorisierungsentscheidung: ``is_active`` und der Passwortstand werden
    bei jedem Treffer neu gelesen. Ohne ihn kostete jede Anfrage einige hundert
    Millisekunden CPU, und ein Sync-Client stellt für einen einzigen Abgleich
    ein halbes Dutzend davon — bei drei Arbeitsprozessen wäre das Portal damit
    beschäftigt, immer wieder dasselbe Passwort zu prüfen.

    Abwägung: Wer ``SECRET_KEY`` *und* Datenbank hat, kann gegen die Schlüssel
    Kandidatenpasswörter mit schnellem SHA-256 durchprobieren — das ist die
    Abschwächung gegenüber PBKDF2. Sie ist auf ``<PREFIX>_AUTH_TTL`` begrenzt,
    und wer beides hat, besitzt ohnehin Sitzungen, Signatur-Salts und die
    Datei-Token.
    """
    from ..models import User

    key = _cache_key(username, passwort)
    eintrag = cache.get(key)
    if eintrag:
        user = User.objects.filter(pk=eintrag["pk"]).first()
        if user and user.is_active and _passwort_kennung(user) == eintrag["ph"]:
            return user
        cache.delete(key)

    # authenticate() statt check_password(): es prüft is_active über
    # user_can_authenticate() mit, bedient den Legacy-Hasher samt Aufrüstung auf
    # PBKDF2 — und löst, anders als login(), kein user_logged_in aus, erzeugt
    # also keine Flut von "login"-Zeilen im Änderungsprotokoll.
    user = authenticate(username=username, password=passwort)
    if user is None:
        return None
    cache.set(
        key,
        {"pk": user.pk, "ph": _passwort_kennung(user)},
        get_config_int(f"{dienst.prefix}_AUTH_TTL", 300),
    )
    return user


def dav_basic_auth(dienst):
    """Verlangt HTTP-Basic und hängt den Betrachter an ``request.dav_user``."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            # Der Dienst wird ausgeliefert, aber erst freigeschaltet, wenn die
            # Mitglieder informiert sind (Datenschutzerklärung, Abschnitt
            # „Sichtbarkeit Deiner Daten im Portal“). Http404 statt 403:
            # solange er aus ist, gibt es ihn schlicht nicht.
            if not get_config_bool(f"{dienst.prefix}_AKTIV", False):
                raise Http404

            drossel = f"{dienst.name}-auth-fail:{_client_ip(request)}"
            fehlversuche = cache.get(drossel, 0)
            grenze = get_config_int(
                f"{dienst.prefix}_MAX_FEHLVERSUCHE_PRO_STUNDE", 30
            )
            if fehlversuche >= grenze:
                # Bewusst 401 und nicht 429: der Client soll es später erneut
                # versuchen, nicht das Konto als kaputt abschreiben.
                return _challenge(dienst)

            zugang = _zugangsdaten(request)
            if zugang is None:
                return _challenge(dienst)

            user = _pruefe_anmeldung(*zugang, dienst)
            if user is None:
                cache.set(drossel, fehlversuche + 1, 3600)
                logger.info("%s: Anmeldung fehlgeschlagen für %r",
                            dienst.name, zugang[0])
                return _challenge(dienst)
            if fehlversuche:
                cache.delete(drossel)

            request.dav_user = user
            return dav_kopfzeilen(view(request, *args, **kwargs), dienst)

        return wrapper

    return decorator

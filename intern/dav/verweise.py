"""Wechselseitige Auffindbarkeit von Adressbuch und Kalender.

Das ist der Kern davon, dass in DAVx⁵ oder iOS die blosse Basis-URL des Portals
genügt: **jeder** der beiden Dienste nennt in seiner Wurzel und in seinem
Principal die Home-Sets **beider** Dienste. Ein Client, der nur einen der beiden
``/.well-known/``-Pfade abfragt, findet den anderen darüber trotzdem und legt
ein Konto mit Adressbuch *und* Kalendern an.

Genannt wird ein fremdes Home-Set aber nur, wenn der zugehörige Dienst
eingeschaltet ist — sonst schickte man den Client auf einen Pfad, der ihm 404
antwortet.
"""

from ..app_settings import get_config_bool
from .http import href
from .xml import NS_CALDAV, NS_CARDDAV, qn

__all__ = ["home_sets"]

# Dienstname → (Konfigurationsschalter, Property, Pfad des Home-Sets)
_DIENSTE = {
    "carddav": (
        "CARDDAV_AKTIV",
        qn(NS_CARDDAV, "addressbook-home-set"),
        lambda pk: f"/carddav/adressbuch/{pk}/",
    ),
    "caldav": (
        "CALDAV_AKTIV",
        qn(NS_CALDAV, "calendar-home-set"),
        lambda pk: f"/caldav/kalender/{pk}/",
    ),
}


def home_sets(pk, eigener):
    """Die Home-Set-Properties für Wurzel und Principal.

    ``eigener`` ist der Dienst, der gerade antwortet; sein Home-Set steht immer
    drin — dass er läuft, hat der Anmelde-Decorator bereits geprüft.
    """
    props = {}
    for name, (schalter, prop, pfad) in _DIENSTE.items():
        if name == eigener or get_config_bool(schalter, False):
            props[prop] = href(pfad(pk))
    return props

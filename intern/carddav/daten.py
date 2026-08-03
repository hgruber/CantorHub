"""Der einzige Berührpunkt des CardDAV-Pakets mit Datenbank und Dateispeicher.

Alles, was hier steht, lässt sich nur mit einer Testdatenbank prüfen — und die
gibt es in diesem Projekt nicht (die Migration ``0003_import`` bräuchte den
Altbestand auf dem MySQL-Server). Deshalb bleibt dieses Modul dünn und schiebt
jede Entscheidung, die sich rein rechnerisch treffen lässt, nach
:mod:`~intern.carddav.vcard` — dort ist sie testbar.
"""

import logging

from ..app_settings import get_config, get_config_bool, get_vereinsname_lang
from . import vcard

logger = logging.getLogger(__name__)

__all__ = [
    "carddav_sichtbar", "mitglieder_qs", "foto_kennung", "foto_bytes",
    "kontakt_daten", "kontakt_liste", "ctag", "adressbuch_name", "organisation",
]

# Muss mit signals._THUMBNAIL_SIZES übereinstimmen, sonst rendert der erste
# Abruf jedes Bild neu, statt das beim Upload erzeugte zu verwenden.
_FOTO_OPTIONEN = {"size": (200, 200), "quality": 85}

_MIME_NACH_ENDUNG = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png", "gif": "image/gif",
}


def carddav_sichtbar(mitglied, feld):
    """Ob ``feld`` in den Export darf. **Kein Admin-Bonus** — Absicht.

    ``User.field_visible_to()`` lässt Halter von ``intern.change_user`` auch
    verborgene Felder sehen; im Portal ist das eine Verwaltungsansicht. Eine
    vCard dagegen wandert in die System-Kontaktdatenbank des Telefons, wird von
    dort automatisch zum Gerätehersteller gesichert und von Messenger-Apps
    ausgelesen. Wer seine Anschrift verbirgt, willigt darin nicht ein, nur weil
    der Abrufende im Vorstand sitzt.

    Nebeneffekt, auf dem die ganze Architektur ruht: jede Karte ist für jeden
    Abrufenden gleich, also sind die ETags global statt pro Konto.
    """
    return feld not in (mitglied.private_fields or [])


def mitglieder_qs(betrachter):
    """Das Adressbuch eines Betrachters: aktive Mitglieder ausser ihm selbst.

    ``is_active=True`` gilt hier für **alle**, abweichend von ``mitglied_list``,
    das Verwaltenden auch Inaktive zeigt: sonst füllt sich das Telefon eines
    Vorstandsmitglieds mit Ausgetretenen und anonymisierten Karteileichen.

    Sich selbst findet niemand im eigenen Adressbuch — iOS und Android führen
    ohnehin eine eigene „Meine Karte", ein zweiter Eintrag mit denselben Daten
    wäre ein Duplikat, das manche Clients zusammenzuführen versuchen.
    """
    from ..models import User

    return (
        User.objects.filter(is_active=True)
        .exclude(pk=betrachter.pk)
        .select_related("avatar")
        .order_by("last_name", "first_name", "pk")
    )


def foto_kennung(mitglied):
    """Identität des Profilbilds, ohne die Datei anzufassen.

    ``filer.File.sha1`` ist der Inhalts-Digest, den filer beim Upload berechnet.
    Damit steht im ETag ein Wert, der sich bei jedem Bildwechsel ändert, ohne
    dass ein PROPFIND über achtzig Kontakte achtzig Dateien öffnen müsste.
    """
    a = getattr(mitglied, "avatar", None)
    if a is None:
        return ""
    return f"{a.pk}:{a.sha1 or ''}:{a._file_size or 0}"


def foto_bytes(mitglied):
    """``(mime, bytes)`` des 200×200-Vorschaubilds — oder ``None``.

    Erst mit ``generate=False``, weil ``signals._THUMBNAIL_SIZES`` beim Upload
    exakt diese Grösse erzeugt; nur für Altbestand fällt der Aufruf auf
    Erzeugung zurück. Der MIME-Typ kommt aus dem Namen des *Vorschaubilds*, nicht
    aus ``File.mime_type``: easy-thumbnails schreibt je nach Quelle JPEG oder PNG.

    Scheitert irgendetwas, gibt es kein Foto statt eines Fehlers. Ein Abgleich
    darf nicht an einem kaputten Avatar sterben.
    """
    a = getattr(mitglied, "avatar", None)
    if a is None or not get_config_bool("CARDDAV_FOTO", True):
        return None
    try:
        from easy_thumbnails.files import get_thumbnailer

        thumb = get_thumbnailer(a.file).get_thumbnail(
            _FOTO_OPTIONEN, generate=False
        )
        if thumb is None:
            thumb = get_thumbnailer(a.file).get_thumbnail(_FOTO_OPTIONEN)
        endung = (thumb.name or "").rsplit(".", 1)[-1].lower()
        mime = _MIME_NACH_ENDUNG.get(endung, "image/jpeg")
        thumb.open("rb")
        try:
            return mime, thumb.read()
        finally:
            thumb.close()
    except Exception:
        logger.warning("CardDAV: Profilbild von %s nicht lesbar", mitglied.pk,
                       exc_info=True)
        return None


def organisation():
    """Wert der vCard-Eigenschaft ``ORG``."""
    return get_config("CARDDAV_ORGANISATION") or get_vereinsname_lang() or ""


def adressbuch_name():
    """Anzeigename der Sammlung auf dem Gerät."""
    eigen = get_config("CARDDAV_ADRESSBUCH_NAME")
    if eigen:
        return eigen
    verein = get_vereinsname_lang() or "CantorHub"
    return f"{verein} – Mitglieder"


def _stimme_label(mitglied):
    """Anzeigename der Stimmlage; leer, wenn keine hinterlegt ist.

    ``"N"`` heisst „keine" und würde sonst als Titel „None" auf dem Telefon
    landen.
    """
    if getattr(mitglied, "stimme", "") in ("", "N"):
        return ""
    try:
        return mitglied.get_stimme_display()
    except AttributeError:
        return ""


def kontakt_daten(mitglied, *, basis_url, org=None):
    """``kontakt_daten``-dict eines Mitglieds, fertig gefiltert.

    ``org`` wird durchgereicht, statt es hier zu ermitteln: :func:`organisation`
    liest zwei Konfigurationswerte, und über achtzig Karten hinweg wären das
    zweihundert Abfragen für einen Wert, der sich innerhalb einer Antwort nicht
    ändert.
    """
    return vcard.kontakt_daten(
        mitglied,
        lambda feld: carddav_sichtbar(mitglied, feld),
        organisation=organisation() if org is None else org,
        basis_url=basis_url,
        stimme_label=_stimme_label(mitglied),
        foto_kennung=foto_kennung(mitglied),
    )


def kontakt_liste(betrachter, *, basis_url):
    """Alle Karten des Adressbuchs als ``(mitglied, daten, etag)``.

    Genau eine Datenbankabfrage für die Mitglieder plus die Konfigurationswerte,
    die einmal vorab geholt werden. Kein Profilbild wird geöffnet — der ETag
    läuft über :func:`foto_kennung`.
    """
    org = organisation()
    ergebnis = []
    for m in mitglieder_qs(betrachter):
        d = kontakt_daten(m, basis_url=basis_url, org=org)
        ergebnis.append((m, d, vcard.etag(d)))
    return ergebnis


def ctag(kontakte):
    """CTag der Sammlung aus dem Ergebnis von :func:`kontakt_liste`."""
    return vcard.ctag([(m.pk, tag) for m, _daten, tag in kontakte])

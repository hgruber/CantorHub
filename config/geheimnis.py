"""Der Django-Schlüssel (``SECRET_KEY``) als Datei im Datenverzeichnis.

Er ist kein Betriebsparameter, sondern ein Geheimnis: Ein Betreiber soll ihn
nicht erfinden, weitergeben oder in einer ``podman run``-Zeile stehen haben, die
in der Shell-Historie landet. Erzeugt wird er deshalb beim ersten Start und
bleibt im Datenverzeichnis liegen — damit überlebt er Neustarts und
Image-Wechsel, und die angemeldeten Sitzungen überstehen ein Update.

Nicht in der Tabelle ``Konfiguration``: ``settings.py`` braucht den Wert, bevor
Django steht, also bevor es ein ORM gibt. Ein zweiter Datenbankweg am ORM vorbei
wäre mehr Mechanik als eine Datei mit Rechten 0600 — und beim allerersten
``migrate`` existierte die Tabelle noch gar nicht.

Wie ``datenbank.py`` ohne Django-Importe, damit ``settings.py`` es früh laden und
der Testlauf es ohne Datenbank prüfen kann.
"""

import os
import secrets


class GeheimnisFehler(Exception):
    """Der Schlüssel ist weder lesbar noch anlegbar."""


def schluessel_lesen_oder_erzeugen(pfad):
    """Den Schlüssel aus ``pfad`` lesen, sonst einen erzeugen und dort ablegen.

    Beim Anlegen entscheidet ``O_EXCL`` das Rennen zweier gleichzeitig
    startender Prozesse: Der Verlierer bekommt ``FileExistsError`` und liest
    danach den Schlüssel des Gewinners. Ohne das könnten die drei
    gunicorn-Arbeiter mit verschiedenen Schlüsseln starten, und jede Sitzung
    wäre nur auf einem von ihnen gültig.
    """
    pfad = str(pfad)
    vorhanden = _lesen(pfad)
    if vorhanden:
        return vorhanden

    neuer = secrets.token_urlsafe(64)
    try:
        fd = os.open(pfad, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        vorhanden = _lesen(pfad)
        if vorhanden:
            return vorhanden
        raise GeheimnisFehler(
            f"{pfad} existiert, ist aber leer oder nicht lesbar. "
            "Datei entfernen, damit beim nächsten Start ein neuer Schlüssel entsteht "
            "(alle angemeldeten Sitzungen enden damit)."
        )
    except OSError as fehler:
        raise GeheimnisFehler(
            f"Schlüssel {pfad} lässt sich nicht anlegen: {fehler}. "
            "Ist das Datenverzeichnis eingehängt und beschreibbar?"
        ) from fehler

    with os.fdopen(fd, "w") as datei:
        datei.write(neuer)
    return neuer


def _lesen(pfad):
    try:
        with open(pfad, encoding="utf-8") as datei:
            return datei.read().strip()
    except FileNotFoundError:
        return ""
    except OSError as fehler:
        raise GeheimnisFehler(f"Schlüssel {pfad} nicht lesbar: {fehler}") from fehler

"""Zeitregeln des Termin-Banners: was gilt als bevorstehender Termin, und wie
wird der Vorlauf benannt.

Rein und ohne Datenbankzugriff — ``jetzt`` kommt von außen herein, damit die
Regeln als ``SimpleTestCase`` prüfbar bleiben.  Die Uhr wird ausschließlich in
der Randschicht gelesen (``intern/templatetags/termin_tags.py`` und
``config/context_processors.py``).
"""

from datetime import datetime, time

from django.db.models import Q
from django.utils.timesince import timeuntil

# Ein Termin ohne Uhrzeit steht als 00:00 in der Datenbank: das Formular setzt
# datetime.min.time(), wenn nichts eingegeben wurde (intern/forms.py).  Eine
# eigene Kennzeichnung am Modell gibt es nicht.
_OHNE_UHRZEIT = (0, 0)


def ist_ganztaegig(datum, datum_bis=None):
    """Ob der Termin ohne Uhrzeit angelegt wurde.

    Beide Enden müssen auf Mitternacht liegen: sobald irgendwo eine Uhrzeit
    steht, ist es ein zeitgebundener Termin.

    Geprüft wird ``(hour, minute)`` und nicht ``time() == time(0, 0)``, damit
    diese Funktion bei Altdaten mit Sekundenanteil genauso entscheidet wie die
    Datumszeile des Banners (``|time:"H:i" != "00:00"``) — die beiden Zeilen
    desselben Banners können sich so nicht widersprechen.
    """
    if (datum.hour, datum.minute) != _OHNE_UHRZEIT:
        return False
    if datum_bis is None:
        return True
    return (datum_bis.hour, datum_bis.minute) == _OHNE_UHRZEIT


def zeitraum_aus_eingabe(datum, uhrzeit, bis_datum, bis_uhrzeit, bisher=None):
    """Beginn und Ende eines Termins aus den vier Eingabefeldern.

    Datum und Uhrzeit sind an beiden Enden getrennt, und die Uhrzeit darf an
    beiden fehlen: ein Ende ohne Uhrzeit steht auf 00:00 und meint den ganzen
    letzten Tag (siehe ``ist_ganztaegig``). Eine Endzeit ohne Enddatum liegt am
    Tag des Beginns. Liefert ``(beginn, ende)``, ``ende`` ist ``None`` ohne
    Ende; ein Widerspruch wirft ``ValueError`` mit dem Text für das Formular.

    ``bisher`` ist ``(datum, datum_bis)`` des gespeicherten Termins: ein
    unveränderter Altbestand mit Uhrzeit an nur einem Ende bleibt speicherbar.
    """
    beginn = datetime.combine(datum, uhrzeit or time())
    if bis_datum is None and bis_uhrzeit is None:
        return beginn, None
    ende = datetime.combine(bis_datum or datum, bis_uhrzeit or time())
    if ende < beginn:
        raise ValueError("Das Ende liegt vor dem Beginn.")
    # Minutengenau: das Formular zeigt keine Sekunden, Altdaten tragen welche.
    if bisher and all(bisher) and (beginn, ende) == tuple(
        t.replace(second=0, microsecond=0) for t in bisher
    ):
        return beginn, ende
    # Ganztägig heißt: beide Enden ohne Uhrzeit. Hat nur eines eine, wäre der
    # Termin zeitgebunden und endete um Mitternacht vor seinem letzten Tag.
    ende_ohne_uhrzeit = (ende.hour, ende.minute) == _OHNE_UHRZEIT
    if not ist_ganztaegig(beginn) and ende_ohne_uhrzeit:
        raise ValueError(
            "Mit Uhrzeit am Beginn braucht auch das Ende eine — 00:00 heißt „ohne "
            "Uhrzeit“, für Mitternacht 23:59 eintragen."
        )
    if ist_ganztaegig(beginn) and not ende_ohne_uhrzeit:
        raise ValueError(
            "Ohne Uhrzeit am Beginn hat auch das Ende keine — oder am Beginn eine eintragen."
        )
    return beginn, ende


def countdown_text(datum, datum_bis, jetzt):
    """Der Vorlauf-Text des Banners.

    Ganztägige Termine werden in *Kalendertagen* gezählt: ein Termin am Freitag
    ist am Montag „4 Tage“ entfernt, nicht „3 Tage, 14 Stunden“ — die Stunden
    sind bei 00:00 ein Artefakt der Mitternachtsrechnung, keine Information.
    Aus demselben Grund heißt der laufende mehrtägige Termin „heute“ und nicht
    „vor zwei Tagen“.

    Termine mit Uhrzeit bleiben bei Djangos ``timeuntil``; dort sind die
    Stunden genau die Auskunft, die man sucht.
    """
    if not ist_ganztaegig(datum, datum_bis):
        return timeuntil(datum, jetzt)
    tage = (datum.date() - jetzt.date()).days
    if tage <= 0:
        return "heute"
    if tage == 1:
        return "morgen"
    # Geschütztes Leerzeichen wie in Djangos timeuntil, damit die Zahl im
    # Banner nicht von ihrer Einheit getrennt umbricht.
    return "%d Tage" % tage


def kommende_q(jetzt):
    """Filter für die Termine, die Banner und Offen-Zähler als bevorstehend führen.

    Neben dem echten Futur zählen dazu die ganztägigen Termine des heutigen
    Tages: ihr ``datum`` ist Mitternacht und damit formal vergangen, im
    Kalender der Mitglieder stehen sie aber noch bevor.  Ein mehrtägiger
    ganztägiger Termin bleibt bis zum Ende seines letzten Tages — dieselbe
    Lesart wie die Monatsansicht, deren Band auf ``datum_bis`` endet
    (``intern/views/termine.py``).

    Die Gleichheit im zweiten Zweig ist Absicht: ``datum__gte=tagesbeginn``
    würde auch die *zeitgebundene* Probe von heute 20:00 um 22:00 Uhr noch
    einblenden.  Eine Lücke um Mitternacht entsteht dadurch nicht — ist
    ``jetzt`` exakt 00:00, fängt der Gleichheitszweig den Termin.

    Die Uhrzeit-Bedingungen im dritten Zweig halten zeitgebundene
    Mehrtagestermine draußen; sie werden nur auf den wenigen Zeilen ausgewertet,
    die der Bereichsfilter davor übrig lässt.
    """
    tagesbeginn = datetime.combine(jetzt.date(), time.min)
    return (
        Q(datum__gt=jetzt)
        | Q(datum=tagesbeginn)
        | Q(
            datum__lt=tagesbeginn,
            datum_bis__gte=tagesbeginn,
            datum__hour=0,
            datum__minute=0,
            datum_bis__hour=0,
            datum_bis__minute=0,
        )
    )

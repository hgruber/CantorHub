"""Die Rollen einer Lied-Datei an **einer** Stelle.

Wie ``zusage.py``: Modell, Tabelle, Filter und Audit-Labels lesen hier, statt
die Rolle an einem Spaltennamen festzumachen. Ohne Datenbankzugriff, damit ein
``SimpleTestCase`` das Register prüfen kann.

Die Beschriftungen sind **wortgleich** zu halten: ``ChangeLog`` hält sie als
Schnappschuss, und ``views/aenderungen.py`` rekonstruiert alte Einträge daraus —
eine geänderte Beschriftung schriebe die Anzeige vergangener Änderungen um.
"""

from collections import namedtuple

# Schlüssel, Beschriftung, erlaubte Endungen — in Anzeigereihenfolge.
Rolle = namedtuple("Rolle", "key label endungen")

ROLLEN = (
    Rolle("original", "Original", (".mp3", ".m4a")),
    Rolle("aufnahme", "Aufnahme", (".mp3", ".m4a")),
    Rolle("notenblatt", "Notenblatt", (".pdf",)),
    Rolle("notensatz", "Notensatz", (".cap", ".msc", ".mscz")),
    Rolle("text", "Liedtext", (".odt",)),
)

# Schlüssel → Beschriftung.
LABELS = {rolle.key: rolle.label for rolle in ROLLEN}

# Die Schlüssel in Anzeigereihenfolge.
SCHLUESSEL = tuple(rolle.key for rolle in ROLLEN)


def label(key):
    """Schlüssel → Beschriftung; Unbekanntes bleibt, wie es gespeichert ist."""
    return LABELS.get(key, key)


def endungen():
    """Alle erlaubten Endungen, für Meldungen und Prüfungen."""
    return tuple(endung for rolle in ROLLEN for endung in rolle.endungen)


def rolle_fuer_endung(endung):
    """Welche Rolle eine Endung vorschlägt — ``None`` für Unbekanntes.

    ``.mp3`` steht bei ``original`` und ``aufnahme``; vorgeschlagen wird die
    erste Rolle (``original``). Die eigene Aufnahme erkennt das Portal am
    Namenspräfix, nicht an der Endung.
    """
    gesucht = (endung or "").lower()
    if gesucht and not gesucht.startswith("."):
        gesucht = f".{gesucht}"
    for rolle in ROLLEN:
        if gesucht in rolle.endungen:
            return rolle.key
    return None

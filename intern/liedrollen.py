"""Die Rollen einer Lied-Datei an **einer** Stelle.

Wie ``zusage.py``: Modell, Tabelle, Filter und Audit-Labels lesen hier, statt
die Rolle an einem Spaltennamen festzumachen. Ohne Datenbankzugriff, damit ein
``SimpleTestCase`` das Register prüfen kann.

Die Beschriftungen sind **wortgleich** zu halten: ``ChangeLog`` hält sie als
Schnappschuss, und ``views/aenderungen.py`` rekonstruiert alte Einträge daraus —
eine geänderte Beschriftung schriebe die Anzeige vergangener Änderungen um.
"""

from collections import namedtuple

# Schlüssel und Beschriftung — in Anzeigereihenfolge. Die Rolle vergibt die
# Medien-Karte von Hand; an Name oder Endung erkennt das Portal sie nicht.
Rolle = namedtuple("Rolle", "key label")

ROLLEN = (
    Rolle("original", "Original"),
    Rolle("aufnahme", "Aufnahme"),
    Rolle("notenblatt", "Notenblatt"),
    Rolle("notensatz", "Notensatz"),
    Rolle("text", "Liedtext"),
)

# Schlüssel → Beschriftung.
LABELS = {rolle.key: rolle.label for rolle in ROLLEN}

# Die Schlüssel in Anzeigereihenfolge.
SCHLUESSEL = tuple(rolle.key for rolle in ROLLEN)


def label(key):
    """Schlüssel → Beschriftung; Unbekanntes bleibt, wie es gespeichert ist."""
    return LABELS.get(key, key)


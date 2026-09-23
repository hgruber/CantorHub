"""Der Wertebereich der Termin-Antwort (``Zusage.option``) an **einer** Stelle.

Diese vier Werte und ihre Beschriftungen waren vorher an fünf Stellen gepflegt — im
Modell, in der Aufstellung, im Änderungsprotokoll, in der Tabellen-Spalte und im
Filter — und die Kopien waren bereits auseinandergelaufen. Ohne Datenbankzugriff,
damit ein ``SimpleTestCase`` sie prüfen kann.

Die Beschriftungen sind **wortgleich** zu den historischen Werten zu halten:
``str(Zusage)`` landet als Schnappschuss in ``ChangeLog.object_repr``, und
``views/aenderungen.py`` rekonstruiert alte Protokolleinträge daraus — eine
geänderte Beschriftung schriebe die Anzeige vergangener Änderungen um.
"""

# Der Wertebereich in Anzeigereihenfolge. "" heißt „noch nichts gesagt".
OPTIONEN = ("1", "2", "3", "")

# Option → Beschriftung (Langform).
OPTION_LABELS = {
    "1": "Zusage",
    "2": "Absage",
    "3": "Eventuell",
    "": "Keine Angabe",
}

# Option → Status-Kürzel der CSS-Klassen (``.aufst-*`` in der Aufstellung,
# ``.zusage-state-*`` auf der Terminseite). Alles Unbekannte ist „offen".
STATUS = {"1": "yes", "3": "maybe", "2": "no"}
STATUS_OFFEN = "na"

# Status-Kürzel → Kurzbeschriftung. Bewusst eine **andere Achse** als
# OPTION_LABELS: „Offen" (noch nichts gesagt) ist nicht „Keine Angabe".
STATUS_TITEL = {"yes": "Zusage", "maybe": "Eventuell", "na": "Offen", "no": "Absage"}

# Erlaubte Übergänge auf der Terminseite: von welcher Antwort aus darf auf welche
# gewechselt werden. ``views/termine.py`` liest das; die Ziele sind eine Teilmenge
# von OPTIONEN.
TRANSITIONS = {
    "": ["1", "2", "3"],
    "3": ["1", "2"],
    "1": [],
    "2": ["1", "3"],
}


def status_von(option):
    """Option → Status-Kürzel; alles Leere und Unbekannte ist „offen"."""
    return STATUS.get(option or "", STATUS_OFFEN)


def titel_von(option):
    """Option → Kurzbeschriftung für Aufstellung und Terminliste."""
    return STATUS_TITEL[status_von(option)]

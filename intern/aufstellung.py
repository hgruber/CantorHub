"""Die „Aufstellung" der Terminliste: ein Kästchen pro Mitglied, angeordnet wie der
Chor auf der Bühne steht.

Hinten Tenor | Bass, vorn Sopran | Alt, Chorleiter und Musiker abgesetzt. Innerhalb
einer Stimme stehen die Zusagen zur Mitte hin: die linke Stimme läuft von außen
Absage → Offen → Eventuell → Zusage, die rechte gespiegelt. So bildet sich ein grüner
Block um den Gang, und die Lücken sitzen an den Rändern.

Ohne Datenbankzugriff, damit es ein ``SimpleTestCase`` prüfen kann; die Abfragen
stehen in ``views.termine._aufstellungen_anhaengen``.
"""

# Zusage.option → Status-Kürzel der CSS-Klassen (.aufst-yes …)
_STATUS = {"1": "yes", "3": "maybe", "2": "no"}
_TITEL = {"yes": "Zusage", "maybe": "Eventuell", "na": "Offen", "no": "Absage"}

# Reihenfolge von der Mitte nach außen
_VON_DER_MITTE = ["yes", "maybe", "na", "no"]

# Stimme → (Reihe, Seite); Seite 0 steht links vom Gang
_PLATZ = {"T": ("hinten", 0), "B": ("hinten", 1), "S": ("vorn", 0), "A": ("vorn", 1)}
_EXTRA = ["C", "M"]


def aufstellung(mitglieder, zusagen, ich_id=None):
    """Baut die Aufstellung eines Termins.

    ``mitglieder``: Folge von ``(id, vorname, nachname, stimme)``, bereits nach Name
    sortiert. ``zusagen``: Folge von ``(person_id, option)`` in id-Reihenfolge — gibt
    es mehrere, gewinnt die letzte, wie auf der Terminseite.

    Mitglieder ohne Stimme (``N``) werden weder platziert noch gezählt, damit Chips
    und Kästchen immer dieselben Menschen meinen.
    """
    option_von = dict(zusagen)

    # je Stimme die Kästchen, gruppiert nach Status
    stimmen = {s: {st: [] for st in _VON_DER_MITTE} for s in [*_PLATZ, *_EXTRA]}
    for pid, vorname, nachname, stimme in mitglieder:
        if stimme not in stimmen:
            continue
        status = _STATUS.get(option_von.get(pid, ""), "na")
        stimmen[stimme][status].append({
            "status": status,
            "titel": f"{vorname} {nachname} – {_TITEL[status]}",
            "ich": pid == ich_id,
        })

    def von_der_mitte(stimme):
        return [k for st in _VON_DER_MITTE for k in stimmen[stimme][st]]

    reihen = {"hinten": [[], []], "vorn": [[], []]}
    for stimme, (reihe, seite) in _PLATZ.items():
        kaestchen = von_der_mitte(stimme)
        # links vom Gang liegt die Mitte am rechten Ende
        reihen[reihe][seite] = kaestchen[::-1] if seite == 0 else kaestchen

    def anzahl(status, auswahl=stimmen):
        return sum(len(stimmen[s][status]) for s in auswahl)

    zahlen = {
        "S": anzahl("yes", ["S"]),
        "A": anzahl("yes", ["A"]),
        "T": anzahl("yes", ["T"]),
        "B": anzahl("yes", ["B"]),
        "zusagen": anzahl("yes"),
        "vielleicht": anzahl("maybe"),
        "offen": anzahl("na"),
        "absagen": anzahl("no"),
    }
    return {
        "hinten": reihen["hinten"],
        "vorn": reihen["vorn"],
        "extra": [k for s in _EXTRA for k in von_der_mitte(s)],
        "zahlen": zahlen,
        "label": (
            f"{zahlen['zusagen']} Zusagen, {zahlen['vielleicht']} Eventuell, "
            f"{zahlen['offen']} offen, {zahlen['absagen']} Absagen"
        ),
    }

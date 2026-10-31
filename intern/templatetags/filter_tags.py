from django import template

from intern.filterbau import hat_schalter, kodiere

register = template.Library()

def _zeile(baukasten, bedingung):
    """Eine Baukasten-Zeile fürs Template.

    ``werte_roh`` sind die **rohen** Werte für die Vorauswahl -- aus dem
    zusammengesetzten ``f``-String ließe sich das im Template nicht rekonstruieren.
    ``wert`` ist der kodierte Wert für den versteckten ``<input name="f">``.

    Die Auswahllisten füllt das Skript aus dem mitgegebenen Bündel: so steht jede
    Liste einmal in der Seite statt in jeder Zeile und jeder Vorlage.
    """
    feld = baukasten.feld(bedingung.feld)
    nicht = baukasten.ist_verneinend(bedingung)
    return {
        "verbindung": bedingung.verbindung,
        "feld": bedingung.feld,
        "operator": bedingung.operator,
        "art": feld.art,
        "wert": kodiere(bedingung),
        "werte_roh": ",".join(bedingung.werte),
        "variante": "exclude" if nicht else None,
        "wert1": bedingung.werte[0] if bedingung.werte else "",
        "wert2": bedingung.werte[1] if len(bedingung.werte) > 1 else "",
        # Bedienung des Operators: bei einem Ja/Nein-Paar der Drei-Zustand-Schalter,
        # sonst die Auswahlliste. Das versteckte <select> gibt es immer -- das Skript
        # liest es unbedingt, und die Pille setzt seinen Wert.
        "schalter": hat_schalter(feld),
        # Serverseitig ist eine Zeile immer ein- oder ausgeschaltet: „egal" entsteht
        # erst im Browser, und eine stille Zeile wird gar nicht erst gesendet.
        "schalter_stellung": "nein" if nicht else "ja",
        "schalter_offset": "0px" if nicht else "28px",
        "operatoren": [
            {"key": k, "label": l, "nicht": n} for k, l, n, _s in feld.operatoren
        ],
        "eintraege": [],
        **baukasten.wert_texte(feld),
    }


@register.inclusion_tag("filter_chips.html")
def filter_chips(kette):
    """Die Kette des Baukastens als Chips der Titelleiste, gedeckelt mit „+n"."""
    chips = list(kette["elemente"])
    if kette["versteckt"]:
        chips.append({
            "chip_type": "mehr",
            "label": "+%d" % kette["versteckt"],
            "titel": kette["titel"],
        })
    return {"chips": chips}


@register.inclusion_tag("_filter_baukasten.html")
def filter_baukasten(bedingungen, request, baukasten, kann_verwalten=False):
    """Der Zeilen-Editor des Filters: bestehende Bedingungen plus die Vorlagen.

    Das Feld-Dropdown zeigt nur die erlaubten Felder -- das ist die erste Hälfte des
    Rechte-Gates, die zweite sitzt in ``baukasten.lese_bedingungen``. Die leeren
    Zeilen kommen aus dem Register, damit ein gesperrtes Feld niemals die Vorlage
    stellt.
    """
    felder = baukasten.felder_kontext(kann_verwalten)
    leer = baukasten.bedingung_fuer_feld(felder[0]["key"], kann_verwalten)
    return {
        "zeilen": [_zeile(baukasten, b) for b in bedingungen if not baukasten.ist_fest(b)],
        # Die Ja/Nein-Felder ohne Wert: feste Schalter unter der Kette, immer da.
        "feste": baukasten.feste_kontext(bedingungen, kann_verwalten),
        "felder": felder,
        "leerzeile": _zeile(baukasten, leer),
        # Eine Werte-Vorlage je Feld, nicht je Art: Solist und Dirigent teilen die Art
        # „mehrfach", aber nicht Einträge und Beschriftungen.
        "vorlagen": [
            _zeile(baukasten, baukasten.bedingung_fuer_feld(feld["key"], kann_verwalten))
            for feld in felder
        ],
        "optionen": baukasten.optionen(),
        # Traegt die Adresse einen Marker, muss das Formular ihn weiterschicken.
        "traeger": baukasten.traeger_felder(request.GET),
    }

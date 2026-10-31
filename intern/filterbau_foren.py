"""Das Feld-Register der Forenliste.

Die Kategorie ist ein Textfeld, keine Auswahl: eine Auswahlliste kaeme ohne
Betrachter zustande und nennte auch die Kategorien der Foren, die er nicht lesen
darf.

Die Volltextsuche ueber die Mitteilungen (``?q=``) ist nicht Teil davon: sie hat
ihre eigene Ergebnisseite und laeuft vor dem Baukasten (``forum_list``). Hier wird
nur die Liste der Foren selbst gefiltert.
"""

from django.db.models import Q

from .filterbau import Baukasten, datum_feld, paar, schalter_feld, text_feld


def _ungelesen_q(operator, werte):
    # ``ungelesen`` annotiert ``ForumQuerySet.mit_ungelesen``.
    treffer = Q(ungelesen__gt=0)
    return ~treffer if operator == "nein" else treffer


FELDER = {
    "kategorie": text_feld("kategorie", "Kategorie"),
    "thema": text_feld("thema", "Thema"),
    "zugriff": datum_feld("zugriff", "Letzter Beitrag", mit_uhrzeit=True),
    "ungelesen": schalter_feld(
        "ungelesen", "Ungelesen",
        paar("ungelesen", "gelesen", "hat ungelesene Beiträge", "hat keine ungelesenen Beiträge"),
        _ungelesen_q,
    ),
}

FELD_REIHENFOLGE = ("kategorie", "thema", "zugriff", "ungelesen")


FOREN = Baukasten(felder=FELDER, reihenfolge=FELD_REIHENFOLGE)

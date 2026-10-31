"""Das Feld-Register der Artikelliste.

Gefiltert wird nur, was die Ansicht schon freigegeben hat: ``article_list`` nimmt
die Artikel mit gesperrtem Lesezugriff **vor** dem Baukasten heraus. Sonst verriete
eine Suche ueber den Text die Existenz eines Artikels, den die Liste verschweigt.
Jede Bedingung gilt der neuesten Fassung eines Artikels.
"""

from .filterbau import Baukasten, Feld, datum_feld, mehrfach_texte, namens_wert, text_feld, wahl_q

_AUTOR = (
    ("in", "ist", False, "zuletzt bearbeitet von {w}"),
    ("nicht-in", "ist nicht", True, "nicht zuletzt bearbeitet von {w}"),
)

FELDER = {
    "name": text_feld("name", "Name"),
    "text": text_feld("text", "Text"),
    "autor": Feld(
        key="autor", label="Letzter Autor", art="mehrfach", operatoren=_AUTOR,
        q=wahl_q("autor"), werte_text=namens_wert,
        texte=mehrfach_texte("Autor", "Autoren"),
    ),
    "datum": datum_feld("datum", "Zuletzt bearbeitet", mit_uhrzeit=True),
}

FELD_REIHENFOLGE = ("name", "text", "autor", "datum")


def autoren():
    """Wer eine Artikelfassung geschrieben hat, als Kennung -> Name."""
    from .models import User

    return {
        str(u.pk): str(u)
        for u in User.objects.filter(artikel__isnull=False).distinct()
        .order_by("last_name", "first_name")
    }


def _eintraege(feld_key):
    if feld_key == "autor":
        return [{"wert": pk, "label": name} for pk, name in autoren().items()]
    return []


ARTIKEL = Baukasten(felder=FELDER, reihenfolge=FELD_REIHENFOLGE, eintraege=_eintraege)

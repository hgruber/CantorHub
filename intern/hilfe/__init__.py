"""Die Hilfe-Artikel, die jede neue Installation mitbringt.

Die Texte liegen als Wiki-Markup unter ``artikel/``, ihre Bilder unter
``bilder/``. Die Ersteinrichtung (``intern/einrichtung.py``) legt sie an; eine
bestehende Installation holt sie mit ``manage.py hilfe_anlegen`` nach. Beides
überschreibt nichts: ein Artikel, den es schon gibt, bleibt, wie er ist, und ein
gleichnamiges Bild wird nicht ersetzt.

Was eine Installation unterscheidet — Adresse, Chat-Domain, Benutzername des
Lesers —, steht in den Texten als Platzhalter (``intern/wiki_platzhalter.py``)
und wird erst beim Anzeigen ersetzt.

Oben die reinen Entscheidungen (``SimpleTestCase``), darunter der DB-Teil.
"""

import logging
from pathlib import Path

from .. import wiki_platzhalter

logger = logging.getLogger(__name__)

VERZEICHNIS = Path(__file__).resolve().parent

# Artikelname → Datei unter artikel/, in der Reihenfolge der Übersicht.
ARTIKEL = {
    "Hilfe": "hilfe.txt",
    "Hilfe:Erste Schritte": "erste-schritte.txt",
    "Hilfe:Mein Profil": "mein-profil.txt",
    "Hilfe:Termine": "termine.txt",
    "Hilfe:Forum": "forum.txt",
    "Hilfe:Repertoire": "repertoire.txt",
    "Hilfe:Mitglieder": "mitglieder.txt",
    "Hilfe:Dateien": "dateien.txt",
    "Hilfe:Wiki": "wiki.txt",
    "Hilfe:Termine aufs Telefon": "termine-aufs-telefon.txt",
    "Hilfe:Kalender abonnieren": "kalender-abonnieren.txt",
    "Hilfe:Kontakte aufs Telefon": "kontakte-aufs-telefon.txt",
    "Hilfe:Chat auf dem Telefon": "chat-auf-dem-telefon.txt",
    "Hilfe:Betrieb und Kosten": "betrieb-und-kosten.txt",
}

# Bearbeiten dürfen nur diese Gruppen — eine Anleitung, die ein Neuling beim
# Ausprobieren zerlegt, hilft niemandem. Lesen bleibt für alle offen.
SCHREIBGRUPPEN = ("Webmaster", "Vorstand")

KOMMENTAR = "Hilfe-Artikel der Ersteinrichtung"

# Die Stelle in wiki.txt, an der die Liste der Platzhalter entsteht.
PLATZHALTER_MARKE = "<<PLATZHALTER>>"


def platzhalter_liste():
    """Die Platzhalter als Wiki-Codezeilen — eingerückt, also unersetzt."""
    return "\n".join(
        f" {{{name}}} — {text}" for name, text in wiki_platzhalter.BESCHREIBUNG.items()
    )


def text(name):
    """Der Text eines Hilfe-Artikels, fertig zum Speichern."""
    roh = (VERZEICHNIS / "artikel" / ARTIKEL[name]).read_text(encoding="utf-8")
    return roh.replace(PLATZHALTER_MARKE, platzhalter_liste())


def bilder():
    """Die Bilddateien unter bilder/, nach Namen sortiert."""
    return sorted((VERZEICHNIS / "bilder").glob("*.png"))


# ── DB-Teil ───────────────────────────────────────────────────────────────────

def anlegen(nutzer, jetzt):
    """Fehlende Hilfe-Artikel und -Bilder anlegen; zurück kommen die neuen Artikelnamen."""
    from django.contrib.auth.models import Group
    from django.core.files.base import ContentFile

    from .. import dateiablage, folders
    from ..models import Artikel, ArtikelPermission

    ordner = folders.artikel()
    if ordner is not None:
        for pfad in bilder():
            if dateiablage.gleichnamige(ordner, pfad.name) is None:
                dateiablage.systemablage_inhalt(
                    ContentFile(pfad.read_bytes(), name=pfad.name), ordner, pfad.name,
                    nutzer, mime="image/png",
                )
    else:
        logger.warning("Hilfe-Artikel: Ordner für Wiki-Anhänge fehlt, Bilder übersprungen")

    gruppen = list(Group.objects.filter(name__in=SCHREIBGRUPPEN))
    neu = []
    for name in ARTIKEL:
        if Artikel.objects.filter(name=name).exists():
            continue
        Artikel.objects.create(
            name=name, version=1, datum=jetzt, autor=nutzer,
            kommentar=KOMMENTAR, text=text(name),
        )
        if not ArtikelPermission.objects.filter(artikel_name=name).exists():
            for gruppe in gruppen:
                ArtikelPermission.objects.create(
                    artikel_name=name, group=gruppe, can_edit=True
                )
        neu.append(name)
    return neu

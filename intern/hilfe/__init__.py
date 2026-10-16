"""Die Hilfe-Artikel, die jede neue Installation mitbringt.

Die Texte liegen als Wiki-Markup unter ``artikel/``, ihre Bilder unter
``bilder/``. Die Ersteinrichtung (``intern/einrichtung.py``) legt sie an; eine
bestehende Installation holt sie mit ``manage.py hilfe_anlegen`` nach. Beides
überschreibt nichts: ein Artikel, den es schon gibt, bleibt, wie er ist, und ein
gleichnamiges Bild wird nicht ersetzt. Erst ``hilfe_anlegen --force`` bringt den
mitgelieferten Stand auch über vorhandene Artikel — als neue Version, und ein
Bild als neue Fassung; die bisherigen bleiben in der Geschichte.

Jede Seite ``Hilfe:…`` bekommt oben und unten eine Zeile mit der vorherigen
Seite, der Übersicht und der folgenden Seite — in der Reihenfolge von
``ARTIKEL``, beim Erzeugen des Texts eingesetzt, nicht in den Dateien gepflegt.

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
KOMMENTAR_ERNEUERT = "Hilfe-Artikel auf den mitgelieferten Stand gebracht"

# Die Stelle in wiki.txt, an der die Liste der Platzhalter entsteht.
PLATZHALTER_MARKE = "<<PLATZHALTER>>"


def platzhalter_liste():
    """Die Platzhalter als Wiki-Codezeilen — eingerückt, also unersetzt."""
    return "\n".join(
        f" {{{name}}} — {text}" for name, text in wiki_platzhalter.BESCHREIBUNG.items()
    )


def _verweis(name):
    return f"[[{name}|{name.removeprefix('Hilfe:')}]]"


def navigation(name):
    """Die Zeile „← vorherige · Übersicht · folgende →“ einer Seite ``Hilfe:…``."""
    seiten = [n for n in ARTIKEL if n.startswith("Hilfe:")]
    i = seiten.index(name)
    teile = []
    if i > 0:
        teile.append(f"← {_verweis(seiten[i - 1])}")
    teile.append("[[Hilfe|Übersicht]]")
    if i + 1 < len(seiten):
        teile.append(f"{_verweis(seiten[i + 1])} →")
    return " · ".join(teile)


def text(name):
    """Der Text eines Hilfe-Artikels, fertig zum Speichern."""
    roh = (VERZEICHNIS / "artikel" / ARTIKEL[name]).read_text(encoding="utf-8")
    roh = roh.replace(PLATZHALTER_MARKE, platzhalter_liste())
    if not name.startswith("Hilfe:"):
        return roh
    zeile = navigation(name)
    return f"{zeile}\n{roh.rstrip()}\n\n{zeile}\n"


def bilder():
    """Die Bilddateien unter bilder/, nach Namen sortiert."""
    return sorted((VERZEICHNIS / "bilder").glob("*.png"))


# ── DB-Teil ───────────────────────────────────────────────────────────────────

def anlegen(nutzer, jetzt, erneuern=False):
    """Fehlende Hilfe-Artikel und -Bilder anlegen; zurück kommen die neuen Artikelnamen.

    Mit ``erneuern`` bekommt ein vorhandener Artikel, dessen neueste Version
    vom mitgelieferten Text abweicht, diesen als nächste Version, und ein
    vorhandenes Bild eine neue Fassung (bei gleichem Inhalt bleibt es, wie es
    ist). Dann kommen auch die erneuerten Namen zurück."""
    from django.contrib.auth.models import Group
    from django.core.files.base import ContentFile

    from .. import dateiablage, folders
    from ..models import Artikel, ArtikelPermission

    ordner = folders.artikel()
    if ordner is not None:
        for pfad in bilder():
            if erneuern or dateiablage.gleichnamige(ordner, pfad.name) is None:
                dateiablage.systemablage_inhalt(
                    ContentFile(pfad.read_bytes(), name=pfad.name), ordner, pfad.name,
                    nutzer, mime="image/png",
                )
    else:
        logger.warning("Hilfe-Artikel: Ordner für Wiki-Anhänge fehlt, Bilder übersprungen")

    gruppen = list(Group.objects.filter(name__in=SCHREIBGRUPPEN))
    neu = []
    for name in ARTIKEL:
        letzte = Artikel.objects.filter(name=name).order_by("-version").first()
        if letzte is not None:
            if erneuern and letzte.text != text(name):
                Artikel.objects.create(
                    name=name, version=letzte.version + 1, datum=jetzt, autor=nutzer,
                    kommentar=KOMMENTAR_ERNEUERT, text=text(name),
                )
                neu.append(name)
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

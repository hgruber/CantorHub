"""Avatare: Fallback-Dateien und Vorschaubilder.

Herausgezogen aus ``models.py`` — die beiden Modelle, die Avatare zeigen
(``User``, ``Mitteilung``), brauchen dieselben Helfer wie die Tabellen- und
Ansichtsschicht. Ohne Modelle zu importieren, aber mit denselben **funktionslokalen**
Importen: ``views/files.py`` importiert seinerseits aus ``models``, ein Import auf
Modulebene wäre also ein Kreis.
"""

from types import SimpleNamespace

# Kantenlaenge des Avatar-Vorschaubilds. Angezeigt werden 38 Pixel im Forum und
# 40 in der Mitgliederliste; das Doppelte deckt Bildschirme mit hoher
# Punktdichte ab. Eine Groesse fuer beide Stellen, damit nicht zwei fast gleiche
# Vorschaubilder je Avatar entstehen.
AVATAR_VORSCHAU = (76, 76)


def fallback_avatar_datei(original_filename):
    """Die per ``import_files`` (django-filer) importierte Fallback-Datei
    (z. B. ``kein_photo.png`` / ``bot.png``), oder ``None``.

    Je Anfrage einmal ermittelt: im Forum braucht sie jede Nachricht des
    XMPP-Bots und jede Nachricht ohne Absenderbild."""
    from filer.models import File

    from .anfragespeicher import gemerkt

    return gemerkt(
        ("fallback_avatar", original_filename),
        lambda: File.objects.filter(original_filename=original_filename).first(),
    )


def vorschau_url(pfad, groesse=AVATAR_VORSCHAU, oeffentlich=True):
    """Quadratisches Vorschaubild zu einem Speicherpfad — ohne die Dateizeile zu laden.

    Eine Liste braucht von einem Avatar nur die URL. Der Weg ueber ``File``
    kostet dafuer **zwei** Abfragen je Zeile: die Dateizeile und, weil filer
    polymorph speichert, die zugehoerige ``Image``-Zeile. Gemessen an der
    Mitgliederliste mit eingeblendeter Avatar-Spalte: 63 Abfragen und 52,5 ms
    ueber die Objekte, 1 Abfrage und 8,8 ms ueber die Pfade — bei denselben URLs.

    Der Ablageort muss filers eigener sein (``filer_public_thumbnails/``), sonst
    entstehen neben den vorhandenen Vorschaubildern zweite. Deshalb wird das
    Dateiobjekt des Feldes gebaut statt ``get_thumbnailer(pfad)`` benutzt: nur
    ``is_public`` entscheidet ueber Ablage und Speicher, und genau das gibt der
    Platzhalter mit.

    Schlaegt das Erzeugen fehl (kein Bild, fehlende Datei), bleibt es beim
    Original — ein fehlendes Bild waere schlimmer als ein zu grosses.
    """
    if not pfad:
        return ""
    from filer.models import File

    from .views.files import datei_url

    feld = File._meta.get_field("file")
    try:
        datei = feld.attr_class(SimpleNamespace(is_public=oeffentlich), feld, pfad)
        return datei.get_thumbnail(
            {"size": groesse, "crop": True, "quality": 85}
        ).url
    except Exception:
        return datei_url(pfad)


def avatar_vorschau_url(datei):
    """Wie ``vorschau_url``, fuer eine bereits geladene ``File``-Zeile."""
    if not datei:
        return ""
    return vorschau_url(
        datei.file.name, oeffentlich=getattr(datei, "is_public", True)
    )

"""Tags für die öffentliche Startseite (Vorlagen-Engine ``startseite``).

Die Seite und ihre Dateien kommen aus ``settings.STARTSEITE_WURZELN``: erst die
eigene Seite der Installation unter ``DATEN/startseite``, dann die mitgelieferte
unter ``intern/startseite``. Bilder, CSS und Schriften liegen dort jeweils in
``statisch/`` und werden unter ``/startseite/…`` ausgeliefert — im Container von
nginx (gleiche Reihenfolge), in der Entwicklung von ``views.startseite_statisch``.
"""

from pathlib import Path
from urllib.parse import quote

from django import template
from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.utils._os import safe_join
from django.utils.html import format_html

register = template.Library()

URL_PRAEFIX = "/startseite/"


def finde_statisch(pfad):
    """Die Datei hinter ``/startseite/<pfad>``: erster Treffer in den Wurzeln.

    ``None``, wenn es sie nirgends gibt oder der Pfad aus ``statisch/`` hinausführt.
    """
    for wurzel in settings.STARTSEITE_WURZELN:
        try:
            datei = Path(safe_join(wurzel / "statisch", pfad))
        except SuspiciousFileOperation:
            return None
        if datei.is_file():
            return datei
    return None


@register.simple_tag
def startseite_datei(pfad):
    """URL einer Datei aus ``statisch/``, mit Änderungszeit als Cache-Brecher.

    ``{% startseite_datei "img/chor-800.jpg" %}`` → ``/startseite/img/chor-800.jpg?v=…``.
    Eine fehlende Datei bekommt ihre URL ohne ``?v=`` — der Browser meldet dann
    die 404, statt dass die Seite beim Rendern abbricht.
    """
    url = URL_PRAEFIX + quote(pfad)
    datei = finde_statisch(pfad)
    if datei is None:
        return url
    return f"{url}?v={int(datei.stat().st_mtime)}"


@register.simple_tag(takes_context=True)
def markenfarbe(context):
    """Setzt ``--brand`` auf ``BRAND_FARBE`` — wie ``_brand_boot.html`` im Portal.

    Muss nach dem Stylesheet-Link stehen, damit die Regel in der Kaskade gewinnt.
    """
    return format_html(
        "<style>:root{{--brand:{};}}</style>",
        context.get("brand_farbe") or "#c14468",
    )

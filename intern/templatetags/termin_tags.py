import re

from django import template
from django.utils.safestring import mark_safe
from django.utils.timezone import now

from intern.terminzeit import countdown_text, ist_ganztaegig

register = template.Library()

# Nachbearbeitung der Altdaten aus dem PHP-Portal (``Termin.extern``). Sie läuft
# nur beim Rendern: der gespeicherte Wert und damit das Änderungsprotokoll
# bleiben roh.
_STIL = re.compile(r"""\s+style\s*=\s*("[^"]*"|'[^']*')""", re.IGNORECASE)
_UEBERSCHRIFT_AUF = re.compile(r"<h[1-3]\b[^>]*>", re.IGNORECASE)
_UEBERSCHRIFT_ZU = re.compile(r"</h[1-3]\s*>", re.IGNORECASE)
_SCHRIFT_AUF = re.compile(r"<font\b[^>]*>", re.IGNORECASE)
_SCHRIFT_ZU = re.compile(r"</font\s*>", re.IGNORECASE)


@register.filter
def extern_html(text):
    """Ankündigungstext als HTML: ``{{ termin.extern|extern_html }}``.

    Das Feld ist eine Altdaten-Spalte des PHP-Portals, sein Inhalt ist als HTML
    gedacht (``<a href=…>``, ``<br>``). Vier Nacharbeiten, und ein Leerwert fällt
    durch: reiner Leerraum ergibt ``""``. Daran hängen die Karte „Extern“ auf der
    Terminseite und der Adressblock der Startseite — beide erscheinen dadurch
    nicht als leerer Kasten. Die *Auswahl* der Termine auf der Startseite prüft
    dagegen das rohe Feld (``intern/views/auth.py``), damit ein einzelnes
    Leerzeichen einen Auftritt listet, ohne einen Text zu erfinden.

    1. ``\\r\\n``, ``\\r`` und ``\\n`` werden zu ``<br>``. 55 der 74 gefüllten
       Zeilen sind zeilenweise Adressblöcke; ohne das läuft alles in einer Zeile
       zusammen. Erst normalisieren, dann ersetzen — sonst entsteht ``\\r<br>``.
    2. ``style="…"`` fliegt raus: drei Zeilen tragen eines, darunter
       ``color:#bacee6`` (1,5:1 auf dem Cremeband, unlesbar) und ein
       ``font-size:14px``, das die ``rem``-Skala umgeht.
    3. ``<h1>``–``<h3>`` werden zu ``<strong>``: 55 Zeilen beginnen mit einem
       ``<h1>``, das in Browser-Größe 2em die Gliederung der Startseite und die
       Terminüberschrift erschlägt.
    4. ``<font>`` wird zu ``<span>`` (zwei Zeilen, in HTML5 ungültig).

    **Kein Sanitizer.** Markup, das nicht in den vier Mustern steht, geht roh
    durch. Das ist vertretbar, weil ``extern`` nur über ``termin_edit``
    (``intern.change_termin``) und den Admin schreibbar ist — siehe
    „Trust boundary“ in ``docs/technical-debt.md``.
    """
    if text is None:
        return ""
    text = str(text)
    if not text.strip():
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _STIL.sub("", text)
    text = _UEBERSCHRIFT_AUF.sub("<strong>", text)
    text = _UEBERSCHRIFT_ZU.sub("</strong>", text)
    text = _SCHRIFT_AUF.sub("<span>", text)
    text = _SCHRIFT_ZU.sub("</span>", text)
    return mark_safe(text.replace("\n", "<br>"))


@register.filter
def countdown(termin, jetzt=None):
    """Vorlauf-Text für das Termin-Banner: ``{{ banner_termin|countdown }}``.

    Die dünne Randschicht um ``intern.terminzeit`` — hier und nur hier wird die
    Uhr gelesen, damit die Regeln selbst ohne Datenbank und ohne Zeitbezug
    testbar bleiben.  ``jetzt`` ist deshalb nur für die Tests da.

    Bewusst ein Filter und keine im Context-Processor vorberechnete Variable:
    ``termin_zusage`` rendert das Banner nach einer Zusage per htmx neu und
    setzt ``banner_termin`` selbst.  Eine vorberechnete Variable käme dort
    weiterhin vom Context-Processor und beschriebe den *anderen* Termin.
    """
    if termin is None:
        return ""
    return countdown_text(termin.datum, termin.datum_bis, jetzt or now())


@register.filter
def zeitraum_bis(termin):
    """Das Enddatum eines *mehrtägigen ganztägigen* Termins — sonst ``None``.

    Die Datumszeile des Banners zeigt damit den ganzen Zeitraum.  Ohne das
    stünde bei einer laufenden Chorfreizeit oben „heute“ und darunter allein
    das bereits vergangene Startdatum — das liest sich wie ein Fehler.
    """
    if termin is None:
        return None
    bis = termin.datum_bis
    if bis is None or not ist_ganztaegig(termin.datum, bis):
        return None
    return bis if bis.date() > termin.datum.date() else None

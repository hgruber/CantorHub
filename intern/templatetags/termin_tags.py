from django import template
from django.utils.timezone import now

from intern.terminzeit import countdown_text, ist_ganztaegig

register = template.Library()


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

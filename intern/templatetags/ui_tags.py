from django import template
from django.apps import apps
from django.utils.safestring import mark_safe

from intern import symbole

register = template.Library()


@register.simple_tag
def symbol(name, **attribute):
    """Ein Symbol aus ``intern/symbole.py``: ``{% symbol "trichter" class="toolicon" %}``.

    Weitere Attribute wie ``width=14`` oder ``stroke_width="2.5"`` gehen ans
    ``<svg>``. Ein falscher Name soll laut scheitern, deshalb kein try/except.
    """
    return mark_safe(symbole.svg(name, **attribute))


@register.inclusion_tag("_hilfe_icon.html")
def hilfe(ziel, label=None):
    """Info-Icon, dessen Tooltip den help_text eines Model-Felds zeigt.

    ziel  — entweder ein BoundField (im Formular: {% hilfe form.repertoire %})
            oder "Model.feld" als String (auf reinen Anzeigeseiten:
            {% hilfe "Termin.repertoire" %})
    label — Text für das aria-label; ohne Angabe der Label-/Feldname

    Die Erklärungstexte stehen ausschließlich als help_text am Model — nie im
    Template. Ein falscher Feldname soll laut scheitern, deshalb kein try/except.
    """
    text = getattr(ziel, "help_text", None)
    if text is None:
        modell, _, feldname = str(ziel).partition(".")
        feld = apps.get_model("intern", modell)._meta.get_field(feldname)
        text = feld.help_text
        label = label if label is not None else feld.verbose_name
    else:
        label = label if label is not None else ziel.label
    return {"text": text, "label": label}

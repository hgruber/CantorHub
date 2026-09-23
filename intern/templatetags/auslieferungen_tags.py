from django import template
from django.utils.safestring import mark_safe

from intern.auslieferungen import auszeichnen

register = template.Library()


@register.filter
def auszeichnung(absatz):
    """Inline-Markup eines Absatzes: ``{{ absatz|auszeichnung }}``.

    ``mark_safe`` ist hier vertretbar, obwohl ``replacements.apply_replacements``
    es nicht setzt: die Eingabe ist ein Rohtext-Absatz aus ``CHANGELOG.md``, und
    ``auszeichnen`` escapet ihn als erste Operation. Bei ``apply_replacements``
    darf die Eingabe dagegen schon Markup enthalten (eingesetzte Bausteine),
    dort wäre ``mark_safe`` falsch. ``termin_tags.extern_html`` ist dasselbe
    Muster für fremdes Markup.
    """
    return mark_safe(auszeichnen(absatz))

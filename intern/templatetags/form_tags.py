from django import template

register = template.Library()


@register.inclusion_tag("_form_field.html", takes_context=True)
def form_field(context, field, label=None, req=False, privacy=None, hilfe=False):
    """Standard-Formularfeld: form-group mit Label, Widget und Fehleranzeige.

    label   — sichtbarer Label-Text; ohne Angabe das Label des Form-Felds
    req     — Pflichtfeld-Stern anzeigen (nur wenn das Feld auch required ist)
    privacy — priv_*-Checkbox-Feld; gerendert nur bei can_set_privacy im Kontext
    hilfe   — help_text des Felds ausgeben (opt-in, damit Django-Default-Hilfetexte
              wie der von username nicht ungewollt erscheinen)
    """
    return {
        "field": field,
        "label": label if label is not None else field.label,
        "req": req,
        "privacy": privacy,
        "can_set_privacy": context.get("can_set_privacy", False),
        "hilfe": hilfe,
    }

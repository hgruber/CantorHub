from django import template
from django_filters import ModelChoiceFilter, ModelMultipleChoiceFilter
from django.forms import NullBooleanField

from intern.filterbau import hat_schalter, kodiere

register = template.Library()

_NO_FILTER_VALUES = frozenset(("", "unknown", "1"))


def _zeile(baukasten, bedingung):
    """Eine Baukasten-Zeile fürs Template.

    ``werte_roh`` sind die **rohen** Werte für die Vorauswahl -- aus dem
    zusammengesetzten ``f``-String ließe sich das im Template nicht rekonstruieren.
    ``wert`` ist der kodierte Wert für den versteckten ``<input name="f">``.

    Die Auswahllisten füllt das Skript aus dem mitgegebenen Bündel: so steht jede
    Liste einmal in der Seite statt in jeder Zeile und jeder Vorlage.
    """
    feld = baukasten.feld(bedingung.feld)
    nicht = baukasten.ist_verneinend(bedingung)
    return {
        "verbindung": bedingung.verbindung,
        "feld": bedingung.feld,
        "operator": bedingung.operator,
        "art": feld.art,
        "wert": kodiere(bedingung),
        "werte_roh": ",".join(bedingung.werte),
        "variante": "exclude" if nicht else None,
        "wert1": bedingung.werte[0] if bedingung.werte else "",
        "wert2": bedingung.werte[1] if len(bedingung.werte) > 1 else "",
        # Bedienung des Operators: bei einem Ja/Nein-Paar der Drei-Zustand-Schalter,
        # sonst die Auswahlliste. Das versteckte <select> gibt es immer -- das Skript
        # liest es unbedingt, und die Pille setzt seinen Wert.
        "schalter": hat_schalter(feld),
        # Serverseitig ist eine Zeile immer ein- oder ausgeschaltet: „egal" entsteht
        # erst im Browser, und eine stille Zeile wird gar nicht erst gesendet.
        "schalter_stellung": "nein" if nicht else "ja",
        "schalter_offset": "0px" if nicht else "28px",
        "operatoren": [
            {"key": k, "label": l, "nicht": n} for k, l, n, _s in feld.operatoren
        ],
        "eintraege": [],
        **baukasten.wert_texte(feld),
    }


@register.inclusion_tag("filter_chips.html")
def filter_chips(filter_obj, request, skip=None, kette=None):
    chips = list(kette["elemente"]) if kette else []
    if kette and kette["versteckt"]:
        chips.append({
            "chip_type": "mehr",
            "label": "+%d" % kette["versteckt"],
            "titel": kette["titel"],
        })
    # Die Mitgliederliste hat kein FilterSet mehr -- ihre Kriterien sind alle
    # Bedingungen des Baukastens und stehen schon oben in der Kette. `not filter_obj`
    # statt `is None`: fehlt die Variable ganz, reicht Django den leeren String herein.
    if not filter_obj:
        return {"chips": chips}
    # Use the filter form's bound data so view-injected defaults (e.g. aktiv=true
    # for managers) surface as chips even when the URL itself has no params.
    bound = filter_obj.form.data if filter_obj.form.is_bound else request.GET
    skip_set = set(skip) if skip else set()

    for field in filter_obj.form:
        name = field.name
        if name in skip_set:
            continue
        values = bound.getlist(name)
        if not values or all(v == "" for v in values):
            continue

        # NullBooleanField "unknown" means no filter is applied — skip the chip
        if isinstance(field.field, NullBooleanField) and all(
            v in _NO_FILTER_VALUES for v in values
        ):
            continue

        # Build URL without this param. If the param wasn't in the URL (it was
        # a server-injected default), explicitly opt out so the default isn't
        # re-applied on the next request.
        params = request.GET.copy()
        if name in params:
            del params[name]
        elif isinstance(field.field, NullBooleanField):
            params[name] = "unknown"
        url = request.path + ("?" + params.urlencode() if params else "")

        label = field.label or name
        display_value = None
        chip_type = "default"

        filter_field = filter_obj.filters.get(name)

        if isinstance(field.field, NullBooleanField):
            # "false"/"3" → red chip; "true"/"2" → green chip
            if len(values) == 1 and values[0] in ("false", "3"):
                chip_type = "false"
            else:
                chip_type = "true"
        elif isinstance(filter_field, (ModelChoiceFilter, ModelMultipleChoiceFilter)):
            if getattr(filter_field, "exclude", False):
                chip_type = "false"
            # Resolve PKs to human-readable names via the filter's queryset,
            # with fallback to the model's full manager in case the filtered
            # queryset excludes the selected object (e.g. inactive user).
            parts = []
            qs = filter_field.queryset
            for v in values:
                if v:
                    try:
                        parts.append(str(qs.get(pk=v)))
                    except Exception:
                        try:
                            parts.append(str(qs.model.objects.get(pk=v)))
                        except Exception:
                            parts.append(v)
            display_value = ", ".join(parts) if parts else None
        elif hasattr(field.field, "choices") and field.field.choices:
            choice_dict = dict(field.field.choices)
            parts = []
            for v in values:
                if v in choice_dict:
                    parts.append(str(choice_dict[v]))
                elif v:
                    parts.append(v)
            display_value = ", ".join(parts) if parts else None
        elif any(v for v in values):
            display_value = ", ".join(v for v in values if v) or None

        chips.append({
            # Dieselbe Form wie die Kette des Baukastens: der Chip traegt seinen Text
            # fertig. Hier ist das „Feld: Wert" -- die Felder eines FilterSet sind
            # keine Saetze.
            "text": label + (": %s" % display_value if display_value else ""),
            "url": url,
            "chip_type": chip_type,
        })

    return {"chips": chips}


@register.inclusion_tag("_filter_baukasten.html")
def filter_baukasten(bedingungen, request, baukasten, kann_verwalten=False):
    """Der Zeilen-Editor des Filters: bestehende Bedingungen plus die Vorlagen.

    Das Feld-Dropdown zeigt nur die erlaubten Felder -- das ist die erste Hälfte des
    Rechte-Gates, die zweite sitzt in ``baukasten.lese_bedingungen``. Die leeren
    Zeilen kommen aus dem Register, damit ein gesperrtes Feld niemals die Vorlage
    stellt.
    """
    felder = baukasten.felder_kontext(kann_verwalten)
    leer = baukasten.bedingung_fuer_feld(felder[0]["key"], kann_verwalten)
    return {
        "zeilen": [_zeile(baukasten, b) for b in bedingungen if not baukasten.ist_fest(b)],
        # Die Ja/Nein-Felder ohne Wert: feste Schalter unter der Kette, immer da.
        "feste": baukasten.feste_kontext(bedingungen, kann_verwalten),
        "felder": felder,
        "leerzeile": _zeile(baukasten, leer),
        # Eine Werte-Vorlage je Feld, nicht je Art: Solist und Dirigent teilen die Art
        # „mehrfach", aber nicht Einträge und Beschriftungen.
        "vorlagen": [
            _zeile(baukasten, baukasten.bedingung_fuer_feld(feld["key"], kann_verwalten))
            for feld in felder
        ],
        "optionen": baukasten.optionen(),
        # Traegt die Adresse einen Marker, muss das Formular ihn weiterschicken.
        "traeger": baukasten.traeger_felder(request.GET),
    }

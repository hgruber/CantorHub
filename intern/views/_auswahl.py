"""Kontext-Helfer fuer die Chip-Mehrfachauswahl (_chip_multiselect.html).

Formulare bekommen ihre Eintraege vom Widget ChipMultiSelect; Seiten ohne
Django-Form -- die drei Berechtigungsseiten -- bauen sie hiermit selbst.
"""


def chip_eintraege(objekte, ausgewaehlt, label_attr="name"):
    """Eintragsliste im Kontrakt von _chip_multiselect.html.

    objekte     Iterable mit `id` und dem Label-Attribut
    ausgewaehlt Menge der gewaehlten IDs (int, passend zu den *_group_ids-Sets)
    """
    return [
        {
            "id": o.id,
            "label": getattr(o, label_attr),
            "selected": o.id in ausgewaehlt,
        }
        for o in objekte
    ]

"""Die Symbole der Oberfläche — eine Quelle für die Vorlagen und das Wiki.

Die Vorlagen holen ein Symbol mit ``{% symbol "trichter" class="toolicon" %}``
(``templatetags/ui_tags.py``), ein Artikel mit ``{symbol:trichter}``
(``replacements.py``). So zeigt eine Anleitung genau das Symbol, das der Leser
auf der Seite sucht, und ein geändertes Symbol ändert sich an beiden Stellen.

Alle stehen im 24er-Raster mit Strich in Textfarbe; ``STANDARD`` sind die
Attribute, die jedes ``<svg>`` trägt, ein Aufrufer kann sie überschreiben
(``stroke_width="2.5"``). Die Namen sind das, was ein Autor schreibt: deutsch,
klein, mit Bindestrich.
"""

import html

# Name → (Bedeutung für „Hilfe:Wiki“, Inhalt des <svg>)
SYMBOLE = {
    "neu": (
        "Neu anlegen",
        '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/>',
    ),
    "bearbeiten": (
        "Bearbeiten",
        '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>',
    ),
    "stift": (
        "Bearbeiten (Stift)",
        '<path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/>',
    ),
    "ansehen": (
        "Ansehen",
        '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
    ),
    "löschen": (
        "Löschen",
        '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
    ),
    "trichter": (
        "Filtern",
        '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
    ),
    "spalten": (
        "Spalten auswählen",
        '<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/>',
    ),
    "suche": (
        "Suchen",
        '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    ),
    "galerie": (
        "Als Galerie anzeigen",
        '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
    ),
    "ordner": (
        "Ordner",
        '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    ),
    "ordner-neu": (
        "Neuer Ordner",
        '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/>',
    ),
    "hochladen": (
        "Hochladen",
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
    ),
    "herunterladen": (
        "Herunterladen",
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    ),
    "anhang": (
        "Anhang",
        '<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
    ),
    "papierflieger": (
        "Senden",
        '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
    ),
    "umschlag": (
        "E-Mail",
        '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/>',
    ),
    "verlauf": (
        "Bearbeitungs-Historie",
        '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    ),
    "schloss": (
        "Zugriffskontrolle",
        '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    ),
    "kommende-termine": (
        "Kommende Termine",
        '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/><polyline points="10 14 7 17 10 20"/><line x1="14" y1="17" x2="17" y2="17"/>',
    ),
    "vergangene-termine": (
        "Vergangene Termine",
        '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/><polyline points="14 14 17 17 14 20"/><line x1="7" y1="17" x2="10" y2="17"/>',
    ),
    "ablauf": (
        "Ablauf bearbeiten",
        '<line x1="3" y1="6" x2="13" y2="6"/><line x1="3" y1="12" x2="13" y2="12"/><line x1="3" y1="18" x2="13" y2="18"/><polyline points="16 9 19 6 22 9"/><line x1="19" y1="6" x2="19" y2="18"/><polyline points="16 15 19 18 22 15"/>',
    ),
    "wiedergabe": (
        "Wiedergabe",
        '<circle cx="12" cy="12" r="9"/><polygon points="10 8 18 12 10 16" fill="currentColor" stroke="none"/>',
    ),
    "note": (
        "Lied",
        '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    ),
    "aufklappen": (
        "Alle aufklappen",
        '<path d="M7 8l5 5 5-5"/><path d="M7 14l5 5 5-5"/>',
    ),
    "haus": (
        "Zurück zur Übersicht",
        '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    ),
    "zurück": (
        "Zurück",
        '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>',
    ),
    "haken": (
        "Zusage, erledigt",
        '<polyline points="20 6 9 17 4 12"/>',
    ),
    "schließen": (
        "Absage, schließen",
        '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    ),
    "hilfe": (
        "Hilfe",
        '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    ),
}

STANDARD = {
    "xmlns": "http://www.w3.org/2000/svg",
    "viewBox": "0 0 24 24",
    "fill": "none",
    "stroke": "currentColor",
    "stroke-width": "2",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
}


def svg(name, **attribute):
    """Das ``<svg>`` zum Symbol ``name``; ein unbekannter Name wirft ``KeyError``.

    ``attribute`` kommen hinzu oder ersetzen ``STANDARD``; ein ``_`` im Namen
    wird zum ``-`` (``aria_hidden="true"``), ``None`` lässt das Attribut weg.
    """
    inhalt = SYMBOLE[name][1]
    werte = dict(STANDARD)
    for schluessel, wert in attribute.items():
        werte[schluessel.replace("_", "-")] = wert
    attr = " ".join(
        f'{k}="{html.escape(str(v))}"' for k, v in werte.items() if v is not None
    )
    return f"<svg {attr}>{inhalt}</svg>"

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

    # Navigation der Sidebar. Sie standen vorher als handgeschriebene <svg> in
    # sidebar.html — neben den {% symbol %}-Aufrufen derselben Spalte, mit
    # eigenen Strichstaerken. Jetzt kommt die ganze Spalte aus diesem Register.
    "artikel": (
        "Artikel, Aktuell",
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/>'
        '<line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>',
    ),
    "forum": (
        "Forum",
        '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    ),
    "kalender": (
        "Termine",
        '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>'
        '<line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/>'
        '<line x1="3" y1="10" x2="21" y2="10"/>',
    ),
    "kalender-tage": (
        "Kalender (Monatsansicht)",
        '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>'
        '<line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/>'
        '<line x1="3" y1="10" x2="21" y2="10"/>'
        '<path d="M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01"/>',
    ),
    "mitglieder": (
        "Mitglieder, Gruppen",
        '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
        '<path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    ),
    "karte": (
        "Karte",
        '<polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21"/>'
        '<line x1="9" y1="3" x2="9" y2="18"/><line x1="15" y1="6" x2="15" y2="21"/>',
    ),
    "ort": (
        "Orte",
        '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>',
    ),
    "einstellungen": (
        "Einstellungen",
        '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    ),
    "admin": (
        "Verwaltung, Schutz",
        '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    ),
    "aufgaben": (
        "Aufgaben, gesperrt",
        '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/><circle cx="12" cy="16" r="1"/>',
    ),
    "konfiguration": (
        "Konfiguration",
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M19.07 4.93A10 10 0 0 0 4.93 19.07M22 12a10 10 0 0 1-10 10M12 2a10 10 0 0 1 10 10"/>'
        '<path d="M2 12a10 10 0 0 0 2.93 7.07"/>',
    ),
    "sicherung": (
        "Sicherung",
        '<ellipse cx="12" cy="5" rx="9" ry="3"/>'
        '<path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>'
        '<path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>',
    ),
    "sonne": (
        "Helles Design",
        '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/>'
        '<line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>'
        '<line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/>'
        '<line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>'
        '<line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>',
    ),
    "mond": (
        "Dunkles Design",
        '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
    ),
    "abmelden": (
        "Abmelden",
        '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>'
        '<polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
    ),

    "pfeil-unten": (
        "Aufklappen",
        '<polyline points="6 9 12 15 18 9"/>',
    ),
    "profil": (
        "Mein Profil",
        '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    ),
    "schrift": (
        "Schriftgröße",
        '<polyline points="4 7 4 4 20 4 20 7"/><line x1="9" y1="20" x2="15" y2="20"/>'
        '<line x1="12" y1="4" x2="12" y2="20"/>',
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

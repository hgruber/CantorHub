"""Die Seite „Änderungen": die Release-Notizen aus ``CHANGELOG.md``.

Nicht zu verwechseln mit dem Änderungsprotokoll (``aenderungsprotokoll_list``):
das ist der Audit-Trail der Datenbank. Hier steht die Datei, in Chargen ganzer
Auslieferungen nachgeladen (``charge`` in ``intern/auslieferungen.py``).
"""

from django.conf import settings
from django.shortcuts import render

from intern.auslieferungen import charge, laufende_kennung, lies_auslieferungen

from ._decorators import perm_or_home
from ._pagination import ist_nachladen, nachlade_antwort, parse_offset

__all__ = ["auslieferungen"]


@perm_or_home("intern.manage_user_permissions")
def auslieferungen(request):
    abschnitte = lies_auslieferungen()
    # Über alle Abschnitte bestimmen, nicht nur über die Charge — sonst trüge
    # die erste Charge die Marke und die zweite nicht.
    laufende = laufende_kennung(settings.VERSION, [a.kennung for a in abschnitte])
    fenster, has_more, next_offset = charge(abschnitte, parse_offset(request))

    if ist_nachladen(request):
        # Ohne request: das Fragment liest nur die zwei Werte unten, und mit
        # request liefen die Kontextprozessoren samt der Abfragen des
        # Termin-Banners bei jedem Nachladen mit (siehe _pagination.py).
        return nachlade_antwort(
            "_auslieferungen_abschnitte.html",
            {"abschnitte": fenster, "laufende": laufende},
            has_more, next_offset,
        )

    return render(request, "auslieferungen.html", {
        "seitentitel": "Änderungen",
        "abschnitte": fenster,
        "laufende": laufende,
        "has_more": has_more,
        "next_offset": next_offset,
    })

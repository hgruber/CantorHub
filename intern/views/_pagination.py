from django.http import JsonResponse
from django.template.loader import render_to_string
from django_tables2 import RequestConfig


def paginate_ordered(request, probe_table, offset, page_size):
    """Apply the requested column sort to the full dataset, then slice.

    Build probe_table over the complete (unsliced) queryset or list.
    RequestConfig applies ?sort= to the underlying data before slicing,
    so every page window contains the globally-correct items.
    Returns (page_list, has_more).
    """
    RequestConfig(request, paginate=False).configure(probe_table)
    window = list(probe_table.data[offset : offset + page_size + 1])
    has_more = len(window) > page_size
    return (window[:page_size] if has_more else window), has_more


# Jenseits jeder realen Liste. Nötig, weil ein OFFSET über der 64-Bit-Grenze
# der Datenbank keinen leeren Ergebnissatz liefert, sondern einen Fehler — und
# der Wert aus der URL kommt, ein Besucher also ?offset=10^30 schicken kann.
_MAX_OFFSET = 10_000_000


def parse_offset(request):
    """Das ``?offset=`` der Nachlade-Anfragen — nie negativ, nie eine Exception.

    Der Wert kommt aus der URL und ist damit beliebig; ein unbrauchbarer
    beginnt wieder bei 0, statt die Liste mit einem 500er abzubrechen.
    """
    try:
        return min(max(0, int(request.GET.get("offset", 0))), _MAX_OFFSET)
    except (TypeError, ValueError):
        return 0


def ist_nachladen(request):
    """True, wenn der Infinite-Scroll die nächste Seite holt (kein Seitenaufruf)."""
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def nachlade_antwort(template, context, has_more, next_offset, request=None,
                     **extra):
    """JSON-Antwort für eine nachgeladene Tabellenseite: gerendertes Fragment
    plus die zwei Angaben, die das Skript zum Weiterblättern braucht.

    ``request`` nur übergeben, wenn das Fragment die Kontextprozessoren
    tatsächlich braucht — sonst laufen sie (samt ihrer Abfragen für das
    Termin-Banner) bei jedem Nachladen mit. ``extra`` hängt seitenspezifische
    Schlüssel an.
    """
    daten = {
        "html": render_to_string(template, context, request=request),
        "has_more": has_more,
        "next_offset": next_offset,
    }
    daten.update(extra)
    return JsonResponse(daten)

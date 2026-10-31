"""Der Standardsatz jeder Liste auf ``table.html``: Filter-Baukasten, Spaltenwahl,
Sortierung und Nachladen in einem Aufruf.

Eine Liste besteht aus drei Teilen, und nur der erste ist ihr eigener:

- einer Tabelle, die von ``tables.Spaltenwahl`` erbt (Spalten, Vorgabe,
  Verwalterspalten),
- einem Register (``filterbau_<liste>.py``, eine ``Baukasten``-Instanz),
- ``tabellenseite()`` hier, das beides auf ein Queryset anwendet.

Die View baut ihr Queryset, ruft ``tabellenseite()``, gibt ``seite.antwort``
zurueck, falls es eine gibt (Nachladen), und ergaenzt ``seite.kontext`` um das,
was nur sie hat (Titel, Anlegen, Topbar-Symbol). Siehe „The filter builder" in
``docs/frontend.md``.
"""

from dataclasses import dataclass

from django_tables2 import RequestConfig

from ..models import TabellenPreferenzen
from ._pagination import ist_nachladen, nachlade_antwort, paginate_ordered, parse_offset

SEITENGROESSE = 50


def gespeicherte_spalten(request, tabelle):
    """Die gespeicherte Spaltenwahl -- und eine neue speichern, wenn das Panel sie
    schickt. Leer, wenn es weder eine eigene noch eine globale Zeile gibt."""
    gewaehlt = request.POST.getlist("columns")
    if gewaehlt:
        TabellenPreferenzen.objects.update_or_create(
            person=request.user,
            tabelle=tabelle,
            defaults={"sichtbare_spalten": gewaehlt},
        )
        return gewaehlt
    # Bewusst first() statt get(): der unique_together deckt die globale
    # Vorgabezeile (person=None) nicht ab, weil NULLs im Unique-Index als
    # verschieden gelten (siehe TabellenPreferenzen in models.py). Eine zweite
    # Vorgabezeile darf die Tabelle nicht mit MultipleObjectsReturned zerlegen.
    pref = (
        TabellenPreferenzen.objects.filter(person=request.user, tabelle=tabelle)
        .order_by("pk")
        .first()
    )
    if pref is None:
        pref = (
            TabellenPreferenzen.objects.filter(person=None, tabelle=tabelle)
            .order_by("pk")
            .first()
        )
    return pref.sichtbare_spalten if pref else []


def spalten_waehlen(gespeichert, tabelle_cls, kann_verwalten=False):
    """Gespeicherte Wahl -> sichtbare Spalten, ohne Datenbank.

    Ohne Wahl gilt ``spalten_vorgabe`` der Tabelle, ohne Vorgabe jede Spalte.
    Verwalterspalten fallen ohne Recht heraus, auch aus einer gespeicherten Wahl.
    """
    erlaubt = tabelle_cls.waehlbare_spalten(kann_verwalten)
    gewaehlt = tabelle_cls.spalten_umdeuten(list(gespeichert or ()))
    if not gewaehlt:
        gewaehlt = list(tabelle_cls.spalten_vorgabe or erlaubt)
    return [name for name in gewaehlt if name in erlaubt]


def sichtbare_spalten(request, tabelle_cls, kann_verwalten=False):
    return spalten_waehlen(
        gespeicherte_spalten(request, tabelle_cls.__name__), tabelle_cls, kann_verwalten
    )


@dataclass
class Tabellenseite:
    """Ergebnis von ``tabellenseite()``: ``antwort`` ist die Nachlade-Antwort (sonst
    ``None``), ``kontext`` der Grundstock fuer ``table.html``, ``queryset`` das
    gefilterte, noch ungeschnittene Queryset."""

    antwort: object
    kontext: dict
    queryset: object
    bedingungen: list
    fields: list


def tabellenseite(request, tabelle_cls, queryset, *, baukasten, kann_verwalten=False,
                  namen=None, nach_filter=None, seite=None, tabelle_kwargs=None,
                  probe_kwargs=None, seitengroesse=SEITENGROESSE):
    """Filter, Spaltenwahl, Sortierung und Seite einer Liste.

    - ``namen``: Kennung -> Name fuer die Chips, als dict oder als Funktion der
      Bedingungen (das Repertoire beschriftet nur die Personen, die vorkommen).
    - ``nach_filter(qs)``: was nach dem Baukasten noch angewendet wird (das
      Repertoire haengt ``konzert`` an).
    - ``seite(zeilen)``: an die Zeilen der Seite haengen, was die Tabelle braucht,
      in einem Zugriff fuer die ganze Seite (Rollen, Aufstellungen, Protokoll).
    - ``tabelle_kwargs`` / ``probe_kwargs``: weitere Argumente fuer die Tabelle der
      Seite bzw. die Probe ueber das ganze Queryset (die Mitgliederliste schwaerzt
      nur die Seite).
    - ``seitengroesse=None``: ohne Nachladen, die ganze Liste auf einmal.
    """
    qs, bedingungen = baukasten.aus_daten(queryset, request.GET, kann_verwalten)
    if nach_filter:
        qs = nach_filter(qs)
    if callable(namen):
        namen = namen(bedingungen)
    kette = baukasten.kette(bedingungen, request, namen)
    fields = sichtbare_spalten(request, tabelle_cls, kann_verwalten)
    tabelle_kwargs = tabelle_kwargs or {}

    offset = parse_offset(request) if seitengroesse else 0
    if seitengroesse:
        probe = tabelle_cls(qs, visible_fields=fields, **(probe_kwargs or {}))
        zeilen, has_more = paginate_ordered(request, probe, offset, seitengroesse)
    else:
        zeilen, has_more = qs, False
    if seite:
        seite(zeilen)
    table = tabelle_cls(zeilen, visible_fields=fields, counter_offset=offset, **tabelle_kwargs)
    RequestConfig(request, paginate=False).configure(table)
    next_offset = offset + (seitengroesse or 0)

    antwort = None
    if seitengroesse and ist_nachladen(request):
        antwort = nachlade_antwort("table_rows.html", {"table": table}, has_more, next_offset)

    kontext = {
        "table": table,
        "column_choices": table.spalten_auswahl(fields, kann_verwalten),
        "baukasten": baukasten,
        "kann_verwalten": kann_verwalten,
        "bedingungen": bedingungen,
        "kette": kette,
        "showfilter": True,
        "has_more": has_more,
        "next_offset": next_offset,
    }
    return Tabellenseite(antwort, kontext, qs, bedingungen, fields)

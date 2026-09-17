"""Ein Zwischenspeicher für ``django_tables2.utils.signature``.

django_tables2 ruft für **jede Zelle** ``call_with_appropriate(fn, kwargs)`` auf, und
das fragt jedes Mal per ``inspect.signature`` nach den Parametern der Render-Funktion.
Die Antwort hängt allein an der Funktion und ändert sich zur Laufzeit nie; im Ordner
mit 50 Zeilen kostete sie rund 50 ms pro Seitenaufruf.

Der Schlüssel ist das zugrundeliegende Funktionsobjekt zusammen mit der Information,
ob es gebunden aufgerufen wurde: ``inspect.signature`` lässt bei einer gebundenen
Methode ``self`` weg, bei derselben Funktion unverpackt nicht. Render-Methoden und die
``row_attrs``-Lambdas stehen auf Klassenebene, ihre Funktionsobjekte leben also so lange
wie der Prozess — der Zwischenspeicher wächst damit nicht unbegrenzt.

Ein Eingriff in fremden Code, deshalb: ``django-tables2`` ist in ``requirements.txt``
auf eine Version festgelegt, und ``Tables2SignaturTest`` vergleicht das Ergebnis mit dem
der Originalfunktion. Schlägt der Test nach einem Upgrade fehl, gehört diese Datei
überprüft.
"""

import django_tables2.columns.base as _spalten
import django_tables2.utils as _utils

_original = _utils.signature
_speicher = {}


def signature_gepuffert(fn):
    try:
        schluessel = (getattr(fn, "__func__", fn), hasattr(fn, "__self__"))
        treffer = _speicher.get(schluessel)
    except TypeError:
        # Nicht hashbar (etwa ein aufrufbares Objekt mit eigenem __hash__ = None).
        return _original(fn)
    if treffer is None:
        treffer = _speicher[schluessel] = _original(fn)
    return treffer


# --- Spaltenattribute --------------------------------------------------------------------
#
# ``BoundColumn.attrs`` setzt die th/td-Attribute einer Spalte fuer **jede Zelle** neu
# zusammen: Tabellenattribute kopieren, Spaltenattribute daruebermischen, dreimal
# ``computed_values()``. Bei 50 Zeilen mal neun Spalten ist das 450-mal dasselbe Ergebnis.
#
# Gepuffert wird nur, wenn weder die Tabellen- noch die Spaltenattribute eine Funktion
# enthalten: ``computed_values()`` setzt dort ``record`` und ``value`` der jeweiligen Zeile
# ein, das Ergebnis haengt dann also sehr wohl von der Zeile ab. Die Ordnertabelle und
# ``RepertoireTabelle`` nutzen genau das.
#
# Der Puffer liegt an der ``BoundColumn`` selbst — die Objekte gehoeren zur Tabelle, leben
# also genau eine Anfrage lang, und mit ihnen verschwindet er.
_PUFFER_NAME = "_attrs_gepuffert"

_attrs_original = _spalten.BoundColumn.attrs


def _enthaelt_funktion(werte):
    for wert in werte.values():
        if callable(wert):
            return True
        if isinstance(wert, dict) and _enthaelt_funktion(wert):
            return True
    return False


def attrs_gepuffert(self):
    gemerkt = self.__dict__.get(_PUFFER_NAME)
    if gemerkt is not None:
        return gemerkt
    if _enthaelt_funktion(dict(self.column.attrs)) or _enthaelt_funktion(dict(self._table.attrs)):
        return _attrs_original.fget(self)
    ergebnis = _attrs_original.fget(self)
    self.__dict__[_PUFFER_NAME] = ergebnis
    return ergebnis


def einbauen():
    """Wird aus ``IntranetConfig.ready()`` aufgerufen; mehrfaches Aufrufen ist harmlos."""
    if _utils.signature is not signature_gepuffert:
        _utils.signature = signature_gepuffert
    if getattr(_spalten.BoundColumn.attrs, "fget", None) is not attrs_gepuffert:
        _spalten.BoundColumn.attrs = property(attrs_gepuffert)

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


def einbauen():
    """Wird aus ``IntranetConfig.ready()`` aufgerufen; mehrfaches Aufrufen ist harmlos."""
    if _utils.signature is not signature_gepuffert:
        _utils.signature = signature_gepuffert

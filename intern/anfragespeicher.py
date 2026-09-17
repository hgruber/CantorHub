"""Ein Zwischenspeicher, der genau eine Anfrage lang lebt.

Manche Werte fallen innerhalb einer Anfrage mehrfach an, ohne sich zu ändern:
``visible_folder_ids()`` läuft dreimal je Ordneransicht (jedes Mal drei Abfragen,
und es wächst mit der Zahl der Ordner), ``fallback_avatar_datei()`` einmal je
Nachricht eines Bots im Forum.

Aufbau und Lebensdauer sind die von ``app_settings``: ``request_started`` legt den
Speicher an, ``request_finished`` wirft ihn weg — beides verbunden in ``signals.py``.
**Außerhalb einer Anfrage greift er bewusst nicht** (``werte`` ist dann ``None``):
``ejabberd_bot`` und ``send_auftritt_erinnerungen`` laufen als Dauerschleife und
sähen sonst bis zum Prozessende den Stand ihres Starts.

Jeder Eintrag gehört einem Schlüssel; wer Daten schreibt, von denen ein Eintrag
abhängt, ruft ``leeren()`` — so wie es der Konfigurations-Speicher vormacht.
"""

import threading

_lokal = threading.local()


def anlegen(**kwargs):
    """``request_started``: ab hier wird gemerkt."""
    _lokal.werte = {}


def verwerfen(**kwargs):
    """``request_finished``: der Thread bedient als nächstes eine fremde Anfrage."""
    _lokal.werte = None


def leeren(**kwargs):
    """Wirft das Gemerkte weg, ohne den Speicher zu schließen.

    Für Schreibpfade, deren Ergebnis ein gemerkter Wert wäre — etwa eine geänderte
    Ordnerberechtigung, die die Sichtbarkeit von Ordnern verschiebt.
    """
    if getattr(_lokal, "werte", None) is not None:
        _lokal.werte = {}


def gemerkt(schluessel, erzeugen):
    """``erzeugen()`` höchstens einmal je Anfrage und Schlüssel aufrufen.

    Ohne laufende Anfrage wird durchgereicht, es wird also nichts gemerkt.
    """
    werte = getattr(_lokal, "werte", None)
    if werte is None:
        return erzeugen()
    if schluessel not in werte:
        werte[schluessel] = erzeugen()
    return werte[schluessel]

"""Die Auslieferungen aus ``CHANGELOG.md`` — Zerlegung und Auszeichnung.

Das ist **kein Markdown-Renderer**, sondern genau die Konstrukte, die die Datei
tatsächlich benutzt (gemessen am 23.09.2026): Überschriften ``#``/``##``,
Änderungsgruppen ``###``, ``- ``-Stichpunkte mit hart umbrochenen
Fortsetzungszeilen, Inline-``code``, ``**fett**`` und ``*kursiv*``. Keine Links,
Tabellen, Codezäune, nummerierten Listen oder Blockquotes — was das Modul nicht
kennt, bleibt als sichtbarer Rohtext stehen: harmloser und ehrlicher als eine
halbe Implementierung.

Kein Eintrag in ``requirements.txt`` dafür: die Datei ist ein Artefakt des
Abbilds mit bekanntem Inhalt, kein Nutzerinhalt. Ein Markdown-Paket brächte
einen Sanitizer mit, den hier niemand braucht — die Trust-Boundary, die
``Termin.extern`` nötig macht, gibt es hier nicht. Die Grenze der eigenen
Auszeichnung: ein ``*`` als Mal-Zeichen würde als Kursiv-Beginn gelesen, dafür
wacht allein die Hand, die die Datei schreibt (``ChangelogTest`` prüft nur das
Format, auf das der ``update``-Hook parst).

**Nicht zu verwechseln** mit dem Änderungsprotokoll (Modell ``ChangeLog``,
View ``aenderungsprotokoll_list``): das ist der Audit-Trail der Datenbank,
dies hier sind die Release-Notizen der Datei. Die Datei selbst nennt ihre
Einheit durchgängig „Auslieferung" — daher der Name dieses Moduls.

Ohne Django-Import, damit die Zerlegung so testbar bleibt wie ``terminzeit``
oder ``zusage``: ``BASE_DIR`` kommt aus ``__file__``, nicht aus den Settings.
"""

import html
import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

#: Name der Datei im Projektwurzelverzeichnis. Sie liegt mit im Abbild
#: (``Dockerfile``: ``COPY . .``, ``.containerignore`` nimmt sie nicht aus).
DATEINAME = "CHANGELOG.md"

#: Wie viele ganze Auslieferungen eine nachgeladene Charge umfasst. Die
#: Abschnitte sind sehr unterschiedlich lang (23.09.2026: 83, 131, 38 und 16
#: Zeilen), deshalb wird in Auslieferungen geschnitten, nicht in Zeilen.
ABSCHNITTE_PRO_CHARGE = 2

# Dieselben Muster, auf die ``ChangelogTest`` den ``update``-Hook schützt.
# Eine Änderung hier ohne Änderung dort (oder umgekehrt) fällt in
# ``AuslieferungenDateiTest`` auf.
UEBERSCHRIFT = re.compile(r"^##\s+(\S+)(.*)$")
STICHPUNKT = re.compile(r"^\s*[-*]\s+(.*)$")
DATUM = re.compile(r"^\s+—\s+(\d{4})-(\d{2})-(\d{2})\s*$")

# Die Änderungsgruppe innerhalb einer Auslieferung („### Hinzugefügt"). Drei
# Rauten: ``## Added`` wäre nach ``UEBERSCHRIFT`` eine Auslieferung namens
# „Added" und fiele im Wächter durch. Der ``update``-Hook lässt ``###``
# ausdrücklich zu (update.sh: „Eine ###-Zeile beendet den Abschnitt nicht, sie
# gehoert hinein").
GRUPPE = re.compile(r"^###\s+(\S.*?)\s*$")

_CODE = re.compile(r"`([^`]+)`")
_FETT = re.compile(r"\*\*([^*]+)\*\*")
_KURSIV = re.compile(r"\*([^*\n]+)\*")


@dataclass(frozen=True)
class Stichpunkt:
    """Ein Aufzählungspunkt; ``absaetze`` sind seine Absätze.

    Ein Punkt kann mehrere Absätze haben: in der Datei trennt eine Leerzeile
    den nächsten Absatz ab, nicht den nächsten Punkt. Die Zeilenumbrüche
    innerhalb eines Absatzes sind typografisch — sie sind hier bereits zu
    einem Leerzeichen geworden.
    """

    absaetze: tuple[str, ...]


@dataclass(frozen=True)
class Gruppe:
    """Eine Änderungsgruppe innerhalb einer Auslieferung.

    Der Name kommt aus der ``###``-Überschrift der Datei („Hinzugefügt",
    „Behoben", …); er ist leer, wenn Stichpunkte vor der ersten Gruppenüberschrift
    stehen. Der ``update``-Hook verlangt keine Gruppe — die Anzeige darf sich
    deshalb nicht darauf verlassen.
    """

    name: str
    stichpunkte: tuple[Stichpunkt, ...]


@dataclass(frozen=True)
class Auslieferung:
    """Eine Auslieferung: ``v1.0.0-rc4``, ``v0.9`` oder ``Unveröffentlicht``."""

    kennung: str
    datum: date | None
    gruppen: tuple[Gruppe, ...]

    @property
    def stichpunkte(self):
        """Alle Punkte der Auslieferung, Gruppe für Gruppe — flach.

        Was die Gruppe ist, geht dabei nicht verloren (``gruppen`` bleibt), aber
        alles, was nur den Text braucht — die Auszeichnung, die Zählung, der
        Vergleich mit dem Wächter — muss die Gruppen nicht kennen.
        """
        return tuple(
            punkt for gruppe in self.gruppen for punkt in gruppe.stichpunkte
        )


def zerlege(text):
    """Text rein, Abschnitte raus — rein und ohne Ausnahme.

    Alles vor der ersten ``##``-Überschrift entfällt: das ist der Vorspann der
    Datei (``# Änderungen`` und die Erklärung, wie ein Abschnitt entsteht),
    Prozess-Text für Beitragende, kein Release-Inhalt.
    """
    auslieferungen = []
    kennung = None
    rest = ""
    koerper = []

    def schliesse():
        if kennung is not None:
            auslieferungen.append(
                Auslieferung(kennung, _datum(rest), _gruppen(koerper))
            )

    for zeile in text.splitlines():
        treffer = UEBERSCHRIFT.match(zeile)
        if treffer:
            schliesse()
            kennung, rest, koerper = treffer.group(1), treffer.group(2), []
            continue
        # Eine ``###``-Zeile ist die Gruppierung innerhalb der Auslieferung und
        # gehört in den Körper. Jede andere Überschrift — ``#``, ``####`` und
        # eine ``###``-Zeile ohne Namen — ist keine Inhaltszeile: sie würde sonst
        # als Fließtext enden.
        if zeile.startswith("#") and not GRUPPE.match(zeile):
            continue
        if kennung is not None:
            koerper.append(zeile)

    schliesse()
    return auslieferungen


def _datum(rest):
    """Das ``— 2026-09-23`` der Überschriftzeile, sonst ``None``."""
    treffer = DATUM.match(rest)
    if not treffer:
        return None
    try:
        return date(int(treffer.group(1)), int(treffer.group(2)), int(treffer.group(3)))
    except ValueError:
        return None


def _stichpunkte(zeilen):
    """Zeilen eines Abschnitts oder einer Gruppe → Stichpunkte mit ihren Absätzen.

    Eine Zeile mit ``- `` beginnt einen neuen Punkt, jede andere Zeile setzt
    den laufenden Absatz fort; eine Leerzeile schließt den Absatz ab, ohne den
    Punkt zu beenden. Text ohne laufenden Punkt (kann nach
    ``ChangelogTest.test_jeder_versionsabschnitt_ist_gefuellt`` nicht
    vorkommen) fällt weg.
    """
    punkte = []
    absaetze = None
    puffer = []

    def schliesse_absatz():
        if puffer and absaetze is not None:
            absaetze.append(" ".join(zeile.strip() for zeile in puffer))
        puffer.clear()

    for zeile in zeilen:
        if not zeile.strip():
            schliesse_absatz()
            continue
        treffer = STICHPUNKT.match(zeile)
        if treffer:
            schliesse_absatz()
            absaetze = []
            punkte.append(absaetze)
        puffer.append(treffer.group(1) if treffer else zeile)
    schliesse_absatz()

    return tuple(Stichpunkt(tuple(absaetze)) for absaetze in punkte)


def _gruppen(zeilen):
    """Zeilen eines Abschnitts → Gruppen mit ihren Stichpunkten.

    Eine ``###``-Zeile beginnt eine neue Gruppe. Punkte **vor** der ersten
    Gruppenüberschrift gehören zu einer Gruppe ohne Namen — der ``update``-Hook
    verlangt keine Gruppe, die Anzeige muss also auch ohne sie funktionieren.
    Eine Gruppe ohne Stichpunkte entfällt: eine leere Überschrift ist nichts,
    was man sehen will.
    """
    gruppen = []
    name = ""
    rumpf = []

    def schliesse():
        punkte = _stichpunkte(rumpf)
        if punkte:
            gruppen.append(Gruppe(name, punkte))
        rumpf.clear()

    for zeile in zeilen:
        treffer = GRUPPE.match(zeile)
        if treffer:
            schliesse()
            name = treffer.group(1)
            continue
        rumpf.append(zeile)
    schliesse()

    return tuple(gruppen)


#: (Schlüssel, Auslieferungen) des letzten Lesevorgangs — prozessweit.
_ZWISCHENSPEICHER = None


def _pfad():
    return Path(__file__).resolve().parent.parent / DATEINAME


def lies_auslieferungen(pfad=None):
    """Die Auslieferungen der Datei — die dünne Hülle um :func:`zerlege`.

    Der Zwischenspeicher hängt an ``mtime`` und Größe, nicht am Inhalt: die
    Datei liegt im Abbild fest, ändert sich in der Entwicklung aber mit jedem
    Commit. Ein fehlendes Ziel wird als leer mitgemerkt, damit die Warnung
    einmal je Prozess kommt und nicht bei jeder Anfrage; entsteht die Datei
    später, ändert sich der Schlüssel und es heilt sich.
    """
    global _ZWISCHENSPEICHER
    ziel = Path(pfad) if pfad else _pfad()
    try:
        stand = ziel.stat()
        schluessel = (str(ziel), stand.st_mtime_ns, stand.st_size)
    except OSError:
        schluessel = (str(ziel), None, 0)

    if _ZWISCHENSPEICHER is not None and _ZWISCHENSPEICHER[0] == schluessel:
        return _ZWISCHENSPEICHER[1]

    try:
        auslieferungen = zerlege(ziel.read_text(encoding="utf-8"))
    except OSError:
        logger.warning("%s nicht lesbar — die Seite bleibt leer.", ziel)
        auslieferungen = []

    _ZWISCHENSPEICHER = (schluessel, auslieferungen)
    return auslieferungen


def laufende_kennung(versionsstring, kennungen):
    """Welche Kennung die laufende Version benennt — oder ``None``.

    ``settings.VERSION`` ist ``"CantorHub " +`` ``git describe --tags``
    (``config/settings.py``), also ``v1.0.0-rc4``, ``v1.0.0-rc4-3-g7c8b717``
    oder ``v1.0.0-rc4-dirty``. Das **längste** passende Token gewinnt: ohne
    diese Regel benennte ``v1.0.0-rc4-3-g…`` auch einen Abschnitt ``v1.0.0``,
    sobald die Endfassung neben ihren Vorabversionen steht. Ohne git
    (``CantorHub v0.1234``, ``CantorHub``) gibt es keinen Treffer — und damit
    keine Marke, statt einer falschen.
    """
    rest = (versionsstring or "").split(" ", 1)[-1].strip()
    treffer = [k for k in kennungen if rest == k or rest.startswith(k + "-")]
    return max(treffer, key=len) if treffer else None


def charge(abschnitte, offset, pro_charge=ABSCHNITTE_PRO_CHARGE):
    """Eine Charge ganzer Auslieferungen: ``(fenster, has_more, next_offset)``.

    Ohne ``paginate_ordered``: das konfiguriert eine django_tables2-Tabelle und
    wendet ``?sort=`` an, beides gibt es hier nicht — die Abschnitte sind eine
    Liste, der Schnitt ist ein ``liste[a:b]``. ``has_more`` bestimmt wie dort
    ein Element Probe; ein ``offset`` jenseits des Endes ist keine Ausnahme,
    sondern eine leere Charge.
    """
    fenster = list(abschnitte[offset:offset + pro_charge + 1])
    has_more = len(fenster) > pro_charge
    return (fenster[:pro_charge] if has_more else fenster), has_more, offset + pro_charge


def auszeichnen(absatz):
    """Inline-Markup eines Absatzes: ``code``, ``fett``, ``kursiv``.

    Erst ``html.escape``, dann feste, vertrauenswürdige Tags — das Muster von
    ``replacements.apply_replacements``. Die Code-Spans werden zuerst
    herausgenommen, damit ein ``*`` in einem Code-Span kein ``<em>`` wird;
    innerhalb eines Spans bleibt nur das Escapen. Die Rückgabe ist damit
    vertrauenswürdig, aber **nicht** ``mark_safe``: das Modul kennt Django
    nicht, den ``SafeString`` setzt der Filter.
    """
    if not absatz:
        return ""
    teile = []
    letzter = 0
    for treffer in _CODE.finditer(absatz):
        teile.append(_betonen(absatz[letzter:treffer.start()]))
        teile.append("<code>%s</code>" % html.escape(treffer.group(1)))
        letzter = treffer.end()
    teile.append(_betonen(absatz[letzter:]))
    return "".join(teile)


def _betonen(text):
    """Escapen und ``**fett**``/``*kursiv*`` setzen — in dieser Reihenfolge,
    damit ein ``**`` vor einem einzelnen ``*`` gelesen wird."""
    text = html.escape(text)
    text = _FETT.sub(r"<strong>\1</strong>", text)
    return _KURSIV.sub(r"<em>\1</em>", text)

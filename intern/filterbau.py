"""Der Filter-Baukasten: eine Kette von Bedingungen, für jedes Register.

Statt eines festen Feldes je Kriterium filtert eine Seite mit einer **Kette von
Bedingungen**: beliebig viele, jede mit eigenem Konnektor (und/oder) und eigener
Verneinung. Damit ist „in Gruppe A und in Gruppe B und nicht in Gruppe C" baubar --
mit festen Feldern war das nicht auszudruecken, weil ein Mehrfachauswahl-Feld seine
Werte immer ODERt und jedes Feld nur einmal vorkam.

**Auswertung.** UND bindet staerker als ODER, wie ueberall sonst. Die Kette wird an
jedem ``oder`` in Abschnitte zerlegt, jeder Abschnitt geundet und die Ergebnisse
geodert: ``A oder B und C`` ist ``A oder (B und C)``. Die Titelleiste klammert das
genau so, damit die Anzeige nicht luegt.

**Zwei Register.** Dieses Modul ist die Maschine und kennt kein einziges Feld. Die
Register liegen daneben: ``filterbau_mitglieder`` und ``filterbau_titel``. Jedes ist
ein ``Baukasten`` -- Felder, Reihenfolge und ein paar Haken, die nur die eine Seite
braucht (die Zugangs-Vorgabe der Mitgliederliste etwa). Damit teilen beide Seiten die
Mechanik und keine Zeile Fachlichkeit.

Alles hier ist ohne Datenbankzugriff -- parsen, verknuepfen, beschriften sind reine
Funktionen, damit ein ``SimpleTestCase`` sie pinnen kann (Vorbild: ``verwendung.py``,
``mitgliedschaft.py``). Nur die Beschriftung von Fremdschluesseln braucht Namen; die
reicht der Aufrufer herein.
"""

from dataclasses import dataclass, replace
from datetime import date
from urllib.parse import quote, unquote

from django.db.models import Q

# Konnektoren der Kette. Die erste Bedingung traegt keinen; sie wird beim Lesen auf
# „und" normalisiert, damit die Auswertung keine Sonderrolle braucht.
KONNEKTOREN = ("und", "oder")

# Hoechstens so viele Bedingungen stehen als Chips in der Titelleiste; der Rest
# wird ein „+n". Gedeckelt wird serverseitig statt per DOM-Messung -- das ist
# deterministisch und damit pruefbar.
MAX_CHIPS = 3

# Das eine Recht, das ueber Felder entscheidet. Verwalter sehen ohnehin jedes Feld
# (``User.field_visible_to``), die uebrigen Mitglieder nicht.
RECHT_VERWALTER = "intern.change_user"


@dataclass(frozen=True)
class Bedingung:
    """Eine Zeile des Baukastens."""

    verbindung: str  # "und" | "oder"
    feld: str
    operator: str
    werte: tuple


@dataclass(frozen=True)
class Feld:
    """Ein im Baukasten verwendbares Feld.

    ``art`` waehlt im Template das Werte-Widget. ``operatoren`` sind
    ``(Schluessel, Beschriftung, verneinend, Satzbaustein)``: der Satzbaustein ist
    die Formulierung des Chips, mit ``{w}`` fuer die Werte und ``{feld}`` fuer den
    Feldnamen. Er traegt die Verneinung selbst aus („ist nicht in Gruppe …") -- das
    ``verneinend`` faerbt den Chip nur rot und bedient den Drei-Zustand-Schalter; als
    Wort steht es nirgends mehr davor, weil der Satz sonst doppelt verneinte.

    **Hat ein Feld genau zwei Operatoren, den ersten bejahend und den zweiten
    verneinend** (``hat_paar``), bedient es ein Drei-Zustand-Schalter: als fester
    Schalter unter der Kette, wenn es keinen Wert hat (``ist_fest``), sonst neben
    seinem Einzelwert (``hat_schalter``). Die beiden Beschriftungen sind dann
    zugleich die Tooltips der Stellungen.

    ``q`` baut das Q-Objekt, ``werte_text`` beschriftet die Werte fuer ``{w}``
    (``namen`` ist die Zuordnung Kennung -> Name des Feldes). ``satz_bauer``
    ueberschreibt den Satzbaustein, wo die Formulierung von den Werten abhaengt --
    die Zusage der Mitgliederliste wird aus Termin und Antwort gebaut.

    Ein Feld ueber eine Mehrfachrelation baut sein Q **als EXISTS-Unterabfrage**, nicht
    als Join: eine verneinte Join-Bedingung prueft sonst die einzelne
    Verknuepfungszeile statt des Datensatzes, und wer ausser der ausgeschlossenen
    Gruppe noch eine andere hat, rutschte durch. Die Unterabfrage spart zugleich den
    Join und damit die doppelten Koepfe -- ein ``.distinct()`` braucht hier nichts.

    ``ohne_wert`` heisst: der Operator traegt die Aussage, es gibt keine Werte.
    ``recht`` schliesslich: wem das Feld ueberhaupt angeboten wird. ``namen_aus``
    sagt, aus welchem Eintrag von ``namen`` die Werte beschriftet werden -- die
    Zusage nennt einen Termin und braucht dessen Zuordnung. ``texte`` ueberschreibt
    die Beschriftungen der Chip-Mehrfachauswahl (``auswahl_label``,
    ``vorrat_label``, ``such_platzhalter``, ``leer_text``).
    """

    key: str
    label: str
    art: str
    operatoren: tuple
    q: object
    werte_text: object
    ohne_wert: bool = False
    recht: str = None
    namen_aus: str = None
    satz_bauer: object = None
    texte: dict = None


def hat_paar(feld):
    """Genau ein Ja/Nein-Paar: der erste Operator bejahend, der zweite verneinend."""
    return (
        len(feld.operatoren) == 2
        and not feld.operatoren[0][2]
        and feld.operatoren[1][2]
        and feld.operatoren[0][0] != feld.operatoren[1][0]
    )


def ist_fest(feld):
    """Ein Ja/Nein-Feld ohne Wert (Hymne, Aufnahme, Zugang) steht nicht im
    Feld-Dropdown, sondern als fester Drei-Zustand-Schalter unter der Kette --
    immer da, „egal" als Grundstellung. Es wird mit UND vor die ganze Kette
    gehaengt; ein ODER ist fuer diese Felder nicht vorgesehen."""
    return feld.ohne_wert and hat_paar(feld)


def hat_schalter(feld):
    """Der Drei-Zustand-Schalter in einer Zeile: bei einem Ja/Nein-Paar mit genau
    einem Wert (Tempo, Tonart, Zusage). Eine Mehrfachauswahl bekommt stattdessen
    die Auswahlliste „ist in / ist nicht in" -- „egal" ergaebe dort keinen Sinn,
    eine leere Auswahl sagt es schon. Text- und Datumsfelder haben ohnehin mehr
    als ein Paar."""
    return hat_paar(feld) and not feld.ohne_wert and feld.art != "mehrfach"


# ------------------------------------------------------------ Bausteine fuer Register
#
# Was beide Register brauchen: Q-Bauer fuer gewoehnliche Spalten und Wertebauer fuer
# die Chip-Beschriftung.


def wahl_q(feldname, ja="in", nein="nicht-in"):
    """Mehrere erlaubte Werte in einer gewoehnlichen Spalte (Stimme, Tempo)."""
    def q(operator, werte):
        treffer = Q(**{feldname + "__in": werte})
        return treffer if operator == ja else ~treffer

    return q


def text_q(*feldnamen):
    """Textoperatoren ueber ein oder mehrere Felder, mit ODER verknuepft.

    „Suche" greift so ueber Titel, Komponist und Bearbeiter zugleich, „Name" ueber
    Vor- und Nachnamen -- niemand soll wissen muessen, in welchem Feld es steht.
    """
    lookup = {
        "enthaelt": "icontains",
        "beginnt": "istartswith",
        "endet": "iendswith",
        "ist": "iexact",
    }

    def q(operator, werte):
        wert = werte[0]
        if operator == "enthaelt-nicht":
            breit = Q()
            for name in feldnamen:
                breit |= Q(**{name + "__icontains": wert})
            return ~breit
        eng = Q()
        for name in feldnamen:
            eng |= Q(**{name + "__" + lookup[operator]: wert})
        return eng

    return q


def datum_q(feldname, mit_uhrzeit):
    """Datumsspalte. ``mit_uhrzeit`` haengt ``__date`` an -- ``last_login`` und
    ``date_joined`` sind Zeitstempel, ``geburtstag`` ist ein reines Datum."""
    basis = feldname + "__date" if mit_uhrzeit else feldname
    lookup = {"vor": "lt", "nach": "gt", "ist": "exact"}

    def q(operator, werte):
        return Q(**{basis + "__" + lookup[operator]: werte[0]})

    return q


def namens_wert(werte, namen):
    """Werte ueber eine Kennung -> Name-Zuordnung beschriften.

    Ohne Zuordnung stehen die Kennungen -- immer noch besser als eine leere Zeile,
    und ohne Datenbankzugriff pruefbar.
    """
    return ", ".join((namen or {}).get(w, w) for w in werte)


def text_wert(werte, namen):
    return werte[0]


def datum_wert(werte, namen):
    try:
        return date.fromisoformat(werte[0]).strftime("%d.%m.%Y")
    except ValueError:
        return werte[0]


# ---------------------------------------------------------------- Das Register


@dataclass(frozen=True)
class Baukasten:
    """Ein Register samt seiner Eigenheiten.

    ``eintraege(feld_key)`` liefert die Auswahl einer ``auswahl``- oder
    ``mehrfach``-Art als ``[{"wert", "label"}, …]``. Die vier Haken sind die Stellen,
    an denen sich die Seiten unterscheiden; sie duerfen ``None`` bleiben:

    - ``vorgabe(bedingungen, daten, kann_verwalten)`` -- eine Voreinstellung, die
      still vorangestellt wird (Mitgliederliste: nur Konten mit Zugang).
    - ``alt_parameter(daten)`` -- die festen Filterfelder von vor dem Baukasten
      uebersetzen. Ohne sie zeigte ein gemerkter Filter im Cookie ungefiltert.
    - ``marker(feld_key, rest)`` -- zusaetzliche Parameter fuer die Chip-Adresse,
      wenn genau diese Bedingung entfernt wird (Mitgliederliste: ``zugang=egal``).
    - ``traeger(daten)`` -- zusaetzliche versteckte Felder des Formulars.

    ``zusaetze`` sind weitere Auswahllisten, die sich nicht an ein Feld haengen lassen
    -- die Zusage-Zeile braucht zwei (Termin und Antwort), hat aber nur einen
    Feldnamen.
    """

    felder: dict
    reihenfolge: tuple
    eintraege: object = None
    vorgabe: object = None
    alt_parameter: object = None
    marker: object = None
    traeger: object = None
    zusaetze: dict = None

    # ------------------------------------------------------------ Zugriff

    def feld(self, key):
        return self.felder[key]

    def erlaubte_felder(self, kann_verwalten=False):
        """Welche Felder dieser Betrachter ueberhaupt sehen und filtern darf."""
        return frozenset(
            key for key, feld in self.felder.items()
            if feld.recht is None or kann_verwalten
        )

    def ist_fest(self, bedingung):
        return ist_fest(self.felder[bedingung.feld])

    def _ordne(self, bedingungen):
        """Feste Bedingungen nach vorn, jede mit „und"; die Kette danach beginnt
        ebenfalls mit „und". So liest sich die Reihenfolge, wie ``baue_q`` rechnet."""
        fest = [replace(b, verbindung="und") for b in bedingungen if self.ist_fest(b)]
        rest = [b for b in bedingungen if not self.ist_fest(b)]
        if rest:
            rest[0] = replace(rest[0], verbindung="und")
        return fest, rest

    def ist_verneinend(self, bedingung):
        for schluessel, _label, nicht, _satz in self.felder[bedingung.feld].operatoren:
            if schluessel == bedingung.operator:
                return nicht
        return False

    def _satz_vorlage(self, feld, operator):
        for schluessel, _label, _nicht, vorlage in feld.operatoren:
            if schluessel == operator:
                return vorlage
        return "{w}"

    # ------------------------------------------------------------- Lesen

    def _parse(self, zeile):
        """Ein ``f``-Wert -> Bedingung. Unbekanntes und Kaputtes faellt still heraus."""
        teile = (zeile or "").split(":", 3)
        if len(teile) != 4:
            return None
        verbindung, feld, operator, wert = (t.strip() for t in teile)
        feld_obj = self.felder.get(feld)
        if feld_obj is None or operator not in [o for o, _l, _n, _k in feld_obj.operatoren]:
            return None
        werte = tuple(unquote(w.strip()) for w in wert.split(",") if w.strip())
        if not werte and not feld_obj.ohne_wert:
            return None
        return Bedingung(
            verbindung if verbindung in KONNEKTOREN else "und", feld, operator, werte
        )

    def lese_bedingungen(self, daten, kann_verwalten=False):
        """GET-Parameter -> Liste von Bedingungen.

        ``daten`` ist ein QueryDict. Ohne ``f`` werden die Parameter der Zeit vor dem
        Baukasten uebersetzt: ``@tabellenzustand`` merkt sich die Query ein Jahr lang
        im Cookie und leitet einen Aufruf ohne Parameter dorthin um -- kennte die
        Ansicht die alten Namen nicht mehr, saehe man eine **ungefilterte** Liste, die
        wie eine gefilterte aussieht.

        Das Recht wird **hier** geprueft, nicht nur im Dropdown: sonst umginge eine
        handgeschriebene Adresse die Oberflaeche und verriete ueber die Treffermenge,
        was die Tabelle verschweigt.
        """
        erlaubt = self.erlaubte_felder(kann_verwalten)
        roh = daten.getlist("f")
        if roh:
            bedingungen = [
                b for b in (self._parse(z) for z in roh)
                if b and b.feld in erlaubt
            ]
        else:
            alt = self.alt_parameter(daten) if self.alt_parameter else []
            bedingungen = [b for b in alt if b.feld in erlaubt]
        fest, rest = self._ordne(bedingungen)
        return fest + rest

    # --------------------------------------------------------- Auswerten

    def baue_q(self, bedingungen):
        """Bedingungen -> Q-Objekt. Ohne Bedingungen ein leeres Q (filtert nichts).

        Die festen Bedingungen gelten fuer die ganze Kette: ``fest und (Kette)``.
        """
        fest, rest = self._ordne(bedingungen)
        kette = None
        for abschnitt in abschnitte(rest):
            q = Q()
            for b in abschnitt:
                q &= self.felder[b.feld].q(b.operator, b.werte)
            kette = q if kette is None else (kette | q)
        gesamt = Q()
        for b in fest:
            gesamt &= self.felder[b.feld].q(b.operator, b.werte)
        if kette is not None:
            gesamt &= kette
        return gesamt

    def aus_daten(self, queryset, daten, kann_verwalten=False):
        """Bedingungen aus den Daten lesen, die Vorgabe ergaenzen und anwenden.

        Nimmt **Daten** entgegen, nicht den Request: ``mitglied_benachrichtigen`` liest
        seine Filter im POST aus einem mitgereichten QueryDict. Liefert
        ``(queryset, bedingungen)`` -- die Bedingungen braucht die Ansicht fuer die
        Chip-Leiste.
        """
        bedingungen = self.lese_bedingungen(daten, kann_verwalten)
        if self.vorgabe:
            bedingungen = self.vorgabe(bedingungen, daten, kann_verwalten)
        q = self.baue_q(bedingungen)
        if q:
            queryset = queryset.filter(q)
        return queryset, bedingungen

    # -------------------------------------------------------- Formular

    def felder_kontext(self, kann_verwalten=False):
        """Die Felder des Baukastens fuer das Template: Feld- und Operator-Dropdown.

        Nur die erlaubten -- das Dropdown ist die erste Haelfte des Rechte-Gates, die
        zweite sitzt in ``lese_bedingungen``.
        """
        erlaubt = self.erlaubte_felder(kann_verwalten)
        return [
            {
                "key": feld.key,
                "label": feld.label,
                "art": feld.art,
                "schalter": hat_schalter(feld),
                "operatoren": [
                    {"key": k, "label": l, "nicht": n, "satz": satz}
                    for k, l, n, satz in feld.operatoren
                ],
            }
            for feld in (self.felder[k] for k in self.reihenfolge if k in erlaubt)
            if not ist_fest(feld)
        ]

    def feste_kontext(self, bedingungen, kann_verwalten=False):
        """Die festen Schalter unter der Kette, mit ihrer Stellung.

        ``marker`` ist, was das Formular mitschicken muss, wenn der Schalter auf
        „egal" steht -- dieselbe Regel wie beim Entfernen per Chip (bei der
        Mitgliederliste ``zugang=egal``, sonst haengte die Vorgabe den Zugang
        sofort wieder an).
        """
        erlaubt = self.erlaubte_felder(kann_verwalten)
        gesetzt = {b.feld: b for b in bedingungen if self.ist_fest(b)}
        feste = []
        for key in self.reihenfolge:
            feld = self.felder[key]
            if key not in erlaubt or not ist_fest(feld):
                continue
            (ja, ja_label, _n, _s), (nein, nein_label, _n2, _s2) = feld.operatoren
            b = gesetzt.get(key)
            stellung = "egal" if b is None else ("nein" if b.operator == nein else "ja")
            feste.append({
                "key": key,
                "label": feld.label,
                "ja": ja,
                "ja_label": ja_label,
                "nein": nein,
                "nein_label": nein_label,
                "stellung": stellung,
                "wert": kodiere(b) if b else "",
                "marker": self.marker(key, []) if self.marker else {},
            })
        return feste

    def wert_texte(self, feld):
        """Die Beschriftungen der Chip-Mehrfachauswahl eines Feldes."""
        grund = {
            "auswahl_label": "Gewählt",
            "vorrat_label": "Verfügbar",
            "such_platzhalter": "Suchen …",
            "leer_text": "Nichts ausgewählt",
        }
        grund.update(feld.texte or {})
        return grund

    def bedingung_fuer_feld(self, feld_key, kann_verwalten=False):
        """Die leere Startzeile fuer ein Feld -- fuer die Vorlage, aus der neue Zeilen
        geklont werden."""
        if feld_key not in self.erlaubte_felder(kann_verwalten):
            return None
        feld = self.felder[feld_key]
        return Bedingung("und", feld.key, feld.operatoren[0][0], ())

    def optionen(self):
        """Alle vom Server zu liefernden Auswahllisten: ``{feld: [{wert, label}]}``.

        Als **ein** Bündel, nicht je Liste eine eigene Kennung: das Skript füllt damit
        jede ``auswahl``- und ``mehrfach``-Auswahl, und ein zweiter Baukasten kann die
        Kennungen nicht verwechseln.
        """
        if not self.eintraege:
            return dict(self.zusaetze or {})
        return {
            key: self.eintraege(key)
            for key, feld in self.felder.items()
            if feld.art in ("auswahl", "mehrfach", "zusage")
        } | dict(self.zusaetze or {})

    def traeger_felder(self, daten):
        """Zusaetzliche versteckte Felder, die das Formular weiterschicken muss."""
        return self.traeger(daten) if self.traeger else []

    # ------------------------------------------------------- Titelleiste

    def _namen_von(self, bedingung, namen):
        feld = self.felder[bedingung.feld]
        return (namen or {}).get(feld.namen_aus or feld.key) or {}

    def chip_text(self, bedingung, namen=None):
        """Die Bedingung als Satz -- „ist in Gruppe Vorstand, Kassenprüfer".

        Der Satz traegt die Verneinung selbst („ist nicht in Gruppe …"); das rote
        Hinterlegen kommt weiterhin aus ``ist_verneinend``, aber es steht kein zweites
        „nicht" davor.
        """
        feld = self.felder[bedingung.feld]
        namen_feld = self._namen_von(bedingung, namen)
        if feld.satz_bauer:
            return feld.satz_bauer(bedingung.operator, bedingung.werte, namen_feld)
        return self._satz_vorlage(feld, bedingung.operator).format(
            w=feld.werte_text(bedingung.werte, namen_feld), feld=feld.label
        )

    def chip_von(self, bedingung, namen=None):
        """Text und Rotfaerbung einer Bedingung -- fuer Chip und Satz."""
        return {
            "text": self.chip_text(bedingung, namen),
            "nicht": self.ist_verneinend(bedingung),
        }

    def satz(self, bedingungen, namen=None):
        """Die Kette als Satz -- fuer den Tooltip des „+n"-Chips."""
        teile = []
        for i, b in enumerate(bedingungen):
            vorne = "" if i == 0 else b.verbindung + " "
            teile.append(vorne + self.chip_text(b, namen))
        return " ".join(teile)

    def _url_ohne(self, request, bedingungen, index):
        """Adresse, die genau die Bedingung ``index`` aus der Kette entfernt.

        Der Register-Haken ``marker`` legt nach, was das Entfernen sonst nicht
        festhalten kann -- bei der Mitgliederliste die abgewaehlte Zugangs-Vorgabe.
        """
        weg = bedingungen[index]
        rest = [b for i, b in enumerate(bedingungen) if i != index]
        params = request.GET.copy()
        if rest:
            params.setlist("f", kodiere_alle(rest))
        else:
            params.pop("f", None)
        if self.marker:
            params.update(self.marker(weg.feld, rest))
        return request.path + ("?" + params.urlencode() if params else "")

    def kette(self, bedingungen, request, namen=None, max_chips=MAX_CHIPS):
        """Die Bedingungen als Anzeigeelemente fuer die Titelleiste.

        Die Elemente haben dieselbe Form wie die Chips aus ``filter_tags`` und werden
        dort vorangestellt -- eine Leiste, ein Container. Ein Element ist entweder ein
        Chip (``text``/``url``/``chip_type``/``nicht``), ein Konnektorwort (``verb``)
        oder eine Klammer (``klammer``).

        Zwischen den Chips steht das Konnektorwort. Geklammert wird nur, wenn es
        ueberhaupt mehr als einen Abschnitt gibt -- die haeufige reine UND-Kette bleibt
        damit klammerefrei. Wird die Kette gedeckelt, entfallen die Klammern: eine
        abgekuerzte Kette mit Klammern waere nur noch Rauschen, und den vollstaendigen
        Satz traegt der Tooltip des „+n"-Chips.
        """
        fest, rest = self._ordne(bedingungen)
        bedingungen = fest + rest
        n_fest = len(fest)
        abschnitte_ = abschnitte(rest)
        zeige = bedingungen[:max_chips]
        geklammert = len(abschnitte_) > 1 and len(zeige) == len(bedingungen)
        auf, zu = _klammern(abschnitte_, len(rest)) if geklammert else (set(), set())
        # Die festen Bedingungen gelten fuer die ganze Kette: „Hymne und (A oder B)".
        aussen = geklammert and n_fest > 0

        elemente = []
        for i, b in enumerate(zeige):
            j = i - n_fest  # Stelle in der Kette, negativ fuer die festen
            if i:
                elemente.append({"verb": "und" if j <= 0 else b.verbindung})
            if aussen and j == 0:
                elemente.append({"klammer": "("})
            if j in auf:
                elemente.append({"klammer": "("})
            chip = self.chip_von(b, namen)
            chip["url"] = self._url_ohne(request, bedingungen, i)
            chip["chip_type"] = "false" if chip["nicht"] else "default"
            elemente.append(chip)
            if j in zu:
                elemente.append({"klammer": ")"})
            if aussen and j == len(rest) - 1:
                elemente.append({"klammer": ")"})

        return {
            "elemente": elemente,
            "versteckt": max(0, len(bedingungen) - max_chips),
            "titel": self.satz(bedingungen, namen),
        }


# ------------------------------------------- Was ohne Register geht


def kodiere(bedingung):
    """Bedingung -> Wert des GET-Parameters ``f``.

    Jeder Einzelwert wird einzeln percent-kodiert: ein getippter Name darf ein
    Komma oder einen Doppelpunkt enthalten, und beides sind hier Trennzeichen.
    Gelesen wird entsprechend erst geteilt und dann je Teil ``unquote``t -- so
    bleiben auch die alten, unkodierten Werte (``1,4``) gueltig.
    """
    return ":".join(
        (bedingung.verbindung, bedingung.feld, bedingung.operator,
         ",".join(quote(w, safe="") for w in bedingung.werte))
    )


def kodiere_alle(bedingungen):
    """Bedingungen -> Liste von ``f``-Werten. Die erste traegt keinen Konnektor."""
    return [
        kodiere(b if i else replace(b, verbindung="und"))
        for i, b in enumerate(bedingungen)
    ]


def abschnitte(bedingungen):
    """Die Kette an jedem ``oder`` in Abschnitte zerlegen.

    Innerhalb eines Abschnitts gilt UND, zwischen den Abschnitten ODER -- genau die
    uebliche Bindung, in der UND staerker ist.
    """
    teile = []
    for b in bedingungen:
        if b.verbindung == "oder" or not teile:
            teile.append([b])
        else:
            teile[-1].append(b)
    return teile


def _klammern(abschnitte_, sichtbar):
    """Je Abschnitt: vor welchem Chip geht eine Klammer auf, nach welchem zu.

    Nur Abschnitte mit mehr als einer Bedingung brauchen eine -- eine einzelne
    Bedingung ist schon fuer sich ein Ausdruck.
    """
    auf, zu = set(), set()
    anfang = 0
    for abschnitt in abschnitte_:
        grenze = anfang + len(abschnitt)
        if grenze > sichtbar:
            break
        if len(abschnitt) > 1:
            auf.add(anfang)
            zu.add(grenze - 1)
        anfang = grenze
    return auf, zu

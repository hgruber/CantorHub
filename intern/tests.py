"""Tests der Auftritts-Mailingliste und kleiner reiner Helfer.

Bewusst ohne Datenbank: die Zeitlogik ist rein, ``jetzt`` wird übergeben.
Für Termine reicht ein winziges Stellvertreter-Objekt — ``faelligkeit`` und
``faellige_erinnerungen`` lesen nur ``datum``.
"""

import ast
import os
import re
from pathlib import Path
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from unittest import mock

from django.core.signals import request_finished, request_started
from django.db.models import Q
from django import forms
from django.http import QueryDict
from django.template import Context, Template
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils.html import escape
from django.utils.timesince import timeuntil

from intern import app_settings
from intern.anfragespeicher import anlegen as anfrage_anlegen
from intern.anfragespeicher import gemerkt
from intern.anfragespeicher import leeren as anfrage_leeren
from intern.anfragespeicher import verwerfen as anfrage_verwerfen
from intern.mitgliedschaft import (
    GRUPPE_FOERDERMITGLIED,
    GRUPPE_GRUENDER,
    GRUPPE_DATENSCHUTZ_BESTAETIGT,
    GRUPPE_KEIN_BILD,
    GRUPPE_MITGLIED,
    antragslink_gilt,
    aufnahme_setzt_aktiv,
    bestaetigungslink_zustand,
    braucht_datenschutzbestaetigung,
    kein_bild_aus_einwilligung,
    mitgliedschafts_aktion,
    ist_erstaufnahme,
)
from intern.aufstellung import aufstellung
from intern.auslieferungen import (
    ABSCHNITTE_PRO_CHARGE, Auslieferung, Gruppe, Stichpunkt, auszeichnen, charge,
    laufende_kennung, lies_auslieferungen, zerlege,
)
from intern.blob_aufraeumen import verwaiste_pfade, zugeordnetes_verzeichnis
from intern.forms import SchnellSelect, SchnellSelectMultiple
from intern.middleware import (
    DATENSCHUTZ_FREI,
    GZip,
    datenschutz_pruefpflichtig,
    muss_auffrischen,
)
from intern.tables import TerminTabelle
from intern.tables2_beschleunigung import (
    _original as tables2_original, attrs_gepuffert, signature_gepuffert,
)
from intern.mailingliste import faelligkeit, faellige_erinnerungen, parse_wochen
from intern.templatetags.termin_tags import zeitraum_bis
from intern.terminzeit import countdown_text, ist_ganztaegig, kommende_q, zeitraum_aus_eingabe
from intern.views.files import _ziel_owner


def _termin(jahr, monat, tag, stunde=20, minute=0):
    return SimpleNamespace(datum=datetime(jahr, monat, tag, stunde, minute), ort=None)


class ParseWochenTest(SimpleTestCase):
    def test_normalfall(self):
        self.assertEqual(parse_wochen(["4", "1"]), [4, 1])

    def test_absteigend_und_dedupliziert(self):
        self.assertEqual(parse_wochen(["1", "4", "4", "2"]), [4, 2, 1])

    def test_unsinn_wird_verworfen(self):
        # Der Dauerloop darf an einer von Hand editierten Konfiguration nicht kippen.
        self.assertEqual(parse_wochen(["a", "", "-3", "4"]), [4])

    def test_leere_liste(self):
        self.assertEqual(parse_wochen([]), [])


class FaelligkeitTest(SimpleTestCase):
    def test_gleiche_uhrzeit_gleicher_wochentag(self):
        termin = _termin(2026, 9, 26, 20, 0)          # Samstag
        faellig = faelligkeit(termin, 4, time(18, 0))
        self.assertEqual(faellig, datetime(2026, 8, 29, 20, 0))
        self.assertEqual(faellig.weekday(), termin.datum.weekday())

    def test_fallback_ohne_uhrzeit(self):
        termin = _termin(2026, 9, 26, 0, 0)
        self.assertEqual(
            faelligkeit(termin, 1, time(18, 0)), datetime(2026, 9, 19, 18, 0)
        )

    def test_ueber_die_sommerzeitgrenze(self):
        # USE_TZ=False: alles ist naive Wanduhrzeit, die Uhrzeit bleibt stehen.
        # Ende Oktober 2026 wird die Uhr zurückgestellt.
        termin = _termin(2026, 11, 7, 19, 30)
        faellig = faelligkeit(termin, 4, time(18, 0))
        self.assertEqual(faellig, datetime(2026, 10, 10, 19, 30))
        self.assertEqual(faellig.time(), time(19, 30))


class FaelligeErinnerungenTest(SimpleTestCase):
    def setUp(self):
        self.termin = _termin(2026, 9, 26, 20, 0)
        self.wochen = [4, 1]
        self.fallback = time(18, 0)

    def _treffer(self, jetzt):
        return faellige_erinnerungen([self.termin], self.wochen, jetzt, self.fallback)

    def test_genau_zum_zeitpunkt(self):
        treffer = self._treffer(datetime(2026, 8, 29, 20, 0))
        self.assertEqual([(t.datum, w) for t, w, _ in treffer],
                         [(self.termin.datum, 4)])

    def test_eine_minute_zu_frueh(self):
        self.assertEqual(self._treffer(datetime(2026, 8, 29, 19, 59)), [])

    def test_innerhalb_der_kulanz(self):
        self.assertEqual(len(self._treffer(datetime(2026, 8, 30, 19, 0))), 1)

    def test_kulanz_abgelaufen(self):
        # Nach einem längeren Ausfall keine sinnlos verspäteten Mails.
        self.assertEqual(self._treffer(datetime(2026, 8, 30, 21, 0)), [])

    def test_termin_bereits_vorbei(self):
        self.assertEqual(self._treffer(self.termin.datum + timedelta(minutes=1)), [])

    def test_zweiter_vorlauf(self):
        treffer = self._treffer(datetime(2026, 9, 19, 20, 0))
        self.assertEqual([w for _, w, _ in treffer], [1])

    def test_sortiert_nach_faelligkeit(self):
        # Zwei Termine, deren Erinnerungen im selben Fenster liegen.
        frueh = _termin(2026, 9, 26, 10, 0)
        spaet = _termin(2026, 9, 26, 20, 0)
        treffer = faellige_erinnerungen(
            [spaet, frueh], [4], datetime(2026, 8, 29, 20, 0), self.fallback
        )
        self.assertEqual([f for _, _, f in treffer],
                         sorted(f for _, _, f in treffer))


class AbmeldeTokenTest(SimpleTestCase):
    """Der Abmelde-Token ist signiert statt gespeichert.

    Geprüft wird die reine Signatur-/Fingerabdruck-Logik; der Datenbank-Zugriff
    steckt bewusst allein in ``read_abmelde_token``.
    """

    def _abo(self, pk=7, email="a@example.org"):
        from intern.models import Auftrittsabo
        return Auftrittsabo(pk=pk, email=email)     # nicht gespeichert

    def test_runde(self):
        from intern.mailingliste import (
            _fingerabdruck, lese_abmelde_token, make_abmelde_token,
        )
        token = make_abmelde_token(self._abo())
        self.assertEqual(
            lese_abmelde_token(token), (7, _fingerabdruck("a@example.org"))
        )

    def test_adresse_steht_nicht_im_token(self):
        # Sonst landete sie in Server-Logs, Referrern und der Browser-Chronik.
        from intern.mailingliste import make_abmelde_token
        self.assertNotIn("a@example.org", make_abmelde_token(self._abo()))

    def test_manipuliertes_token(self):
        from intern.mailingliste import lese_abmelde_token, make_abmelde_token
        self.assertIsNone(lese_abmelde_token(make_abmelde_token(self._abo()) + "x"))
        self.assertIsNone(lese_abmelde_token("unsinn"))


class AnkuendigungAlsTextTest(SimpleTestCase):
    """``{extern}`` in der Erinnerungsmail: der Ankündigungstext wird zum Fließtext.

    ``mail_markup`` setzt Platzhalter *vor* dem Zeilen- und Inline-Parser ein.
    Ohne die Reduktion könnte ein Termin-Bearbeiter über ``Termin.extern`` einen
    ``{button:…:URL}`` oder ein ``[URL Name]`` in eine Mail an die Öffentlichkeit
    schmuggeln — dieselbe Gefahr, wegen der ``{beschreibung}`` dort fehlt.
    """

    def _frei(self, extern):
        from intern.models import Termin
        from intern.mailingliste import _ankuendigung_als_text

        return _ankuendigung_als_text(Termin(extern=extern))     # nicht gespeichert

    def test_html_wird_ein_absatz(self):
        self.assertEqual(
            self._frei("Eintritt frei<br>Einlass 16:30"), "Eintritt frei Einlass 16:30"
        )

    def test_link_bleibt_als_text(self):
        # Das Ziel geht verloren — der Preis für die schlanke Reduktion. Die
        # nackte URL im Text bleibt dagegen verlinkbar (siehe unten).
        self.assertEqual(
            self._frei('<a href="https://x.example/t">Tickets</a>'), "Tickets"
        )

    def test_kein_button_aus_geschweiften_klammern(self):
        self.assertNotIn("{", self._frei("{button:Kaufen:http://evil.example}"))

    def test_kein_benannter_link_aus_eckigen_klammern(self):
        self.assertNotIn("[", self._frei("[http://evil.example Phishing]"))

    def test_linktext_ist_die_url(self):
        # Der Linktext darf nicht der frei gewählte des Ankündigungstexts sein.
        from intern.mail_markup import render_mail_markup

        html, _ = render_mail_markup("{extern}", {"extern": self._frei(
            "[https://x.example Phishing]"
        )})
        self.assertNotIn(">Phishing</a>", html)
        self.assertIn('href="https://x.example"', html)

    def test_leerwert(self):
        self.assertEqual(self._frei("   "), "")
        self.assertEqual(self._frei(None), "")

    def test_fingerabdruck_trennt_adressen(self):
        """Der Schutz gegen wiederverwendete Primärschlüssel.

        Erbt ein neuer Eintrag die PK eines gelöschten, passt der Fingerabdruck
        des alten Links nicht mehr — read_abmelde_token verwirft ihn dann.
        """
        from intern.mailingliste import _fingerabdruck
        self.assertNotEqual(
            _fingerabdruck("a@example.org"), _fingerabdruck("fremd@example.org")
        )


class BestaetigtPropertyTest(SimpleTestCase):
    def test_leitet_sich_aus_dem_zeitstempel_ab(self):
        from intern.models import Auftrittsabo
        self.assertFalse(Auftrittsabo(email="x@y.z").bestaetigt)
        self.assertTrue(
            Auftrittsabo(email="x@y.z", bestaetigt_am=datetime(2026, 1, 1)).bestaetigt
        )


class GetConfigListTest(SimpleTestCase):
    def test_trennt_und_raeumt_auf(self):
        from intern.app_settings import get_config_list
        # Ohne DB-Zugriff: get_config fängt die Exception ab und liefert None,
        # get_config_list fällt dann auf den übergebenen Default zurück.
        self.assertEqual(get_config_list("GIBT_ES_NICHT", " 4 , ,1 "), ["4", "1"])


class KonfigCacheTest(SimpleTestCase):
    """Der Anfrage-Zwischenspeicher aus app_settings.

    Ohne Datenbank: SimpleTestCase verbietet den Zugriff, der Lesefehler landet
    also im try/except von ``_werte()`` und das Ergebnis ist das leere Dict —
    genau der Fall, in dem der Vorgabewert durchkommen muss.
    """

    def tearDown(self):
        # Der Zwischenspeicher hängt an einem threading.local, das die übrigen
        # Tests im selben Thread weiterbenutzen.
        app_settings.cache_verwerfen()

    def test_ausserhalb_einer_anfrage_kein_zwischenspeicher(self):
        app_settings.cache_verwerfen()
        self.assertIsNone(app_settings._werte())

    def test_innerhalb_einer_anfrage_wird_gelesen(self):
        app_settings.cache_anlegen()
        self.assertEqual(app_settings._werte(), {})

    def test_vorgabewert_kommt_durch(self):
        app_settings.cache_anlegen()
        self.assertEqual(app_settings.get_config("GIBT_ES_NICHT", "vorgabe"), "vorgabe")

    def test_gelesen_wird_aus_dem_zwischenspeicher(self):
        app_settings.cache_anlegen()
        app_settings._lokal.werte = {"VEREINSNAME": "Testchor"}
        self.assertEqual(app_settings.get_vereinsname(), "Testchor")

    def test_umgebungsvariable_schlaegt_den_zwischenspeicher(self):
        app_settings.cache_anlegen()
        app_settings._lokal.werte = {"VEREINSNAME": "Aus der Tabelle"}
        with mock.patch.dict(os.environ, {"VEREINSNAME": "Aus der Umgebung"}):
            self.assertEqual(app_settings.get_vereinsname(), "Aus der Umgebung")

    def test_leeren_erzwingt_neulesen(self):
        app_settings.cache_anlegen()
        app_settings._lokal.werte = {"VEREINSNAME": "Testchor"}
        app_settings.cache_leeren()
        self.assertIs(app_settings._lokal.werte, app_settings._UNGELESEN)

    def test_leeren_schaltet_ausserhalb_einer_anfrage_nichts_ein(self):
        # Sonst finge ein Management-Kommando, das die Konfiguration schreibt,
        # ab diesem Moment an zwischenzuspeichern — und bliebe auf dem Stand.
        app_settings.cache_verwerfen()
        app_settings.cache_leeren()
        self.assertIsNone(app_settings._werte())

    def test_kontextmanager_puffert_und_raeumt_auf(self):
        app_settings.cache_verwerfen()
        with app_settings.konfiguration_gepuffert():
            self.assertIsNotNone(app_settings._werte())
        self.assertIsNone(app_settings._werte())

    def test_kontextmanager_laesst_eine_laufende_anfrage_unberuehrt(self):
        # Verschachtelt in einer Anfrage darf sein finally den Zwischenspeicher
        # nicht wegwerfen — der Rest der Anfrage liefe sonst wieder auf
        # Einzelabfragen.
        app_settings.cache_anlegen()
        app_settings._lokal.werte = {"VEREINSNAME": "Testchor"}
        with app_settings.konfiguration_gepuffert():
            self.assertEqual(app_settings.get_vereinsname(), "Testchor")
        self.assertEqual(app_settings.get_vereinsname(), "Testchor")

    def test_kontextmanager_raeumt_auch_nach_einem_fehler_auf(self):
        # Ein abgebrochener Versand darf den Puffer nicht stehen lassen: das
        # Kommando laeuft als Dauerschleife weiter.
        app_settings.cache_verwerfen()
        with self.assertRaises(RuntimeError):
            with app_settings.konfiguration_gepuffert():
                raise RuntimeError("Versand fehlgeschlagen")
        self.assertIsNone(app_settings._werte())

    def test_signale_sind_verbunden(self):
        # Prüft die Verdrahtung in signals.py, nicht nur die Funktionen.
        app_settings.cache_verwerfen()
        request_started.send(sender=self.__class__)
        self.assertIsNotNone(app_settings._werte())
        request_finished.send(sender=self.__class__)
        self.assertIsNone(app_settings._werte())


class ClientIpTest(SimpleTestCase):
    """_client_ip() trägt die Drosseln und Auftrittsabo.bestaetigt_ip.

    Ein Stellvertreter genügt — die Funktion liest nur ``request.META``.
    """

    def _ip(self, **meta):
        from intern.views.auth import _client_ip
        return _client_ip(SimpleNamespace(META=meta))

    def test_einzelner_eintrag(self):
        self.assertEqual(self._ip(HTTP_X_FORWARDED_FOR="203.0.113.9"), "203.0.113.9")

    def test_letzter_eintrag_gewinnt(self):
        # Ein vom Client gefälschter Vorspann steht immer weiter vorn: haproxy
        # hängt seinen Eintrag an, nginx reicht nur diesen weiter.  Würde hier
        # der erste Eintrag genommen, könnte sich jeder eine IP aussuchen.
        self.assertEqual(
            self._ip(HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.9"), "203.0.113.9"
        )

    def test_leerraum_wird_entfernt(self):
        self.assertEqual(self._ip(HTTP_X_FORWARDED_FOR="  203.0.113.9  "), "203.0.113.9")

    def test_ohne_header_remote_addr(self):
        self.assertEqual(self._ip(REMOTE_ADDR="198.51.100.7"), "198.51.100.7")

    def test_leerer_header_faellt_auf_remote_addr_zurueck(self):
        self.assertEqual(
            self._ip(HTTP_X_FORWARDED_FOR="", REMOTE_ADDR="198.51.100.7"),
            "198.51.100.7",
        )

    def test_gar_nichts(self):
        # bestaetigt_ip ist ein GenericIPAddressField — auftritte.py macht aus
        # dem leeren String per ``or None`` ein NULL.
        self.assertEqual(self._ip(), "")


def _ordner(pk, owner_id=None, parent=None):
    """Stellvertreter für einen filer-Ordner — ``_ziel_owner`` liest nur diese drei."""
    return SimpleNamespace(pk=pk, owner_id=owner_id, parent=parent)


class ZielOwnerTest(SimpleTestCase):
    """Die Besitzsuche beim Löschen eines Mitglieds (``besitz_uebertragen``).

    Ohne Datenbank testbar, weil ``_ziel_owner`` von der Ordnerzeile nur ``pk``,
    ``owner_id`` und ``parent`` anfasst.
    """

    WEG = 7        # das Mitglied, das verschwindet
    FALLBACK = 99  # die löschende Person

    def _ziel(self, ordner, cache=None):
        return _ziel_owner(ordner, self.WEG, self.FALLBACK, cache if cache is not None else {})

    def test_uebergeordneter_ordner_hat_besitzer(self):
        self.assertEqual(self._ziel(_ordner(1, owner_id=42)), 42)

    def test_besitzloser_ordner_wird_uebersprungen(self):
        # Ein Ordner ohne owner (etwa nach einer früheren Löschung) ist kein Ziel.
        self.assertEqual(self._ziel(_ordner(2, owner_id=None, parent=_ordner(1, owner_id=42))), 42)

    def test_vorfahr_gehoert_ebenfalls_dem_mitglied(self):
        kette = _ordner(3, owner_id=self.WEG, parent=_ordner(2, owner_id=self.WEG, parent=_ordner(1, owner_id=42)))
        self.assertEqual(self._ziel(kette), 42)

    def test_ganze_kette_gehoert_dem_mitglied(self):
        kette = _ordner(2, owner_id=self.WEG, parent=_ordner(1, owner_id=self.WEG))
        self.assertEqual(self._ziel(kette), self.FALLBACK)

    def test_ohne_ordner(self):
        # Datei auf oberster Ebene: filer erlaubt folder=None.
        self.assertEqual(self._ziel(None), self.FALLBACK)

    def test_zyklus_terminiert(self):
        a = _ordner(1, owner_id=self.WEG)
        b = _ordner(2, owner_id=self.WEG, parent=a)
        a.parent = b
        self.assertEqual(self._ziel(a), self.FALLBACK)

    def test_cache_deckt_die_ganze_kette_ab(self):
        cache = {}
        kette = _ordner(2, owner_id=None, parent=_ordner(1, owner_id=42))
        self._ziel(kette, cache)
        self.assertEqual(cache, {2: 42, 1: 42})

    def test_cache_wird_benutzt(self):
        # Zweiter Aufruf darf die Kette nicht noch einmal hochlaufen — bei einem
        # Ordner voller Dateien wäre das je Datei eine Abfrage pro Ebene.
        cache = {5: 42}
        gesperrt = SimpleNamespace(pk=5, owner_id=self.WEG)  # kein .parent
        self.assertEqual(self._ziel(gesperrt, cache), 42)


class HilfeTagTest(SimpleTestCase):
    """Die Erklärungstexte haben genau eine Quelle: den help_text am Model.

    Schlägt an, sobald jemand einen Text ins Template kopiert — beide Wege des
    Tags müssen denselben Text liefern.
    """

    FELDER = ("anwesenheit", "extern", "repertoire")

    def _render(self, ausdruck, **kontext):
        return Template("{% load ui_tags %}" + ausdruck).render(Context(kontext))

    def _help_text(self, feld):
        from intern.models import Termin

        return str(Termin._meta.get_field(feld).help_text)

    def test_texte_sind_gesetzt(self):
        for feld in self.FELDER:
            with self.subTest(feld=feld):
                self.assertTrue(self._help_text(feld).strip(), feld + " ohne help_text")

    def test_string_ziel_liest_den_help_text(self):
        for feld in self.FELDER:
            with self.subTest(feld=feld):
                html = self._render('{%% hilfe "Termin.%s" %%}' % feld)
                self.assertIn('data-hilfe="' + escape(self._help_text(feld)) + '"', html)

    def test_bound_field_liest_denselben_text(self):
        from intern.forms import TerminForm

        form = TerminForm()
        for feld in self.FELDER:
            with self.subTest(feld=feld):
                html = self._render("{%% hilfe form.%s %%}" % feld, form=form)
                self.assertIn('data-hilfe="' + escape(self._help_text(feld)) + '"', html)

    def test_icon_sendet_das_formular_nicht_ab(self):
        # Das Icon steht in <form>-Elementen; ohne type="button" waere es ein Submit.
        self.assertIn('type="button"', self._render('{% hilfe "Termin.repertoire" %}'))


# ---------------------------------------------------------------------------
# CardDAV
#
# Alles Folgende ist datenbankfrei, weil die Serialisierung und der XML-Bau
# reine Funktionen sind (siehe intern/carddav/__init__.py). Geprueft wird
# gegen SimpleNamespace-Stellvertreter; was wirklich die Datenbank braucht,
# steckt in intern/carddav/daten.py und bleibt hier aussen vor.
# ---------------------------------------------------------------------------


def _mitglied(**abweichend):
    """Stellvertreter fuer ein Mitglied; kontakt_daten liest nur Attribute."""
    felder = dict(
        pk=12, first_name="Ann-Kathrin", last_name="Müller-Groß",
        username="amueller", email="a@example.org",
        telefon="069 1", telefon_mobil="0170 2", telefon_job="",
        telefon_job_mobil="", fax="",
        strasse="Hauptstr. 1", plz="60311", ort="Frankfurt",
        breite=50.11, laenge=8.68,
        geburtstag=date(1985, 3, 7), xmpp="a@jabber.de",
        text="Singt seit Ewigkeiten.", date_joined=datetime(2012, 4, 1),
    )
    felder.update(abweichend)
    return SimpleNamespace(**felder)


def _karte(mitglied=None, sichtbar=None, **kwargs):
    from intern.carddav import vcard

    daten = vcard.kontakt_daten(
        mitglied or _mitglied(), sichtbar or (lambda f: True), **kwargs
    )
    return daten, vcard.vcard_text(daten)


class VCardFaltungTest(SimpleTestCase):
    def test_kurze_zeile_bleibt_ungefaltet(self):
        from intern.carddav.vcard import fold

        self.assertEqual(fold("x" * 75), "x" * 75)

    def test_ab_76_oktetten_wird_gefaltet(self):
        from intern.carddav.vcard import fold

        self.assertIn("\r\n ", fold("x" * 76))

    def test_folgezeile_beginnt_mit_genau_einem_leerzeichen(self):
        from intern.carddav.vcard import fold

        for zeile in fold("x" * 400).split("\r\n")[1:]:
            self.assertTrue(zeile.startswith(" "))
            self.assertFalse(zeile.startswith("  "))

    def test_umlaute_werden_nie_mitten_im_zeichen_getrennt(self):
        # Der eigentliche Grund fuer die byteweise Zaehlung: ein 'ä' belegt zwei
        # Oktette, und ein Schnitt dazwischen macht die ganze Karte unlesbar.
        from intern.carddav.vcard import fold

        for laenge in (37, 38, 39, 100):
            with self.subTest(laenge=laenge):
                original = "ä" * laenge
                gefaltet = fold(original)
                self.assertEqual(gefaltet.replace("\r\n ", ""), original)
                for zeile in gefaltet.split("\r\n"):
                    self.assertLessEqual(len(zeile.encode("utf-8")), 75)


class VCardEscapeTest(SimpleTestCase):
    def test_sonderzeichen(self):
        from intern.carddav.vcard import escape_text

        self.assertEqual(escape_text("a,b"), "a\\,b")
        self.assertEqual(escape_text("a;b"), "a\\;b")
        self.assertEqual(escape_text("a\\b"), "a\\\\b")
        self.assertEqual(escape_text("a\nb"), "a\\nb")
        self.assertEqual(escape_text("a\r\nb"), "a\\nb")

    def test_komponententrenner_bleibt_roh(self):
        from intern.carddav.vcard import strukturiert

        # Das Komma IN der Komponente wird escaped, das trennende ; nicht.
        self.assertEqual(strukturiert(["a,b", "c"]), "a\\,b;c")

    def test_listentrenner_bleibt_roh(self):
        from intern.carddav.vcard import liste

        self.assertEqual(liste(["Chor, e.V.", "Sopran"]), "Chor\\, e.V.,Sopran")


class VCardStrukturTest(SimpleTestCase):
    def test_rahmen_und_zeilenenden(self):
        _daten, text = _karte()
        self.assertTrue(text.startswith("BEGIN:VCARD\r\nVERSION:3.0\r\n"))
        self.assertTrue(text.endswith("END:VCARD\r\n"))
        self.assertNotIn("\n", text.replace("\r\n", ""))

    def test_n_hat_fuenf_komponenten(self):
        _daten, text = _karte()
        n = [z for z in text.split("\r\n") if z.startswith("N:")][0]
        self.assertEqual(n.count(";"), 4)

    def test_uid_ist_vorhanden_und_stabil(self):
        from intern.carddav.vcard import uid_fuer

        _daten, text = _karte()
        self.assertIn("UID:" + uid_fuer(12), text)

    def test_keine_zeile_ueber_75_oktette(self):
        _daten, text = _karte()
        for zeile in text.split("\r\n"):
            self.assertLessEqual(len(zeile.encode("utf-8")), 75)


class VCardMappingTest(SimpleTestCase):
    def test_felder_landen_mit_den_richtigen_typen(self):
        _daten, text = _karte(organisation="Just Gospel", stimme_label="Sopran",
                              basis_url="https://x.de")
        for erwartet in (
            "FN:Ann-Kathrin Müller-Groß",
            "NICKNAME:amueller",
            "ORG:Just Gospel",
            "TITLE:Sopran",
            "CATEGORIES:Just Gospel,Sopran",
            "EMAIL;TYPE=INTERNET,HOME,PREF:a@example.org",
            "TEL;TYPE=HOME,VOICE,PREF:069 1",
            "TEL;TYPE=CELL,VOICE:0170 2",
            "ADR;TYPE=HOME:;;Hauptstr. 1;Frankfurt;;60311;",
            "GEO:50.11;8.68",
            "BDAY:1985-03-07",
            "IMPP;X-SERVICE-TYPE=XMPP;TYPE=HOME:xmpp:a@jabber.de",
            "X-JABBER:a@jabber.de",
            "URL:https://x.de/intern/mitglied/12/",
        ):
            with self.subTest(erwartet=erwartet):
                self.assertIn(erwartet, text)

    def test_leere_felder_erzeugen_keine_zeile(self):
        # Eine leere TEL-Zeile legt auf Android einen leeren Eintrag an.
        _daten, text = _karte()
        self.assertNotIn("TEL;TYPE=WORK", text)
        self.assertNotIn("TEL;TYPE=HOME,FAX", text)

    def test_pref_nur_bei_der_ersten_nummer(self):
        _daten, text = _karte()
        self.assertEqual(text.count("PREF"), 2)  # einmal TEL, einmal EMAIL

    def test_eintrittsjahr_steht_in_der_notiz(self):
        _daten, text = _karte()
        self.assertIn("Mitglied seit 2012", text)


class VCardPrivacyTest(SimpleTestCase):
    VERBORGEN = {"telefon", "telefon_mobil", "geburtstag", "email",
                 "strasse", "plz", "ort"}

    def _ohne(self, verborgen):
        return _karte(sichtbar=lambda f: f not in verborgen)[1]

    def test_verborgene_felder_fehlen(self):
        text = self._ohne(self.VERBORGEN)
        for verboten in ("TEL", "EMAIL", "BDAY", "ADR", "GEO"):
            with self.subTest(verboten=verboten):
                self.assertFalse(
                    any(z.startswith(verboten) for z in text.split("\r\n"))
                )

    def test_sichtbares_bleibt(self):
        text = self._ohne(self.VERBORGEN)
        self.assertIn("FN:Ann-Kathrin Müller-Groß", text)
        self.assertIn("X-JABBER:", text)

    def test_teilweise_verborgene_adresse_behaelt_den_rest(self):
        text = self._ohne({"plz"})
        self.assertIn("ADR;TYPE=HOME:;;Hauptstr. 1;Frankfurt;;;", text)

    def test_geo_haengt_an_der_sichtbarkeit_der_anschrift(self):
        # Sonst liesse sich die verborgene Adresse aus den Koordinaten
        # zurueckrechnen.
        self.assertNotIn("GEO:", self._ohne({"plz"}))


class CarddavSichtbarTest(SimpleTestCase):
    """Der Export kennt bewusst keinen Admin-Bonus."""

    def test_verwaltungsrecht_hebt_die_verbergung_nicht_auf(self):
        from intern.carddav.daten import carddav_sichtbar

        mitglied = SimpleNamespace(private_fields=["telefon", "geburtstag"])
        self.assertFalse(carddav_sichtbar(mitglied, "telefon"))
        self.assertTrue(carddav_sichtbar(mitglied, "email"))

    def test_leere_liste_gibt_alles_frei(self):
        from intern.carddav.daten import carddav_sichtbar

        for leer in ([], None):
            with self.subTest(leer=leer):
                self.assertTrue(
                    carddav_sichtbar(SimpleNamespace(private_fields=leer), "telefon")
                )


class AdressbuchOptOutTest(SimpleTestCase):
    """Der Widerspruch gegen den ganzen Datensatz, nicht gegen einzelne Felder.

    Der Filter selbst sitzt in ``mitglieder_qs`` und braucht Zeilen — ohne
    Testdatenbank nicht pruefbar (siehe dortigen Docstring). Geprueft wird hier
    alles, was ihn umgibt und still falsch werden koennte.
    """

    def _feld(self):
        from intern.models import User

        return User._meta.get_field("adressbuch_verborgen")

    def test_standard_laesst_alle_im_adressbuch(self):
        # Ein True als Default leerte auf einen Schlag jedes Adressbuch.
        self.assertIs(self._feld().default, False)

    def test_help_text_ist_gesetzt(self):
        # Der Erklaerungstext lebt am Model, nie im Template ({% hilfe %}).
        self.assertTrue(str(self._feld().help_text).strip())

    def test_hilfe_tag_findet_das_feld(self):
        # mitglied_edit.html nutzt die String-Form; ein Tippfehler faellt sonst
        # erst beim Rendern der Seite auf.
        from django.template import Context, Template
        from django.utils.html import escape

        html = Template(
            '{% load ui_tags %}{% hilfe "User.adressbuch_verborgen" %}'
        ).render(Context({}))
        self.assertIn('data-hilfe="' + escape(str(self._feld().help_text)) + '"', html)

    def test_ist_kein_feld_fuer_feld_schalter(self):
        from intern.mitglied_felder import PRIVACY_FIELDS

        # Stuende es dort, baute UserEditForm ein sinnloses priv_-Haekchen dazu.
        self.assertNotIn("adressbuch_verborgen", PRIVACY_FIELDS)

    def test_nicht_in_meta_fields(self):
        """Sonst loescht ein fremdes Formular den Widerspruch stillschweigend.

        Eine nicht gerenderte Checkbox fehlt im POST, ``BooleanField`` liefert
        dann ``False``, und ``construct_instance`` schreibt es weg.
        """
        from intern.forms import UserEditForm

        self.assertNotIn("adressbuch_verborgen", UserEditForm.Meta.fields)

    def test_steht_im_aenderungsprotokoll(self):
        from intern.signals import _AUDIT_FIELDS
        from intern.tables import _CHANGELOG_FIELD_LABELS
        from intern.views.aenderungen import FIELD_LABELS

        self.assertIn("adressbuch_verborgen", _AUDIT_FIELDS["User"])
        for karte in (FIELD_LABELS, _CHANGELOG_FIELD_LABELS):
            with self.subTest(karte=karte):
                self.assertIn("adressbuch_verborgen", karte)

    def test_haekchen_nur_im_eigenen_profil_bei_aktivem_dienst(self):
        from intern.forms import UserEditForm
        from intern.models import User

        instanz = User(adressbuch_verborgen=True)
        for privacy, adressbuch, erwartet in [
            (False, False, False),   # fremdes Profil
            (True, False, False),    # eigenes Profil, CardDAV aus
            (True, True, True),      # eigenes Profil, CardDAV an
        ]:
            with self.subTest(privacy=privacy, adressbuch=adressbuch):
                form = UserEditForm(
                    instance=instanz,
                    with_privacy=privacy,
                    mit_adressbuch=adressbuch,
                )
                self.assertIs("adressbuch_verborgen" in form.fields, erwartet)
                if erwartet:
                    self.assertTrue(form.fields["adressbuch_verborgen"].initial)


class EtagTest(SimpleTestCase):
    def _etag(self, mitglied=None, sichtbar=None, **kwargs):
        from intern.carddav import vcard

        return vcard.etag(
            vcard.kontakt_daten(mitglied or _mitglied(),
                                sichtbar or (lambda f: True), **kwargs)
        )

    def test_gleiche_eingabe_gleicher_etag(self):
        self.assertEqual(self._etag(), self._etag())

    def test_ist_ein_starker_etag(self):
        tag = self._etag()
        self.assertTrue(tag.startswith('"') and tag.endswith('"'))

    def test_jedes_sichtbare_feld_wirkt(self):
        for feld, wert in [("first_name", "Anders"), ("telefon", "999"),
                           ("ort", "Mainz"), ("xmpp", "b@j.de")]:
            with self.subTest(feld=feld):
                self.assertNotEqual(
                    self._etag(), self._etag(_mitglied(**{feld: wert}))
                )

    def test_foto_wechsel_wirkt(self):
        self.assertNotEqual(
            self._etag(foto_kennung="1:aa:10"),
            self._etag(foto_kennung="1:bb:10"),
        )

    def test_serialisierungsstand_wirkt(self):
        # Ohne diesen Anteil behielten alle Clients nach einer Aenderung an
        # vcard.py fuer immer ihre alten Karten.
        from intern.carddav import vcard

        alt = self._etag()
        with mock.patch.object(vcard, "_SERIALISIERUNG", "v2"):
            self.assertNotEqual(alt, self._etag())

    def test_verborgenes_feld_veraendert_den_etag_nicht(self):
        # Sonst liesse sich aus dem ETag ablesen, dass es das Feld gibt.
        ohne = lambda f: f != "telefon"  # noqa: E731
        self.assertEqual(
            self._etag(_mitglied(telefon="111"), ohne),
            self._etag(_mitglied(telefon="222"), ohne),
        )


class CtagTest(SimpleTestCase):
    def setUp(self):
        from intern.carddav.vcard import ctag

        self.ctag = ctag

    def test_reihenfolge_ist_egal(self):
        self.assertEqual(
            self.ctag([(1, '"a"'), (2, '"b"')]),
            self.ctag([(2, '"b"'), (1, '"a"')]),
        )

    def test_abgang_wirkt(self):
        self.assertNotEqual(
            self.ctag([(1, '"a"'), (2, '"b"')]), self.ctag([(1, '"a"')])
        )

    def test_geaenderte_karte_wirkt(self):
        self.assertNotEqual(
            self.ctag([(1, '"a"'), (2, '"b"')]),
            self.ctag([(1, '"a"'), (2, '"c"')]),
        )


class DavParseTest(SimpleTestCase):
    def test_propfind_liefert_die_angefragten_namen(self):
        from intern.dav import xml as dav

        rumpf = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b'<D:propfind xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/">'
            b"<D:prop><D:resourcetype/><CS:getctag/></D:prop></D:propfind>"
        )
        self.assertEqual(
            dav.parse_propfind(rumpf),
            [dav.qn(dav.NS_DAV, "resourcetype"), dav.qn(dav.NS_CS, "getctag")],
        )

    def test_leerer_rumpf_und_allprop_bedeuten_alles(self):
        from intern.dav import xml as dav

        self.assertIsNone(dav.parse_propfind(b""))
        self.assertIsNone(
            dav.parse_propfind(b'<D:propfind xmlns:D="DAV:"><D:allprop/></D:propfind>')
        )

    def test_multiget_liefert_die_hrefs(self):
        from intern.dav import xml as dav

        rumpf = (
            b'<C:addressbook-multiget xmlns:D="DAV:" '
            b'xmlns:C="urn:ietf:params:xml:ns:carddav">'
            b"<D:prop><D:getetag/></D:prop>"
            b"<D:href>/carddav/adressbuch/7/mitglieder/12.vcf</D:href>"
            b"</C:addressbook-multiget>"
        )
        bericht = dav.parse_report(rumpf)
        self.assertEqual(bericht.art, "multiget")
        self.assertEqual(bericht.hrefs,
                         ["/carddav/adressbuch/7/mitglieder/12.vcf"])

    def test_query_mit_limit(self):
        from intern.dav import xml as dav

        rumpf = (
            b'<C:addressbook-query xmlns:D="DAV:" '
            b'xmlns:C="urn:ietf:params:xml:ns:carddav">'
            b"<D:prop><D:getetag/></D:prop><C:filter/>"
            b"<C:limit><C:nresults>5</C:nresults></C:limit>"
            b"</C:addressbook-query>"
        )
        bericht = dav.parse_report(rumpf)
        self.assertEqual((bericht.art, bericht.limit), ("query", 5))

    def test_dtd_wird_abgewiesen(self):
        # Schliesst Billion Laughs, ohne eine Bibliothek einzuziehen.
        from intern.dav import xml as dav

        with self.assertRaises(ValueError):
            dav.parse_body(
                b'<!DOCTYPE x [<!ENTITY a "aaa">]>'
                b'<D:propfind xmlns:D="DAV:"><D:prop/></D:propfind>'
            )

    def test_uebergrosser_rumpf_wird_abgewiesen(self):
        from intern.dav import xml as dav

        with self.assertRaises(ValueError):
            dav.parse_body(b"<x/>" + b" " * (256 * 1024))

    def test_kaputtes_xml_wird_abgewiesen(self):
        from intern.dav import xml as dav

        with self.assertRaises(ValueError):
            dav.parse_body(b"<nicht-geschlossen")


class MultistatusTest(SimpleTestCase):
    def _bauen(self):
        from intern.dav import xml as dav

        return dav, dav.multistatus([(
            "/carddav/adressbuch/7/mitglieder/",
            {
                dav.qn(dav.NS_CS, "getctag"): '"abc"',
                dav.qn(dav.NS_DAV, "resourcetype"): [
                    dav.element(dav.NS_DAV, "collection"),
                    dav.element(dav.NS_CARDDAV, "addressbook"),
                ],
            },
            [dav.qn(dav.NS_DAV, "sync-token")],
        )])

    def test_ist_wohlgeformt(self):
        import xml.etree.ElementTree as ET

        _dav, xml = self._bauen()
        ET.fromstring(xml)

    def test_unbekannte_property_wird_als_404_gemeldet(self):
        # Sie stillschweigend wegzulassen ist der Fehler, an dem iOS aussteigt.
        import xml.etree.ElementTree as ET

        dav, xml = self._bauen()
        antwort = ET.fromstring(xml).find(dav.qn(dav.NS_DAV, "response"))
        zustaende = sorted(
            p.find(dav.qn(dav.NS_DAV, "status")).text
            for p in antwort.findall(dav.qn(dav.NS_DAV, "propstat"))
        )
        self.assertEqual(zustaende, ["HTTP/1.1 200 OK", "HTTP/1.1 404 Not Found"])

    def test_adressbuch_ist_collection_und_addressbook(self):
        import xml.etree.ElementTree as ET

        dav, xml = self._bauen()
        rt = ET.fromstring(xml).find(".//" + dav.qn(dav.NS_DAV, "resourcetype"))
        self.assertIsNotNone(rt.find(dav.qn(dav.NS_DAV, "collection")))
        self.assertIsNotNone(rt.find(dav.qn(dav.NS_CARDDAV, "addressbook")))


class CarddavAuthKeyTest(SimpleTestCase):
    def test_schluessel_ist_stabil_und_unterscheidet(self):
        from intern.dav.auth import _cache_key

        self.assertEqual(_cache_key("a", "geheim"), _cache_key("a", "geheim"))
        self.assertNotEqual(_cache_key("a", "geheim"), _cache_key("b", "geheim"))
        self.assertNotEqual(_cache_key("a", "geheim"), _cache_key("a", "anders"))

    def test_das_passwort_steht_nicht_im_schluessel(self):
        from intern.dav.auth import _cache_key

        self.assertNotIn("geheim", _cache_key("a", "geheim"))

    def test_kennung_folgt_dem_gespeicherten_hash(self):
        # Damit eine Passwortaenderung den Eintrag sofort entwertet.
        from intern.dav.auth import _passwort_kennung

        alt = _passwort_kennung(SimpleNamespace(password="pbkdf2$alt"))
        neu = _passwort_kennung(SimpleNamespace(password="pbkdf2$neu"))
        self.assertNotEqual(alt, neu)


# ---------------------------------------------------------------------------
# CalDAV
#
# Dieselbe Bauart wie oben: die iCalendar-Serialisierung ist rein, die Zeitzone
# und der DTSTAMP werden hereingereicht. Was wirklich die Datenbank braucht,
# steckt in intern/caldav/daten.py und bleibt hier aussen vor.
# ---------------------------------------------------------------------------

_ZONE = ZoneInfo("Europe/Berlin")
_STAND = datetime(2026, 8, 3, 12, 0, 0)


def _ort(**abweichend):
    felder = dict(name="Heilig-Geist-Kirche", strasse="Berger Weg 3",
                  plz="60389", ort="Frankfurt", breite=50.15, laenge=8.72)
    felder.update(abweichend)
    return SimpleNamespace(**felder)


def _kalendertermin(**abweichend):
    """Stellvertreter fuer einen Termin; termin_daten liest nur Attribute."""
    felder = dict(
        pk=42, kurz="Chorprobe", lang="", datum=datetime(2026, 1, 7, 20, 0),
        datum_bis=None, ort=None, repertoire=False,
    )
    felder.update(abweichend)
    return SimpleNamespace(**felder)


def _vevent(termin=None, **kwargs):
    from intern.caldav import ical

    daten = ical.termin_daten(termin or _kalendertermin(), zone=_ZONE, **kwargs)
    return daten, ical.vcalendar_text(daten, stand=_STAND)


class ICalZeitTest(SimpleTestCase):
    def test_winterzeit_wird_nach_utc_gerechnet(self):
        # 20:00 MEZ ist 19:00 UTC. Ohne Umrechnung stuende hier eine Zeit ohne
        # Zonenangabe, die jedes Geraet anders auslegt.
        _daten, text = _vevent()
        self.assertIn("DTSTART:20260107T190000Z", text)

    def test_sommerzeit_wird_nach_utc_gerechnet(self):
        _daten, text = _vevent(_kalendertermin(datum=datetime(2026, 8, 23, 18, 30)))
        self.assertIn("DTSTART:20260823T163000Z", text)

    def test_ohne_endzeit_gilt_die_standarddauer(self):
        _daten, text = _vevent()
        self.assertIn("DTEND:20260107T210000Z", text)

    def test_endzeit_vor_beginn_wird_ignoriert(self):
        # Kaputte Altdaten duerfen kein VEVENT mit negativer Dauer erzeugen.
        _daten, text = _vevent(_kalendertermin(
            datum_bis=datetime(2026, 1, 7, 18, 0)))
        self.assertIn("DTEND:20260107T210000Z", text)


class ICalGanztagTest(SimpleTestCase):
    def test_mitternacht_ohne_ende_wird_ganztaegig(self):
        # 00:00 ist die Kennung fuer "ohne Uhrzeit": das Formular setzt
        # datetime.min.time(), wenn nichts eingegeben wurde.
        daten, text = _vevent(_kalendertermin(datum=datetime(2026, 11, 8, 0, 0)))
        self.assertTrue(daten["ganztaegig"])
        self.assertIn("DTSTART;VALUE=DATE:20261108", text)

    def test_dtend_ist_bei_value_date_exklusiv(self):
        _daten, text = _vevent(_kalendertermin(datum=datetime(2026, 11, 8, 0, 0)))
        self.assertIn("DTEND;VALUE=DATE:20261109", text)

    def test_mehrtaegig_reicht_bis_einschliesslich_datum_bis(self):
        # Dieselbe Lesart wie die Monatsansicht: das Band endet auf datum_bis.
        _daten, text = _vevent(_kalendertermin(
            datum=datetime(2026, 11, 6, 0, 0),
            datum_bis=datetime(2026, 11, 8, 0, 0)))
        self.assertIn("DTSTART;VALUE=DATE:20261106", text)
        self.assertIn("DTEND;VALUE=DATE:20261109", text)

    def test_eine_uhrzeit_am_ende_macht_es_zeitgebunden(self):
        daten, _text = _vevent(_kalendertermin(
            datum=datetime(2026, 11, 6, 0, 0),
            datum_bis=datetime(2026, 11, 6, 12, 0)))
        self.assertFalse(daten["ganztaegig"])


class ICalInhaltTest(SimpleTestCase):
    def test_ort_wird_zu_einer_location_zeile(self):
        _daten, text = _vevent(_kalendertermin(ort=_ort()))
        self.assertIn(
            "LOCATION:Heilig-Geist-Kirche\\, Berger Weg 3\\, 60389 Frankfurt",
            text,
        )

    def test_leere_ortsteile_hinterlassen_kein_komma(self):
        _daten, text = _vevent(_kalendertermin(
            ort=_ort(strasse="", plz="", ort="")))
        self.assertIn("LOCATION:Heilig-Geist-Kirche\r\n", text)

    def test_koordinaten_werden_mit_semikolon_getrennt(self):
        _daten, text = _vevent(_kalendertermin(ort=_ort()))
        self.assertIn("GEO:50.15;8.72", text)

    def test_ohne_ort_keine_location_und_kein_geo(self):
        _daten, text = _vevent()
        self.assertNotIn("LOCATION", text)
        self.assertNotIn("GEO", text)

    def test_auftritt_bekommt_eine_eigene_kategorie(self):
        _daten, text = _vevent(_kalendertermin(repertoire=True))
        self.assertIn("CATEGORIES:Auftritt", text)
        _daten, text = _vevent()
        self.assertIn("CATEGORIES:Termin", text)

    def test_beschreibung_wird_escaped_und_gefaltet(self):
        lang = "Erste Zeile\nZweite, mit Komma; und Semikolon " + "ä" * 60
        _daten, text = _vevent(_kalendertermin(lang=lang))
        self.assertIn("\\n", text)
        self.assertIn("\\,", text)
        self.assertIn("\\;", text)
        for zeile in text.split("\r\n"):
            self.assertLessEqual(len(zeile.encode("utf-8")), 75)

    def test_rahmen_und_zeilenenden(self):
        _daten, text = _vevent()
        self.assertTrue(text.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(text.endswith("END:VCALENDAR\r\n"))
        self.assertIn("VERSION:2.0", text)
        self.assertIn("UID:cantorhub-termin-42", text)
        self.assertIn("DTSTAMP:20260803T120000Z", text)

    def test_url_zeigt_auf_die_terminseite(self):
        _daten, text = _vevent(basis_url="https://portal.example.org")
        self.assertIn("URL:https://portal.example.org/intern/termin/42/", text)


class ICalGeburtstagTest(SimpleTestCase):
    def _bauen(self, **abweichend):
        from intern.caldav import ical

        felder = dict(pk=7, first_name="Ann-Kathrin", last_name="Müller-Groß",
                      geburtstag=date(1976, 11, 10))
        felder.update(abweichend)
        daten = ical.geburtstag_daten(SimpleNamespace(**felder))
        return daten, ical.vcalendar_text(daten, stand=_STAND)

    def test_wiederkehrend_und_ganztaegig(self):
        _daten, text = self._bauen()
        self.assertIn("DTSTART;VALUE=DATE:19761110", text)
        self.assertIn("DTEND;VALUE=DATE:19761111", text)
        self.assertIn("RRULE:FREQ=YEARLY", text)

    def test_zeigt_niemanden_als_beschaeftigt(self):
        # Ein Geburtstag blockiert keinen Termin.
        _daten, text = self._bauen()
        self.assertIn("TRANSP:TRANSPARENT", text)

    def test_name_steht_im_titel(self):
        _daten, text = self._bauen()
        self.assertIn("SUMMARY:Ann-Kathrin Müller-Groß hat Geburtstag", text)

    def test_uid_haengt_am_mitglied_nicht_am_datum(self):
        daten, _text = self._bauen()
        self.assertEqual(daten["uid"], "cantorhub-geburtstag-7")


class ICalETagTest(SimpleTestCase):
    def test_geaenderter_titel_aendert_den_etag(self):
        from intern.caldav import ical

        a = ical.etag(_vevent()[0])
        b = ical.etag(_vevent(_kalendertermin(kurz="Generalprobe"))[0])
        self.assertNotEqual(a, b)

    def test_gleiche_daten_ergeben_denselben_etag(self):
        from intern.caldav import ical

        self.assertEqual(ical.etag(_vevent()[0]), ical.etag(_vevent()[0]))

    def test_etag_ist_stark_und_in_anfuehrungszeichen(self):
        from intern.caldav import ical

        tag = ical.etag(_vevent()[0])
        self.assertTrue(tag.startswith('"') and tag.endswith('"'))
        self.assertNotIn("W/", tag)

    def test_ctag_bemerkt_einen_zugang(self):
        from intern.caldav import ical

        self.assertNotEqual(
            ical.ctag([(1, '"a"')]),
            ical.ctag([(1, '"a"'), (2, '"b"')]),
        )


class CalDavReportTest(SimpleTestCase):
    def test_calendar_multiget_wird_erkannt(self):
        from intern.dav import xml as dav

        rumpf = (
            b'<CAL:calendar-multiget xmlns:D="DAV:" '
            b'xmlns:CAL="urn:ietf:params:xml:ns:caldav">'
            b"<D:prop><D:getetag/></D:prop>"
            b"<D:href>/caldav/kalender/7/termine/42.ics</D:href>"
            b"</CAL:calendar-multiget>"
        )
        bericht = dav.parse_report(rumpf)
        self.assertEqual(bericht.art, "multiget")
        self.assertEqual(bericht.hrefs, ["/caldav/kalender/7/termine/42.ics"])

    def test_comp_filter_nennt_die_gesuchte_komponente(self):
        # Fragt ein Client nach VTODO, darf er keine Termine bekommen.
        from intern.dav import xml as dav

        rumpf = (
            b'<CAL:calendar-query xmlns:D="DAV:" '
            b'xmlns:CAL="urn:ietf:params:xml:ns:caldav">'
            b"<D:prop><D:getetag/></D:prop><CAL:filter>"
            b'<CAL:comp-filter name="VCALENDAR">'
            b'<CAL:comp-filter name="VTODO"/>'
            b"</CAL:comp-filter></CAL:filter></CAL:calendar-query>"
        )
        bericht = dav.parse_report(rumpf)
        self.assertEqual(bericht.art, "query")
        # VCALENDAR ist nur der Rahmen und faellt raus.
        self.assertEqual(bericht.komponenten, ("VTODO",))

    def test_time_range_wird_gelesen(self):
        from intern.dav import xml as dav

        rumpf = (
            b'<CAL:calendar-query xmlns:D="DAV:" '
            b'xmlns:CAL="urn:ietf:params:xml:ns:caldav">'
            b"<D:prop><D:getetag/></D:prop><CAL:filter>"
            b'<CAL:comp-filter name="VCALENDAR">'
            b'<CAL:comp-filter name="VEVENT">'
            b'<CAL:time-range start="20261101T000000Z" end="20261201T000000Z"/>'
            b"</CAL:comp-filter></CAL:comp-filter>"
            b"</CAL:filter></CAL:calendar-query>"
        )
        bericht = dav.parse_report(rumpf)
        self.assertEqual(
            bericht.zeitraum,
            (datetime(2026, 11, 1), datetime(2026, 12, 1)),
        )

    def test_unlesbarer_zeitraum_bricht_nicht_ab(self):
        # Ein kaputter Filter darf den Abgleich nicht beenden; er entfaellt dann.
        from intern.dav import xml as dav

        rumpf = (
            b'<CAL:calendar-query xmlns:D="DAV:" '
            b'xmlns:CAL="urn:ietf:params:xml:ns:caldav">'
            b'<CAL:filter><CAL:time-range start="morgen"/></CAL:filter>'
            b"</CAL:calendar-query>"
        )
        self.assertEqual(dav.parse_report(rumpf).zeitraum, (None, None))

    def test_carddav_report_bleibt_unberuehrt(self):
        from intern.dav import xml as dav

        rumpf = (
            b'<C:addressbook-query xmlns:D="DAV:" '
            b'xmlns:C="urn:ietf:params:xml:ns:carddav"><C:filter/>'
            b"</C:addressbook-query>"
        )
        bericht = dav.parse_report(rumpf)
        self.assertEqual((bericht.art, bericht.komponenten, bericht.zeitraum),
                         ("query", (), None))


class KonfigGruppenTest(SimpleTestCase):
    """Gruppenzuordnung der Konfigurationsschlüssel — DB-frei."""

    def _defaults_keys(self):
        from intern.apps import _CONFIG_DEFAULTS
        return {row[0] for row in _CONFIG_DEFAULTS}

    def test_jeder_default_schluessel_hat_eine_gruppe(self):
        # Der Regressionswächter: ein neuer Schlüssel in apps.py ohne
        # Gruppeneintrag fällt hier auf, statt still in „Sonstiges" zu landen.
        from intern.konfig_gruppen import zuordnung
        for key in self._defaults_keys():
            self.assertNotEqual(
                zuordnung(key), "sonstiges",
                msg=f"Schlüssel {key!r} hat keine Gruppeneintragung",
            )

    def test_exakte_schluessel_existieren_und_sind_eindeutig(self):
        from intern.konfig_gruppen import GRUPPEN
        defaults = self._defaults_keys()
        gesehen = {}
        for g in GRUPPEN:
            for k in g.keys:
                self.assertIn(
                    k, defaults,
                    msg=f"Exakter Schlüssel {k!r} in Gruppe {g.id!r} fehlt in _CONFIG_DEFAULTS",
                )
                self.assertNotIn(
                    k, gesehen,
                    msg=f"Schlüssel {k!r} steht in zwei Gruppen: {gesehen.get(k)!r} und {g.id!r}",
                )
                gesehen[k] = g.id

    def test_exakte_schluessel_in_keiner_zwei_gruppen(self):
        # Verdoppeltungsschutz auch über die Ableitung (_EXAKT) geprüft.
        from intern.konfig_gruppen import _EXAKT
        defaults = self._defaults_keys()
        for k in _EXAKT:
            self.assertIn(k, defaults)

    def test_praefix_vorrang(self):
        from intern.konfig_gruppen import zuordnung
        self.assertEqual(zuordnung("MAIL_MAILINGLISTE_OPTIN"), "mailingliste")
        self.assertEqual(zuordnung("MAILINGLISTE_WOCHEN"), "mailingliste")
        self.assertEqual(zuordnung("MAIL_ANTRAG"), "mailtexte")
        # Exakt schlägt Präfix: MAIL_BEI_AKTIVIERUNG ist exakt in mailversand,
        # fiele sonst unter das MAIL_-Präfix von mailtexte.
        self.assertEqual(zuordnung("MAIL_BEI_AKTIVIERUNG"), "mailversand")
        self.assertEqual(zuordnung("DEFAULT_FROM_EMAIL"), "mailversand")

    def test_gruppiere_invarianten(self):
        from intern.konfig_gruppen import GRUPPEN, SCHLUESSEL_REIHENFOLGE, gruppiere
        keys = sorted(self._defaults_keys())
        # Absichtlich gemischte Reihenfolge, damit die Sortierung geprüft wird,
        # nicht die Eingabereihenfolge.
        rows = [
            {"id": i, "key": k, "value": "", "description": ""}
            for i, k in enumerate(reversed(keys))
        ]
        ergebnis = gruppiere(rows)

        # Keine leere Gruppe in der Ausgabe.
        for g in ergebnis:
            self.assertGreater(len(g["eintraege"]), 0, msg=f"Gruppe {g['id']!r} ist leer")

        # Summe der Einträge == len(rows) — nichts verloren, nichts doppelt.
        self.assertEqual(sum(len(g["eintraege"]) for g in ergebnis), len(rows))

        # Ausgabereihenfolge == Definitionsreihenfolge: jede definierte Gruppe,
        # die Einträge hat, erscheint in GRUPPEN-Reihenfolge.
        belegte = {g["id"] for g in ergebnis}
        erwartet = [g.id for g in GRUPPEN if g.id in belegte]
        self.assertEqual([g["id"] for g in ergebnis], erwartet)

        # Innerhalb einer Gruppe: SCHLUESSEL_REIHENFOLGE (nicht alphabetisch,
        # nicht Eingabereihenfolge). Schlüssel ohne Eintrag in der Reihenfolge
        # landen am Ende — hier kommt jeder Default-Schlüssel vor.
        pos = {k: i for i, k in enumerate(SCHLUESSEL_REIHENFOLGE)}
        for g in ergebnis:
            positionen = [pos[e["key"]] for e in g["eintraege"]]
            self.assertEqual(positionen, sorted(positionen),
                             msg=f"Reihenfolge in {g['id']!r} nicht wie definiert")

    def test_reihenfolge_ist_vollstaendig(self):
        # Jeder Default-Schlüssel steht in SCHLUESSEL_REIHENFOLGE, kein Duplikat,
        # kein Fremdschlüssel — sonst würde ein Schlüssel still ans Ende rutschen.
        from intern.konfig_gruppen import SCHLUESSEL_REIHENFOLGE
        defaults = self._defaults_keys()
        self.assertEqual(len(SCHLUESSEL_REIHENFOLGE), len(set(SCHLUESSEL_REIHENFOLGE)),
                         msg="SCHLUESSEL_REIHENFOLGE enthält Duplikate")
        self.assertEqual(set(SCHLUESSEL_REIHENFOLGE), set(defaults),
                         msg="SCHLUESSEL_REIHENFOLGE passt nicht zu _CONFIG_DEFAULTS")

    def test_unbekannter_schluessel_landet_in_sonstiges(self):
        from intern.konfig_gruppen import gruppiere, zuordnung
        self.assertEqual(zuordnung("FOO_BAR"), "sonstiges")

        # „sonstiges" fehlt in der Ausgabe, wenn es leer ist.
        rows = [{"id": 1, "key": "VEREINSNAME", "value": "", "description": ""}]
        ids = [g["id"] for g in gruppiere(rows)]
        self.assertNotIn("sonstiges", ids)

        # … und erscheint am Ende, wenn es Einträge gibt.
        rows.append({"id": 2, "key": "FOO_BAR", "value": "", "description": ""})
        ergebnis = gruppiere(rows)
        self.assertEqual(ergebnis[-1]["id"], "sonstiges")

    def test_gruppen_ids_sind_html_sicher(self):
        # Dienen als HTML-id und localStorage-Schlüssel.
        import re
        from intern.konfig_gruppen import GRUPPEN
        pattern = re.compile(r"^[a-z0-9-]+$")
        for g in GRUPPEN:
            self.assertRegex(g.id, pattern, msg=f"Gruppen-ID {g.id!r} nicht html-sicher")


class KonfigTypenTest(SimpleTestCase):
    """Eingabewidget-Typ je Konfigurationsschlüssel — DB-frei."""

    def _defaults(self):
        from intern.apps import _CONFIG_DEFAULTS
        return list(_CONFIG_DEFAULTS)

    def test_jeder_default_schluessel_hat_einen_typ(self):
        # Regressionswächter: ein neuer Schlüssel ohne FELDTYPEN-Eintrag fällt hier
        # auf, statt still als Textarea gerendert zu werden.
        from intern.konfig_gruppen import FELDTYPEN
        for key, _value, _desc in self._defaults():
            self.assertIn(
                key, FELDTYPEN,
                msg=f"Schlüssel {key!r} fehlt in FELDTYPEN",
            )

    def test_typen_sind_gueltig(self):
        from intern.konfig_gruppen import FELDTYPEN
        gueltig = {"bool", "int", "string", "text", "select", "color"}
        for key, typ in FELDTYPEN.items():
            self.assertIn(typ, gueltig, msg=f"Schlüssel {key!r} hat ungültigen Typ {typ!r}")

    def test_unbekannter_schluessel_default_text(self):
        from intern.konfig_gruppen import feldtyp
        self.assertEqual(feldtyp("UNBEKANNT_NEU"), "text")

    def test_stichproben(self):
        from intern.konfig_gruppen import feldtyp
        self.assertEqual(feldtyp("MAIL_BEI_AKTIVIERUNG"), "bool")
        self.assertEqual(feldtyp("EMAIL_PORT"), "int")
        self.assertEqual(feldtyp("VEREINS_URL"), "string")
        self.assertEqual(feldtyp("MAIL_ANTRAG"), "text")
        self.assertEqual(feldtyp("MAILINGLISTE_WOCHEN"), "string")
        self.assertEqual(feldtyp("ZEITZONE"), "select")
        self.assertEqual(feldtyp("BRAND_FARBE"), "color")

    def test_gruppiere_reichert_um_typ_ohne_mutation(self):
        from intern.konfig_gruppen import gruppiere
        rows = [
            {"id": 1, "key": "EMAIL_PORT", "value": "25", "description": ""},
            {"id": 2, "key": "MAIL_ANTRAG", "value": "Hallo", "description": ""},
        ]
        ergebnis = gruppiere(rows)
        # Original-dict bleibt unverändert (kein 'typ'-Feld eingeschmuggelt).
        self.assertNotIn("typ", rows[0])
        # Angereicherte Einträge tragen den richtigen Typ.
        typen = {}
        for g in ergebnis:
            for e in g["eintraege"]:
                typen[e["key"]] = e["typ"]
        self.assertEqual(typen["EMAIL_PORT"], "int")
        self.assertEqual(typen["MAIL_ANTRAG"], "text")

    def test_bool_defaults_sind_null_oder_eins(self):
        # Das Checkbox-Rendering prüft {% if value == "1" %}; die Defaultwerte der
        # Bool-Schlüssel müssen also "0" oder "1" sein.
        from intern.konfig_gruppen import FELDTYPEN
        defaults = {key: value for key, value, _desc in self._defaults()}
        for key, typ in FELDTYPEN.items():
            if typ != "bool":
                continue
            self.assertIn(
                defaults[key], ("0", "1"),
                msg=f"Bool-Schlüssel {key!r} hat Default {defaults[key]!r}, nicht 0/1",
            )

    def test_select_optionen_sind_vollstaendig(self):
        # Jeder select-Typ braucht eine nicht-leere Optionliste in SELECT_OPTIONEN,
        # sonst rendert das Template ein leeres Dropdown. Ob die *Werte* gültig
        # sind, prüfen die beiden folgenden Tests je Schlüssel — die Maßstäbe
        # sind verschieden (IANA-Zonen hier, Djangos Sprachliste dort).
        from intern.konfig_gruppen import FELDTYPEN, SELECT_OPTIONEN
        for key, typ in FELDTYPEN.items():
            if typ != "select":
                continue
            self.assertIn(
                key, SELECT_OPTIONEN,
                msg=f"select-Schlüssel {key!r} fehlt in SELECT_OPTIONEN",
            )
            self.assertGreater(
                len(SELECT_OPTIONEN[key]), 0, msg=f"{key!r} hat keine Optionen"
            )

    def test_zeitzone_optionen_sind_iana_zonen(self):
        # Ein Tippfehler hier ließe daten.zeitzone() beim iCal-Export scheitern.
        from zoneinfo import available_timezones
        from intern.konfig_gruppen import SELECT_OPTIONEN
        zonen = available_timezones()
        for wert, _label in SELECT_OPTIONEN["ZEITZONE"]:
            self.assertIn(wert, zonen, msg=f"{wert!r} ist keine IANA-Zone")

    def test_sprach_optionen_kennt_django(self):
        # Eine Sprache, für die Django keine Übersetzung mitbringt, führte zu
        # englischen Formularfehlern trotz anderer Auswahl. Django fällt vom
        # Regionalcode auf die Hauptsprache zurück ("de-at" -> "de"), deshalb
        # genügt es, wenn eine der beiden Formen bekannt ist.
        from django.conf.global_settings import LANGUAGES
        from intern.konfig_gruppen import SELECT_OPTIONEN
        bekannt = {code.lower() for code, _name in LANGUAGES}
        for wert, _label in SELECT_OPTIONEN["SPRACHE"]:
            self.assertTrue(
                wert in bekannt or wert.split("-")[0] in bekannt,
                msg=f"{wert!r} kennt Django nicht",
            )

    def test_sprache_default_steht_in_optionen(self):
        from intern.konfig_gruppen import SELECT_OPTIONEN
        defaults = {key: value for key, value, _desc in self._defaults()}
        optionen = {wert for wert, _label in SELECT_OPTIONEN["SPRACHE"]}
        self.assertIn(defaults["SPRACHE"], optionen)

    def test_zeitzone_default_steht_in_optionen(self):
        # Der Defaultwert aus _CONFIG_DEFAULTS muss eine der Auswahl-Optionen sein,
        # sonst ist nach dem Seeding nichts selected im Dropdown.
        from intern.konfig_gruppen import SELECT_OPTIONEN
        defaults = {key: value for key, value, _desc in self._defaults()}
        optionen = {wert for wert, _label in SELECT_OPTIONEN["ZEITZONE"]}
        self.assertIn(defaults["ZEITZONE"], optionen)

    def test_color_defaults_sind_hex_oder_leer(self):
        # Jeder color-Typ-Default muss entweder leer sein oder ein #rrggbb-Hexwert
        # -- sonst rendert der native <input type="color"> ohne sinnvollen
        # Startwert bzw. get_config liefert an anderer Stelle (mail_markup.py,
        # pdf.py, caldav/daten.py:farbe()) einen unparsbaren String.
        import re
        from intern.konfig_gruppen import FELDTYPEN
        hex_re = re.compile(r"^#[0-9a-fA-F]{6}$")
        defaults = {key: value for key, value, _desc in self._defaults()}
        for key, typ in FELDTYPEN.items():
            if typ != "color":
                continue
            value = defaults.get(key, "")
            self.assertTrue(
                value == "" or hex_re.match(value),
                msg=f"{key!r}: Default {value!r} ist weder leer noch #rrggbb",
            )


class KonfigVollstaendigkeitTest(SimpleTestCase):
    """Mängelzählung des Konfigurations-Banners — DB-frei."""

    def _defaults_keys(self):
        from intern.apps import _CONFIG_DEFAULTS
        return {row[0] for row in _CONFIG_DEFAULTS}

    def test_optional_leer_kennt_nur_katalogschluessel(self):
        # Ein Tippfehler in OPTIONAL_LEER bliebe sonst unbemerkt — der Schlüssel
        # gälte weiter als Pflicht und der Banner meldete ihn ewig.
        from intern.konfig_gruppen import OPTIONAL_LEER
        defaults = self._defaults_keys()
        for key in OPTIONAL_LEER:
            self.assertIn(
                key, defaults,
                msg=f"OPTIONAL_LEER kennt {key!r}, _CONFIG_DEFAULTS nicht",
            )

    def test_pflicht_gilt_nur_fuer_katalogschluessel(self):
        # Manuell angelegte Schlüssel (Gruppe „sonstiges") sind nie Pflicht.
        from intern.konfig_gruppen import ist_pflicht
        self.assertFalse(ist_pflicht("FOO_BAR"))
        self.assertTrue(ist_pflicht("VEREINSNAME"))
        self.assertFalse(ist_pflicht("EMAIL_HOST"))  # leer = kein Versand

    def test_unvollstaendig_zaehlt_leerzeichen_als_leer(self):
        from intern.konfig_gruppen import ist_unvollstaendig
        self.assertTrue(ist_unvollstaendig("VEREINSNAME", ""))
        self.assertTrue(ist_unvollstaendig("VEREINSNAME", "   "))
        self.assertTrue(ist_unvollstaendig("VEREINSNAME", None))
        self.assertFalse(ist_unvollstaendig("VEREINSNAME", "Chor"))
        # Optionaler Schlüssel bleibt auch leer vollständig.
        self.assertFalse(ist_unvollstaendig("MAIL_FOOTER", ""))
        # Unbekannter Schlüssel ebenso.
        self.assertFalse(ist_unvollstaendig("FOO_BAR", ""))

    def test_zaehlt_leere_pflichtfelder(self):
        from intern.konfig_gruppen import zaehle_unvollstaendig
        rows = [
            {"id": 1, "key": "VEREINSNAME", "value": "", "description": ""},
            {"id": 2, "key": "VEREINSNAME_KURZ", "value": "JG", "description": ""},
            {"id": 3, "key": "MAIL_FOOTER", "value": "", "description": ""},   # optional
            {"id": 4, "key": "FOO_BAR", "value": "", "description": ""},       # kein Katalog
        ]
        self.assertEqual(zaehle_unvollstaendig(rows), 1)
        self.assertEqual(zaehle_unvollstaendig([]), 0)

    def test_abgeschaltete_dienste(self):
        from intern.konfig_gruppen import abgeschaltete_dienste

        def rows(**werte):
            vorgabe = {"EMAIL_HOST": "", "EJABBERD_HOST": "", "EJABBERD_BOT_JID": ""}
            vorgabe.update(werte)
            return [{"id": i, "key": k, "value": v, "description": ""}
                    for i, (k, v) in enumerate(vorgabe.items())]

        # Beides aus: beide Dienste gemeldet, je mit ihren leeren Schlüsseln.
        aus = abgeschaltete_dienste(rows())
        self.assertEqual(
            aus,
            (("E-Mail-Versand", ("EMAIL_HOST",)),
             ("XMPP-Brücke der Foren", ("EJABBERD_HOST", "EJABBERD_BOT_JID"))),
        )
        # Mail konfiguriert: nur noch XMPP.
        aus = abgeschaltete_dienste(rows(EMAIL_HOST="smtp.example.com"))
        self.assertEqual([name for name, _ in aus], ["XMPP-Brücke der Foren"])
        # Halb konfiguriertes XMPP bleibt abgeschaltet — genau wie
        # is_ejabberd_configured() es sieht; genannt wird nur der leere Schlüssel.
        aus = abgeschaltete_dienste(rows(EJABBERD_HOST="xmpp.example.com"))
        self.assertEqual(aus, (("E-Mail-Versand", ("EMAIL_HOST",)),
                               ("XMPP-Brücke der Foren", ("EJABBERD_BOT_JID",))))
        # Alles gesetzt: nichts zu melden. Leerraum zählt als leer.
        self.assertEqual(abgeschaltete_dienste(rows(
            EMAIL_HOST="smtp.example.com",
            EJABBERD_HOST="xmpp.example.com",
            EJABBERD_BOT_JID="bot@xmpp.example.com",
        )), ())
        self.assertNotEqual(abgeschaltete_dienste(rows(EMAIL_HOST="   ")), ())

    def test_dienst_schluessel_stehen_im_katalog_und_sind_optional(self):
        # Ein Dienst-Schlüssel darf nie zugleich als Mangel gezählt und als
        # Hinweis genannt werden — sonst meldete der Banner dasselbe zweimal,
        # einmal gelb und einmal grau.
        from intern.konfig_gruppen import DIENSTE, OPTIONAL_LEER, ist_pflicht
        defaults = self._defaults_keys()
        for name, keys in DIENSTE:
            self.assertTrue(keys, msg=f"Dienst {name!r} nennt keinen Schlüssel")
            for key in keys:
                self.assertIn(key, defaults, msg=f"{key!r} ({name}) fehlt in _CONFIG_DEFAULTS")
                self.assertIn(key, OPTIONAL_LEER, msg=f"{key!r} ({name}) fehlt in OPTIONAL_LEER")
                self.assertFalse(ist_pflicht(key))

    def test_dienst_bedingungen_decken_sich_mit_app_settings(self):
        # Die Anzeige darf nicht behaupten, ein Dienst laufe, während der Code
        # ihn für unkonfiguriert hält. Beide Kriterien stehen in app_settings.
        import inspect
        from intern import app_settings
        from intern.konfig_gruppen import DIENSTE
        dienst_keys = {name: set(keys) for name, keys in DIENSTE}
        self.assertEqual(dienst_keys["E-Mail-Versand"], {"EMAIL_HOST"})
        self.assertEqual(dienst_keys["XMPP-Brücke der Foren"],
                         {"EJABBERD_HOST", "EJABBERD_BOT_JID"})
        # Gegenprobe am Quelltext: genau diese Schlüssel prüfen die Helfer.
        for funktion, keys in ((app_settings.is_email_configured, dienst_keys["E-Mail-Versand"]),
                               (app_settings.is_ejabberd_configured,
                                dienst_keys["XMPP-Brücke der Foren"])):
            quelle = inspect.getsource(funktion)
            for key in keys:
                self.assertIn(key, quelle,
                              msg=f"{funktion.__name__} prüft {key!r} nicht (mehr)")

    def test_fehlende_schluessel(self):
        from intern.konfig_gruppen import SCHLUESSEL_REIHENFOLGE, fehlende_schluessel
        # Vollständige Tabelle: nichts fehlt.
        self.assertEqual(fehlende_schluessel(SCHLUESSEL_REIHENFOLGE), ())
        # Zwei entfernte Zeilen kommen in Anzeigereihenfolge zurück, nicht
        # alphabetisch — der Banner nennt sie in derselben Ordnung wie die Seite.
        rest = [k for k in SCHLUESSEL_REIHENFOLGE if k not in ("VEREINSNAME", "EMAIL_PORT")]
        fehlend = fehlende_schluessel(rest)
        self.assertEqual(set(fehlend), {"VEREINSNAME", "EMAIL_PORT"})
        pos = {k: i for i, k in enumerate(SCHLUESSEL_REIHENFOLGE)}
        self.assertEqual(list(fehlend), sorted(fehlend, key=lambda k: pos[k]))
        # Ein Fremdschlüssel in der Tabelle ändert nichts.
        self.assertEqual(fehlende_schluessel(list(SCHLUESSEL_REIHENFOLGE) + ["FOO_BAR"]), ())


class ZeitzoneTest(SimpleTestCase):
    """ZEITZONE-Konfiguration — DB-frei über Env-Variablen und Fallback geprüft."""

    def test_env_vorrang(self):
        import os
        from unittest import mock
        from intern.app_settings import get_zeitzone
        with mock.patch.dict(os.environ, {"ZEITZONE": "Europe/Zurich"}):
            self.assertEqual(get_zeitzone(), "Europe/Zurich")

    def test_fallback_auf_settings_ohne_db(self):
        # Ohne Env und ohne DB lief get_config auf None zurück → settings.TIME_ZONE.
        import os
        from unittest import mock
        from django.conf import settings
        from intern.app_settings import get_zeitzone
        env = {k: v for k, v in os.environ.items() if k != "ZEITZONE"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(get_zeitzone(), settings.TIME_ZONE)

    def test_ungueltiger_wert_faellt_zurueck(self):
        # Ein verstellter/ungültiger Wert darf nie eine ZoneInfo werfen.
        import os
        from unittest import mock
        from django.conf import settings
        from intern.app_settings import get_zeitzone
        with mock.patch.dict(os.environ, {"ZEITZONE": "Nicht/Vorhanden"}):
            self.assertEqual(get_zeitzone(), settings.TIME_ZONE)

    def test_daten_zeitzone_ohne_db(self):
        # daten.zeitzone() baut auch ohne DB eine ZoneInfo (über den Fallback).
        from django.conf import settings
        from intern.caldav.daten import zeitzone
        from zoneinfo import ZoneInfo
        self.assertEqual(zeitzone(), ZoneInfo(settings.TIME_ZONE))


class SpracheTest(SimpleTestCase):
    """SPRACHE-Konfiguration — wie ZeitzoneTest DB-frei über Env geprüft."""

    def test_env_vorrang(self):
        from intern.app_settings import get_sprache
        with mock.patch.dict(os.environ, {"SPRACHE": "fr-fr"}):
            self.assertEqual(get_sprache(), "fr-fr")

    def test_regionalcode_wird_akzeptiert(self):
        # "de-at" steht nicht in Djangos LANGUAGES, "de" schon — Django fällt
        # intern auf die Hauptsprache zurück, also darf der Wert durch.
        from intern.app_settings import get_sprache
        with mock.patch.dict(os.environ, {"SPRACHE": "de-at"}):
            self.assertEqual(get_sprache(), "de-at")

    def test_ungueltiger_wert_faellt_zurueck(self):
        from django.conf import settings
        from intern.app_settings import get_sprache
        with mock.patch.dict(os.environ, {"SPRACHE": "kl-ingon"}):
            self.assertEqual(get_sprache(), settings.LANGUAGE_CODE)

    def test_fallback_ohne_env_und_ohne_db(self):
        from django.conf import settings
        from intern.app_settings import get_sprache
        env = {k: v for k, v in os.environ.items() if k != "SPRACHE"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(get_sprache(), settings.LANGUAGE_CODE)


class WochentagsnamenTest(SimpleTestCase):
    """Wächter für die deutsche Locale — lokal wie im Container.

    ``replacements.format_datetime`` gibt den kurzen Wochentag über ``%a`` aus und
    setzt dafür ``LC_TIME`` auf ``de_DE``; schlägt das fehl, fängt es den Fehler ab
    und liefert stillschweigend englische Kürzel („Thu" statt „Do"). Im Abbild ist
    genau das passiert, weil ``locale-gen`` in Debian sein Argument ignoriert und
    deshalb nie eine Locale erzeugt wurde. Dieser Test schlägt dann fehl, statt
    dass es irgendwann jemandem auf einer Seite auffällt.
    """

    def test_wochentag_ist_deutsch(self):
        from intern.replacements import format_datetime
        ausgabe = format_datetime(datetime(2026, 1, 15, 20, 0))
        self.assertIn("Do,", ausgabe, msg=f"Deutsche Locale fehlt: {ausgabe!r}")


class DatumsformatTest(SimpleTestCase):
    """Wochentag voran, Monat als Zahl — kein Monatsname mehr.

    Geprüft wird relativ zur Uhr (``format_datetime`` liest sie selbst), damit der
    Test zu jedem Zeitpunkt läuft — auch über einen Jahreswechsel hinweg.
    """

    def test_wochentag_voran_und_monat_als_zahl(self):
        from intern.replacements import format_datetime
        ziel = (datetime.now() + timedelta(days=30)).replace(
            hour=19, minute=30, second=0, microsecond=0
        )
        ausgabe = format_datetime(ziel)
        self.assertTrue(
            ausgabe.startswith(ziel.strftime("%a") + ","),
            msg=f"Wochentag fehlt: {ausgabe!r}",
        )
        self.assertIn(f"{ziel.day:02d}.{ziel.month:02d}.", ausgabe)
        self.assertIn("19:30", ausgabe)
        self.assertNotIn(ziel.strftime("%B"), ausgabe)

    def test_anderes_jahr_nennt_das_jahr(self):
        from intern.replacements import format_datetime
        ziel = datetime(datetime.now().year + 1, 6, 3, 20, 0)
        ausgabe = format_datetime(ziel)
        self.assertIn(f"03.06.{ziel.year}", ausgabe)
        self.assertTrue(ausgabe.startswith(ziel.strftime("%a") + ","), ausgabe)

    def test_heute_und_gestern_bleiben_wie_sie_waren(self):
        from intern.replacements import format_datetime
        jetzt = datetime.now().replace(hour=20, minute=0, second=0, microsecond=0)
        self.assertEqual(format_datetime(jetzt), "20:00")
        self.assertEqual(
            format_datetime(jetzt - timedelta(days=1)), "gestern 20:00"
        )


class KonfigurierteHelperTest(SimpleTestCase):
    """Die aus Modulkonstanten in die Konfiguration gewanderten Helfer.

    Ohne DB-Zugriff: env-Variablen haben Vorrang und lassen sich per
    ``mock.patch.dict(os.environ, …)`` steuern. ``get_map_center`` fängt die
    DB-Exception im try/except ab und fällt auf die env-basierten Werte zurück.
    """

    def test_invite_max_age_default(self):
        from intern.views.auth import _invite_max_age
        with mock.patch.dict("os.environ", {}, clear=False):
            self.assertEqual(_invite_max_age(), 7 * 24 * 3600)

    def test_invite_max_age_aus_konfiguration(self):
        from intern.views.auth import _invite_max_age
        with mock.patch.dict("os.environ", {"MITGLIED_EINLADUNG_TAGE": "14"}):
            self.assertEqual(_invite_max_age(), 14 * 24 * 3600)

    def test_bestaetigung_max_age_default(self):
        from intern.views.auth import _bestaetigung_max_age
        self.assertEqual(_bestaetigung_max_age(), 30 * 24 * 3600)

    def test_bestaetigung_max_age_aus_konfiguration(self):
        from intern.views.auth import _bestaetigung_max_age
        with mock.patch.dict("os.environ", {"MITGLIED_BESTAETIGUNG_TAGE": "60"}):
            self.assertEqual(_bestaetigung_max_age(), 60 * 24 * 3600)

    def test_map_center_fallback_default(self):
        # Ohne DB und ohne env bleibt es beim neutralen Fallback (Mitte Deutschlands).
        from intern.app_settings import get_map_center
        with mock.patch.dict("os.environ", {}, clear=False):
            self.assertEqual(get_map_center(), (51.1634, 10.4477))

    def test_map_center_fallback_aus_konfiguration(self):
        from intern.app_settings import get_map_center
        env = {"MAP_CENTER_LAT": "10.5", "MAP_CENTER_LNG": "20.25"}
        with mock.patch.dict("os.environ", env):
            self.assertEqual(get_map_center(), (10.5, 20.25))

    def test_termin_daten_standdauer_default(self):
        # Ohne hereingereichte standdauer gilt die Modulkonstante (2 h) —
        # die bestehenden ical-Tests bleiben unberührt.
        from intern.caldav import ical
        termin = SimpleNamespace(
            pk=1, datum=datetime(2025, 6, 1, 19, 30), datum_bis=None, ort=None
        )
        d = ical.termin_daten(termin, zone=ZoneInfo("Europe/Berlin"))
        # 19:30 Berlin (CEST, UTC+2) + 2 h Standarddauer = 21:30 lokal = 19:30 UTC.
        self.assertEqual(d["ende"], "20250601T193000Z")

    def test_termin_daten_standdauer_konfiguriert(self):
        from intern.caldav import ical
        termin = SimpleNamespace(
            pk=1, datum=datetime(2025, 6, 1, 19, 30), datum_bis=None, ort=None
        )
        d = ical.termin_daten(
            termin, zone=ZoneInfo("Europe/Berlin"),
            standdauer=timedelta(hours=3),
        )
        # + 3 h = 22:30 lokal = 20:30 UTC.
        self.assertEqual(d["ende"], "20250601T203000Z")


def _datei(name, mime="", url=None):
    """Ein filer-File, so weit die Einbettung es anfasst."""
    return SimpleNamespace(
        original_filename=name,
        mime_type=mime,
        url=url if url is not None else f"/media/{name}",
    )


class MedientypTest(SimpleTestCase):
    """MIME zuerst, Endung als Rückfall — dieselbe Rangfolge wie im Ordner."""

    def test_audio_endungen(self):
        from intern.medientypen import medientyp
        for name in ("a.mp3", "a.M4A", "a.opus", "a.flac", "a.wav"):
            self.assertEqual(medientyp("", name), "audio", name)

    def test_video_endungen(self):
        from intern.medientypen import medientyp
        for name in ("a.mp4", "a.webm", "a.MOV", "a.ogv"):
            self.assertEqual(medientyp("", name), "video", name)

    def test_nicht_abspielbar(self):
        from intern.medientypen import medientyp
        # .mkv/.avi spielt kein Browser verlässlich, .pdf/.jpg gehören in die Figur.
        for name in ("a.mkv", "a.avi", "a.wmv", "a.pdf", "a.jpg", "a", ""):
            self.assertIsNone(medientyp("", name), name)

    def test_mime_schlaegt_endung(self):
        from intern.medientypen import medientyp
        self.assertEqual(medientyp("audio/mpeg", "unbekannt.dat"), "audio")
        self.assertEqual(medientyp("video/mp4", "unbekannt.dat"), "video")
        # .ogg ist Audio, solange kein video/ogg dagegensteht.
        self.assertEqual(medientyp("", "a.ogg"), "audio")
        self.assertEqual(medientyp("video/ogg", "a.ogg"), "video")

    def test_endungen_mit_folders_geteilt(self):
        """Divergieren die Listen, verspricht die Ordnerzeile Zählungen,
        die die Playlist nicht einlöst."""
        from intern import medientypen
        from intern.views import folders
        self.assertIs(folders._AUDIO_ENDUNGEN, medientypen.AUDIO_ENDUNGEN)


class MedienleisteMarkupTest(SimpleTestCase):
    """Das Markup muss die Regex-Kette in ``apply_replacements`` überleben."""

    def _leiste(self, name, mime=""):
        from intern.replacements import insert_file_object
        return insert_file_object(_datei(name, mime), spieler=True)

    def test_audio_ist_figur_ohne_eigene_controls(self):
        """Audio spielt nur im Mini-Player — eine Leiste daneben wäre doppelt."""
        markup = self._leiste("Song.mp3")
        self.assertIn('class="wiki-figure wiki-audio"', markup)
        self.assertIn('data-typ="audio"', markup)
        self.assertIn('data-url="/media/Song.mp3"', markup)
        self.assertIn('data-titel="Song"', markup)
        self.assertIn('class="wiki-audio-start" href="/media/Song.mp3"', markup)
        self.assertIn('<span class="wiki-audio-name">Song.mp3</span>', markup)
        self.assertIn('class="wp-download" href="/media/Song.mp3" download', markup)
        self.assertNotIn("wiki-player", markup)
        self.assertNotIn("mp-", markup)
        self.assertNotIn("<audio", markup)

    def test_video_leiste_ohne_eigene_controls(self):
        import re as _re
        markup = self._leiste("Clip.mp4")
        self.assertIn('data-typ="video"', markup)
        self.assertIn('<video class="wp-video"', markup)
        # Die Leiste *ist* die Steuerung — native controls daneben wären doppelt.
        video_tag = _re.search(r"<video[^>]*>", markup).group(0)
        self.assertNotIn("controls", video_tag)

    def test_nur_phrasing_content(self):
        """Ein Blockelement bräche den <p>, in den die Zeile danach wandert."""
        markup = self._leiste("Clip.mp4")
        self.assertNotIn("<div", markup)
        self.assertNotIn("<figure", markup)
        self.assertNotIn("\n", markup)

    def test_ueberlebt_die_nachfolgenden_regeln(self):
        """''kursiv'', ""zitat"" und $roh$ laufen nach dieser Ersetzung."""
        for name in ("Song.mp3", "Clip.mp4"):
            markup = self._leiste(name)
            self.assertNotIn("'", markup, name)
            self.assertNotIn('""', markup, name)
            self.assertNotIn("$", markup, name)
            self.assertNotIn("\n", markup, name)

    def test_anfuehrungszeichen_im_dateinamen(self):
        markup = self._leiste('a"b.mp3')
        self.assertIn("&quot;", markup)
        # Das Attribut bleibt heil: nach data-url folgt genau ein schließendes ".
        self.assertIn('data-url="/media/a&quot;b.mp3"', markup)

    def test_label_ueberschreibt_den_titel(self):
        from intern.replacements import insert_file_object
        markup = insert_file_object(_datei("Clip.mp4"), "Mein Titel", spieler=True)
        self.assertIn('class="mp-title">Mein Titel<', markup)
        markup = insert_file_object(_datei("Song.mp3"), "Mein Titel", spieler=True)
        self.assertIn('data-titel="Mein Titel"', markup)
        self.assertIn('<span class="wiki-audio-name">Mein Titel</span>', markup)

    def test_nicht_abspielbares_bleibt_figur(self):
        for name in ("Noten.pdf", "Brief.docx", "Film.mkv"):
            markup = self._leiste(name)
            self.assertIn('class="wiki-figure"', markup, name)
            self.assertNotIn("wiki-player", markup, name)

    def test_ohne_spieler_kein_player(self):
        """Der Forums-Renderpfad ruft ohne ``spieler`` auf."""
        from intern.replacements import insert_file_object
        markup = insert_file_object(_datei("Song.mp3"))
        self.assertIn('class="wiki-figure"', markup)
        self.assertNotIn("wiki-audio", markup)
        markup = insert_file_object(_datei("Clip.mp4"))
        self.assertNotIn("wiki-player", markup)


class WikiPlayerIntegrationTest(SimpleTestCase):
    """Der ganze Weg durch ``apply_replacements``."""

    def _rendern(self, text, datei=None, request=True):
        from intern import replacements
        req = SimpleNamespace(user=None) if request else None
        with mock.patch.object(replacements, "File") as File, mock.patch.object(
            replacements, "get_vereinsname_kurz", return_value="JG"
        ):
            File.objects.filter.return_value.first.return_value = datei
            return replacements.apply_replacements(text, req)

    def test_absatz_bleibt_heil(self):
        out = self._rendern("Hier: [[Datei:Clip.mp4]] und Ende", _datei("Clip.mp4"))
        self.assertIn('<p>Hier: <span class="wiki-player', out)
        self.assertIn("und Ende</p>", out)

    def test_audio_wird_figur(self):
        out = self._rendern("[[Datei:Song.mp3]]", _datei("Song.mp3"))
        self.assertIn('<figure class="wiki-figure wiki-audio"', out)
        self.assertNotIn("wiki-player", out)

    def test_label_wird_ausgewertet(self):
        out = self._rendern("[[Datei:Clip.mp4|Mein Titel]]", _datei("Clip.mp4"))
        self.assertIn('class="mp-title">Mein Titel<', out)

    def test_fehlende_datei_unveraendert(self):
        out = self._rendern("[[Datei:fehlt.mp3]]", None)
        self.assertIn('class="not_found"', out)
        self.assertNotIn("wiki-player", out)

    def test_forum_ohne_player(self):
        out = self._rendern(
            "[[Datei:Song.mp3]]", _datei("Song.mp3"), request=False
        )
        self.assertNotIn("wiki-audio", out)
        self.assertIn('class="wiki-figure"', out)


class PdfExtraktionTest(SimpleTestCase):
    """PDF-Preview und Textextraktion über pypdfium2 (Nachfolger von PyMuPDF).

    Das Test-PDF entsteht in-memory mit reportlab — kein DB-Zugriff, kein
    Fixture, konsistent mit der SimpleTestCase-Invariante.
    """

    @classmethod
    def _pdf(cls):
        if not hasattr(cls, "_pdf_bytes"):
            import io as _io

            from reportlab.pdfgen import canvas as rl_canvas

            buf = _io.BytesIO()
            c = rl_canvas.Canvas(buf, pagesize=(595, 842))
            c.setFont("Helvetica", 12)
            c.drawString(72, 700, "Erste Strophe des Liedes")
            c.save()
            cls._pdf_bytes = buf.getvalue()
        return cls._pdf_bytes

    def test_text_wird_gelesen(self):
        from intern.fileindex import _extract_pdf

        self.assertIn("Erste Strophe", _extract_pdf(self._pdf()))

    def test_textextraktion_bricht_bei_muell_ab(self):
        from intern.fileindex import _extract_pdf

        self.assertEqual(_extract_pdf(b"gar kein pdf"), "")

    def test_thumbnail_wird_erzeugt(self):
        from io import BytesIO

        from intern.thumbnails import pdf_source

        bild = pdf_source(BytesIO(self._pdf()))
        self.assertIsNotNone(bild)
        # 150 dpi auf A4 (595 pt breit) → ca. 1240 px.
        self.assertAlmostEqual(bild.size[0], 595 * 150 / 72, delta=2)

    def test_thumbnail_nicht_pdf_liefert_none(self):
        from io import BytesIO

        from intern.thumbnails import pdf_source

        self.assertIsNone(pdf_source(BytesIO(b"gar kein pdf")))
        # Magic-Byte-Guard: "%PDF-" ohne gültigen Rest kippt nicht, sondern
        # liefert None (wie bei PyMuPDF).
        self.assertIsNone(pdf_source(BytesIO(b"%PDF-" + b"\x00" * 64)))

    def test_thumbnail_leeres_pdf_liefert_none(self):
        from io import BytesIO

        import pypdfium2 as pdfium

        from intern.thumbnails import pdf_source

        doc = pdfium.PdfDocument.new()
        buf = BytesIO()
        doc.save(buf)
        doc.close()
        self.assertIsNone(pdf_source(BytesIO(buf.getvalue())))
        self.assertIsNone(pdf_source(BytesIO(b"%PDF-" + b"\x00" * 64)))
        self.assertIsNone(pdf_source(BytesIO(b"gar kein pdf")))


# ---------------------------------------------------------------------------
# Termin-Banner: Countdown und Auswahl
# ---------------------------------------------------------------------------

# Ein Montag — von hier aus sind die Wochentage in den Tests ablesbar.
MONTAG = datetime(2026, 9, 14, 10, 0)

# Djangos timeuntil trennt Zahl und Einheit mit einem geschuetzten Leerzeichen;
# der Countdown macht das mit. Hier benannt, damit im Testcode kein
# unsichtbares Zeichen steht.
NBSP = "\u00a0"


class TerminZeitraumEingabeTest(SimpleTestCase):
    """Datum und Uhrzeit getrennt an beiden Enden; die Uhrzeit ist optional."""

    def test_ohne_ende(self):
        self.assertEqual(
            zeitraum_aus_eingabe(date(2026, 11, 6), time(19, 0), None, None),
            (datetime(2026, 11, 6, 19, 0), None),
        )

    def test_mehrtaegig_ohne_uhrzeit(self):
        # Die Chorfreizeit: das Ende auf 00:00 meint den ganzen letzten Tag.
        beginn, ende = zeitraum_aus_eingabe(date(2026, 11, 6), None, date(2026, 11, 8), None)
        self.assertEqual(ende, datetime(2026, 11, 8, 0, 0))
        self.assertTrue(ist_ganztaegig(beginn, ende))

    def test_endzeit_ohne_datum_liegt_am_selben_tag(self):
        self.assertEqual(
            zeitraum_aus_eingabe(date(2026, 11, 6), time(19, 0), None, time(21, 30))[1],
            datetime(2026, 11, 6, 21, 30),
        )

    def test_mehrtaegig_mit_uhrzeiten(self):
        self.assertEqual(
            zeitraum_aus_eingabe(date(2026, 11, 6), time(18, 0), date(2026, 11, 8), time(14, 0))[1],
            datetime(2026, 11, 8, 14, 0),
        )

    def test_uhrzeit_nur_an_einem_ende_abgelehnt(self):
        with self.assertRaises(ValueError):
            zeitraum_aus_eingabe(date(2026, 11, 6), time(18, 0), date(2026, 11, 8), None)
        with self.assertRaises(ValueError):
            zeitraum_aus_eingabe(date(2026, 11, 6), None, date(2026, 11, 8), time(14, 0))

    def test_ende_vor_beginn_abgelehnt(self):
        with self.assertRaises(ValueError):
            zeitraum_aus_eingabe(date(2026, 11, 6), time(19, 0), None, time(18, 0))

    def test_unveraenderter_altbestand_bleibt_speicherbar(self):
        # Silvester 20:00 bis Neujahr 00:00, angelegt mit dem alten Feld: wer nur
        # die Beschreibung ändert, soll nicht an der Uhrzeitregel scheitern.
        bisher = (datetime(2026, 12, 31, 20, 0, 13), datetime(2027, 1, 1, 0, 0))
        self.assertEqual(
            zeitraum_aus_eingabe(
                date(2026, 12, 31), time(20, 0), date(2027, 1, 1), None, bisher=bisher
            ),
            (datetime(2026, 12, 31, 20, 0), datetime(2027, 1, 1, 0, 0)),
        )

    def test_geaenderter_altbestand_folgt_der_regel(self):
        bisher = (datetime(2026, 12, 31, 20, 0), datetime(2027, 1, 1, 0, 0))
        with self.assertRaises(ValueError):
            zeitraum_aus_eingabe(
                date(2026, 12, 31), time(19, 0), date(2027, 1, 1), None, bisher=bisher
            )


class IcalFeedGanztaegigTest(SimpleTestCase):
    """Der iCal-Feed liest ganztägige Termine wie CalDAV: als Datum, Ende exklusiv."""

    def _feed(self, *termine):
        from icalendar import Calendar

        from intern.views import termine as termine_mod

        with mock.patch.object(termine_mod, "get_config", return_value="geheim"), \
                mock.patch.object(termine_mod, "get_config_int", side_effect=[180, 2]), \
                mock.patch.object(termine_mod, "Termin") as modell:
            modell.objects.filter.return_value.select_related.return_value.order_by.return_value = list(termine)
            antwort = termine_mod.calendar_ics(None, "geheim")
        return [e for e in Calendar.from_ical(antwort.content).walk("VEVENT")]

    def _termin(self, datum, datum_bis=None):
        return SimpleNamespace(pk=1, kurz="T", datum=datum, datum_bis=datum_bis, lang="", ort=None)

    def test_mehrtaegig_ganztaegig_bis_einschliesslich_letztem_tag(self):
        (ev,) = self._feed(self._termin(datetime(2026, 5, 1), datetime(2026, 5, 3)))
        self.assertEqual(ev.decoded("dtstart"), date(2026, 5, 1))
        self.assertEqual(ev.decoded("dtend"), date(2026, 5, 4))

    def test_mit_uhrzeit_bleibt_zeitgebunden(self):
        (ev,) = self._feed(self._termin(datetime(2026, 5, 1, 19, 0), datetime(2026, 5, 1, 21, 30)))
        self.assertEqual(ev.decoded("dtend"), datetime(2026, 5, 1, 21, 30))


def _bannertermin(datum, datum_bis=None):
    """Stellvertreter fuer den Banner-Termin: gelesen werden nur die zwei Felder."""
    return SimpleNamespace(datum=datum, datum_bis=datum_bis)


class IstGanztaegigTest(SimpleTestCase):
    def test_ohne_uhrzeit(self):
        self.assertTrue(ist_ganztaegig(datetime(2026, 9, 18, 0, 0)))

    def test_mit_uhrzeit(self):
        self.assertFalse(ist_ganztaegig(datetime(2026, 9, 18, 20, 0)))

    def test_beide_enden_muessen_mitternacht_sein(self):
        self.assertTrue(ist_ganztaegig(
            datetime(2026, 9, 18, 0, 0), datetime(2026, 9, 20, 0, 0)))
        self.assertFalse(ist_ganztaegig(
            datetime(2026, 9, 18, 0, 0), datetime(2026, 9, 20, 14, 0)))

    def test_sekunden_zaehlen_nicht_als_uhrzeit(self):
        # Fixiert die (hour, minute)-Lesart: Altdaten mit Sekundenanteil sind
        # ganztaegig, genau wie die Datumszeile des Banners es sieht.
        self.assertTrue(ist_ganztaegig(datetime(2026, 9, 18, 0, 0, 30)))


class TerminCountdownTest(SimpleTestCase):
    """``countdown_text`` — Kalendertage bei 00:00, sonst Djangos timeuntil."""

    def test_mit_uhrzeit_bleibt_timeuntil(self):
        # Gegen Djangos eigene Ausgabe pruefen, nicht gegen einen
        # festgeschriebenen String: sonst braeche der Test an einer geaenderten
        # Uebersetzung statt an einem echten Fehler.
        freitag = datetime(2026, 9, 18, 20, 0)
        self.assertEqual(
            countdown_text(freitag, None, MONTAG), timeuntil(freitag, MONTAG)
        )

    def test_ganztaegig_zaehlt_kalendertage(self):
        # Der gemeldete Fall: Montag 10:00 auf Freitag ganztaegig.
        freitag = datetime(2026, 9, 18, 0, 0)
        self.assertIn("Stunden", timeuntil(freitag, MONTAG))      # Gegenprobe
        self.assertEqual(countdown_text(freitag, None, MONTAG), f"4{NBSP}Tage")

    def test_morgen(self):
        self.assertEqual(
            countdown_text(datetime(2026, 9, 15, 0, 0), None, MONTAG), "morgen"
        )

    def test_heute(self):
        self.assertEqual(
            countdown_text(datetime(2026, 9, 14, 0, 0), None, MONTAG), "heute"
        )

    def test_kurz_vor_mitternacht(self):
        # timeuntil sagte hier "1 Minute" — gemeint ist der naechste Tag.
        jetzt = datetime(2026, 9, 14, 23, 59)
        self.assertEqual(
            countdown_text(datetime(2026, 9, 15, 0, 0), None, jetzt), "morgen"
        )

    def test_kurz_nach_mitternacht(self):
        jetzt = datetime(2026, 9, 15, 0, 1)
        self.assertEqual(
            countdown_text(datetime(2026, 9, 15, 0, 0), None, jetzt), "heute"
        )

    def test_laufend_mehrtaegig_ist_heute(self):
        # Chorfreizeit Fr–So, jetzt ist Samstag: der Termin laeuft noch.
        self.assertEqual(
            countdown_text(
                datetime(2026, 9, 18, 0, 0), datetime(2026, 9, 20, 0, 0),
                datetime(2026, 9, 19, 11, 0),
            ),
            "heute",
        )

    def test_mehrtaegig_mit_uhrzeit_bleibt_timeuntil(self):
        # Eine Uhrzeit an einem der beiden Enden genuegt: zeitgebunden.
        datum = datetime(2026, 9, 18, 0, 0)
        self.assertEqual(
            countdown_text(datum, datetime(2026, 9, 20, 14, 0), MONTAG),
            timeuntil(datum, MONTAG),
        )

    def test_ein_tag_kommt_nie_vor(self):
        # Bei Kalendertagen ist "1 Tag" per Definition der naechste Tag und
        # heisst "morgen"; der Plural-Zweig beginnt erst bei 2, deshalb braucht
        # es kein ngettext. Die Tageszeit darf nichts daran aendern.
        erwartet = [
            "heute", "morgen", f"2{NBSP}Tage", f"3{NBSP}Tage",
            f"4{NBSP}Tage", f"5{NBSP}Tage", f"6{NBSP}Tage", f"7{NBSP}Tage",
        ]
        for stunde in (0, 9, 23):
            jetzt = datetime(2026, 9, 14, stunde, 30)
            self.assertEqual(
                [countdown_text(datetime(2026, 9, 14 + t, 0, 0), None, jetzt)
                 for t in range(8)],
                erwartet,
            )

    def test_monatswechsel(self):
        jetzt = datetime(2026, 9, 30, 22, 0)
        self.assertEqual(
            countdown_text(datetime(2026, 10, 1, 0, 0), None, jetzt), "morgen"
        )
        self.assertEqual(
            countdown_text(datetime(2026, 10, 3, 0, 0), None, jetzt), f"3{NBSP}Tage"
        )

    def test_jahreswechsel(self):
        jetzt = datetime(2026, 12, 31, 10, 0)
        self.assertEqual(
            countdown_text(datetime(2027, 1, 1, 0, 0), None, jetzt), "morgen"
        )

    def test_ueber_die_zeitumstellung(self):
        # USE_TZ ist aus, alles ist naive Wanduhrzeit: die Nacht mit 25 Stunden
        # darf die Kalendertage nicht verschieben.
        jetzt = datetime(2026, 10, 24, 12, 0)
        self.assertEqual(
            countdown_text(datetime(2026, 10, 26, 0, 0), None, jetzt), f"2{NBSP}Tage"
        )

    def test_vergangener_termin_wird_heute(self):
        # Defensiv: zwischen Seitenaufbau und htmx-Swap kann Mitternacht liegen.
        self.assertEqual(
            countdown_text(datetime(2026, 9, 13, 0, 0), None, MONTAG), "heute"
        )

    def test_geschuetztes_leerzeichen(self):
        # Djangos timeuntil trennt Zahl und Einheit mit U+00A0; ohne das
        # braeche der Countdown im Banner anders um als bisher.
        self.assertIn(
            NBSP, countdown_text(datetime(2026, 9, 18, 0, 0), None, MONTAG)
        )


class AnkuendigungLeerformenTest(SimpleTestCase):
    """Das Kriterium für „öffentlich angekündigt" ist ein nicht-leerer Ankündigungstext.

    Startseite (`home()`) und Auftritts-Erinnerungen teilen sich diese Menge
    (`OHNE_ANKUENDIGUNG` in `intern/models.py`). Die beiden Leerformen sehen
    redundant aus und sind es nicht: Django setzt
    bei der Negation auf einer nullable-Spalte ein ``IS NOT NULL`` in die
    Bedingung (``NOT (extern = '' AND extern IS NOT NULL)``), ein
    ``NULL``-Datensatz überlebt ``exclude(extern="")`` also.

    Die zweite Hälfte prüft die *Länge*, nicht den Wert. MySQL/MariaDB
    vergleichen Zeichenketten unter den gängigen Kollationen mit ``PAD SPACE``,
    dort ist ``' ' = ''`` wahr — ein ``Q(extern="")`` schließt also genau die
    Auftritte aus, die das Leerzeichen aus ``_STARTSEITE_OHNE_TEXT`` listen
    soll. Die Suite läuft ohne Datenbank und sieht das nicht; darum pinnt der
    Test die Form der Bedingung, nicht ihr Ergebnis.
    """

    def test_beide_leerformen_zaehlen(self):
        from intern.models import OHNE_ANKUENDIGUNG

        self.assertEqual(
            OHNE_ANKUENDIGUNG, Q(extern__isnull=True) | Q(extern__length=0)
        )

    def test_kein_vergleich_mit_leerstring(self):
        """Kein ``extern=""`` in der Bedingung — das wäre die PAD-SPACE-Falle."""
        from intern.models import OHNE_ANKUENDIGUNG

        lookups = {kind[0] for kind in OHNE_ANKUENDIGUNG.children}
        self.assertNotIn("extern", lookups)
        self.assertNotIn("extern__exact", lookups)

    def test_length_lookup_ist_registriert(self):
        """``extern__length`` muss auflösbar sein, sonst wirft die Abfrage."""
        from django.db.models import TextField
        from django.db.models.functions import Length

        self.assertIs(TextField.get_lookups().get("length"), Length)


class KommendeTermineQTest(SimpleTestCase):
    """``kommende_q`` ohne Datenbank — ueber die strukturelle Q-Gleichheit."""

    def _erwartet(self, jetzt, tagesbeginn):
        return (
            Q(datum__gt=jetzt)
            | Q(datum=tagesbeginn)
            | Q(
                datum__lt=tagesbeginn,
                datum_bis__gte=tagesbeginn,
                datum__hour=0,
                datum__minute=0,
                datum_bis__hour=0,
                datum_bis__minute=0,
            )
        )

    def test_zweige(self):
        self.assertEqual(
            kommende_q(MONTAG),
            self._erwartet(MONTAG, datetime(2026, 9, 14, 0, 0)),
        )

    def test_keine_luecke_um_mitternacht(self):
        # Ist `jetzt` exakt 00:00, greift datum__gt noch nicht — dann faengt
        # der Gleichheitszweig den ganztaegigen Termin desselben Augenblicks.
        mitternacht = datetime(2026, 9, 14, 0, 0)
        self.assertEqual(
            kommende_q(mitternacht), self._erwartet(mitternacht, mitternacht)
        )


class TerminCountdownFilterTest(SimpleTestCase):
    """Der Template-Filter — die einzige Stelle, die die Uhr liest."""

    def _rendern(self, termin, jetzt):
        return Template("{% load termin_tags %}{{ t|countdown:jetzt }}").render(
            Context({"t": termin, "jetzt": jetzt})
        )

    def test_reicht_jetzt_durch(self):
        termin = _bannertermin(datetime(2026, 9, 15, 0, 0))
        self.assertEqual(self._rendern(termin, MONTAG), "morgen")

    def test_ohne_argument_wird_die_uhr_gelesen(self):
        termin = _bannertermin(datetime(2026, 9, 15, 0, 0))
        with mock.patch("intern.templatetags.termin_tags.now", return_value=MONTAG):
            out = Template("{% load termin_tags %}{{ t|countdown }}").render(
                Context({"t": termin})
            )
        self.assertEqual(out, "morgen")

    def test_none_bleibt_leer(self):
        self.assertEqual(self._rendern(None, MONTAG), "")


class ExternHtmlFilterTest(SimpleTestCase):
    """Der Ankündigungstext aus dem Altsystem, beim Rendern nachbearbeitet.

    Nacharbeiten nur beim Rendern — der gespeicherte Wert und damit das
    Änderungsprotokoll bleiben roh. Was der Filter *nicht* tut, ist
    sanitisieren; das ist eine bewusste Grenze und steht in seinem Docstring.
    """

    def _rendern(self, wert):
        return Template("{% load termin_tags %}{{ t|extern_html }}").render(
            Context({"t": wert})
        )

    def test_ohne_inhalt_bleibt_leer(self):
        # Leerraum zaehlt auf der Startseite als „gefuellt" (die Auswahl prueft
        # das rohe Feld), die Anzeige soll daraus aber keinen leeren Kasten
        # machen.
        for wert in (None, "", " ", "\r\n"):
            with self.subTest(wert=wert):
                self.assertEqual(self._rendern(wert), "")

    def test_zeilenumbrueche_werden_zu_br(self):
        self.assertEqual(self._rendern("a\r\nb\rc\nd"), "a<br>b<br>c<br>d")

    def test_adressblock_der_alten_zeilen(self):
        text = "Evangelische Kirchengemeinde Fechenheim Pfortenstraße 4 \r\n60386 Frankfurt am Main"
        self.assertEqual(
            self._rendern(text),
            "Evangelische Kirchengemeinde Fechenheim Pfortenstraße 4 <br>"
            "60386 Frankfurt am Main",
        )

    def test_links_bleiben(self):
        text = '<a href="https://example.org/x" target="_blank">example</a>'
        self.assertEqual(self._rendern(text), text)

    def test_style_verschwindet(self):
        self.assertEqual(
            self._rendern('<a href="/x" style="color:#bacee6;">x</a>'),
            '<a href="/x">x</a>',
        )

    def test_ueberschriften_werden_strong(self):
        self.assertEqual(
            self._rendern("<h1>Konzert</h1>"), "<strong>Konzert</strong>"
        )
        self.assertEqual(self._rendern("<h3>Eintritt frei</h3>"), "<strong>Eintritt frei</strong>")

    def test_font_wird_span(self):
        self.assertEqual(self._rendern('<font size=-1>x</font>'), "<span>x</span>")


class ZeitraumBisFilterTest(SimpleTestCase):
    """Die Datumszeile zeigt bei mehrtaegigen Ganztagsterminen den Zeitraum."""

    def test_mehrtaegig_ganztaegig(self):
        termin = _bannertermin(
            datetime(2026, 9, 18, 0, 0), datetime(2026, 9, 20, 0, 0))
        self.assertEqual(zeitraum_bis(termin), datetime(2026, 9, 20, 0, 0))

    def test_eintaegig_ohne_ende(self):
        self.assertIsNone(zeitraum_bis(_bannertermin(datetime(2026, 9, 18, 0, 0))))

    def test_ende_am_selben_tag_ist_kein_zeitraum(self):
        termin = _bannertermin(
            datetime(2026, 9, 18, 0, 0), datetime(2026, 9, 18, 0, 0))
        self.assertIsNone(zeitraum_bis(termin))

    def test_mit_uhrzeit_kein_zeitraum(self):
        # Zeitgebundene Termine behalten ihre bisherige Datumszeile.
        termin = _bannertermin(
            datetime(2026, 9, 18, 18, 0), datetime(2026, 9, 20, 14, 0))
        self.assertIsNone(zeitraum_bis(termin))

    def test_none(self):
        self.assertIsNone(zeitraum_bis(None))


class AufstellungTest(SimpleTestCase):
    """Die Bühnengrafik der Terminliste: Platz, Spiegelung, Zahlen."""

    MITGLIEDER = [
        (1, "Sa", "Eins", "S"), (2, "Sa", "Zwei", "S"), (3, "Sa", "Drei", "S"),
        (4, "Al", "Eins", "A"), (5, "Al", "Zwei", "A"),
        (6, "Te", "Eins", "T"), (7, "Ba", "Eins", "B"),
        (8, "Chor", "Leiter", "C"), (9, "Mu", "Siker", "M"), (10, "Ohne", "Stimme", "N"),
    ]

    def _stati(self, kaestchen):
        return [k["status"] for k in kaestchen]

    def test_plaetze(self):
        a = aufstellung(self.MITGLIEDER, [])
        self.assertEqual([len(a["hinten"][0]), len(a["hinten"][1])], [1, 1])
        self.assertEqual([len(a["vorn"][0]), len(a["vorn"][1])], [3, 2])
        self.assertEqual([k["titel"] for k in a["extra"]],
                         ["Chor Leiter – Offen", "Mu Siker – Offen"])
        # Stimme N taucht nirgends auf, auch nicht in den Zahlen
        self.assertEqual(a["zahlen"]["offen"], 9)

    def test_zusagen_zur_mitte(self):
        zusagen = [(1, "2"), (2, "1"), (3, "3"), (4, "1"), (5, "2")]
        a = aufstellung(self.MITGLIEDER, zusagen)
        # links vom Gang: außen Absage, innen Zusage
        self.assertEqual(self._stati(a["vorn"][0]), ["no", "maybe", "yes"])
        # rechts gespiegelt
        self.assertEqual(self._stati(a["vorn"][1]), ["yes", "no"])

    def test_fehlend_offen_und_letzte_zusage_gewinnt(self):
        a = aufstellung(self.MITGLIEDER, [(6, "2"), (6, "1")])
        self.assertEqual(self._stati(a["hinten"][0]), ["yes"])
        self.assertEqual(self._stati(a["hinten"][1]), ["na"])

    def test_ich_und_zahlen(self):
        zusagen = [(1, "1"), (4, "1"), (5, "1"), (6, "3"), (7, "2"), (8, "1"), (10, "1")]
        a = aufstellung(self.MITGLIEDER, zusagen, ich_id=4)
        alle = [*a["hinten"][0], *a["hinten"][1], *a["vorn"][0], *a["vorn"][1], *a["extra"]]
        self.assertEqual([k["titel"] for k in alle if k["ich"]], ["Al Eins – Zusage"])
        self.assertEqual(a["zahlen"], {
            "zusagen": 4, "vielleicht": 1, "offen": 3, "absagen": 1,
        })
        self.assertEqual(a["label"], "4 Zusagen, 1 Eventuell, 3 offen, 1 Absagen")

    def test_template(self):
        a = aufstellung(self.MITGLIEDER, [(1, "1")], ich_id=1)
        html = render_to_string("_aufstellung.html", {"value": a})
        self.assertEqual(html.count('class="aufst-p '), 9)
        self.assertIn("aufst-yes aufst-ich", html)
        self.assertIn('aria-label="1 Zusagen, 0 Eventuell, 8 offen, 0 Absagen"', html)
        self.assertNotIn("att-count", html)
        self.assertNotIn("aufst-gross", html)
        self.assertEqual(render_to_string("_aufstellung.html", {"value": None}).strip(), "")

    def test_karte_auf_der_terminseite(self):
        termin = SimpleNamespace(id=1, anwesenheit=True,
                                 aufstellung=aufstellung(self.MITGLIEDER, []))
        html = render_to_string("_termin_aufstellung_karte.html", {"termin": termin})
        self.assertIn('id="aufstellung-section"', html)
        self.assertIn("aufst aufst-gross", html)
        self.assertNotIn("hx-swap-oob", html)
        # ohne Zu-/Absage hängt der View keine Aufstellung an → keine Karte
        leer = SimpleNamespace(id=2, anwesenheit=False)
        self.assertEqual(render_to_string("_termin_aufstellung_karte.html", {"termin": leer}).strip(), "")

    def test_karte_kommt_mit_der_zusage_antwort(self):
        # Nach „Zusagen" tauscht htmx die Karte out-of-band aus; das Widget der
        # Terminseite selbst (widget_only) rendert sie nicht doppelt.
        termin = SimpleNamespace(id=1, anwesenheit=True,
                                 aufstellung=aufstellung(self.MITGLIEDER, [(1, "1")], ich_id=1))
        kontext = {"termin": termin, "my_option": "1", "stimme_groups": []}
        html = render_to_string("_termin_zusage.html", kontext)
        self.assertRegex(html, r'id="aufstellung-section"[^>]*hx-swap-oob="true"')
        html = render_to_string("_termin_zusage.html", {**kontext, "widget_only": True})
        self.assertNotIn("aufstellung-section", html)


class ExternKarteTest(SimpleTestCase):
    """Die Karte „Extern" der Terminseite erscheint nur bei gefuelltem Feld."""

    def _karte(self, wert):
        return render_to_string(
            "_termin_extern_karte.html", {"termin": SimpleNamespace(extern=wert)}
        )

    def test_ohne_text_keine_karte(self):
        for wert in (None, "", " "):
            with self.subTest(wert=wert):
                self.assertEqual(self._karte(wert).strip(), "")

    def test_mit_text_karte_mit_ueberschrift_und_tooltip(self):
        html = self._karte("<h1>Konzert</h1>")
        self.assertIn('id="extern-section"', html)
        self.assertIn("<strong>Konzert</strong>", html)
        self.assertIn("data-hilfe=", html)
        # Der Hilfetooltip nennt das Feld beim Namen (sonst stuende dort das
        # kleine verbose_name „extern").
        self.assertIn("Erklärung: Extern", html)


class TerminMarkerSpaltenTest(SimpleTestCase):
    """Die zwei Markerspalten der Terminliste: Mikrofon und Repertoire-Pille."""

    def _auftritt(self, **felder):
        vorgabe = {"extern": None, "repertoire": False}
        vorgabe.update(felder)
        return TerminTabelle([]).render_auftritt(SimpleNamespace(**vorgabe))

    def _lieder(self, value, **felder):
        vorgabe = {"extern": None, "repertoire": False}
        vorgabe.update(felder)
        return TerminTabelle([]).render_lieder(value, SimpleNamespace(**vorgabe))

    def test_mikrofon_nur_bei_ankuendigungstext(self):
        self.assertIn("marker-icon",
                      self._auftritt(extern="<h1>Konzert</h1>"))
        for wert in (None, ""):
            with self.subTest(wert=wert):
                self.assertNotIn("marker-icon", self._auftritt(extern=wert))

    def test_leerraum_zaehlt_als_ankuendigung(self):
        """Das **rohe** Feld entscheidet, nicht der Anzeige-Filter ``extern_html``:
        ein einzelnes Leerzeichen listet den Termin auf der Startseite
        (``intern/views/auth.py``) und traegt daher auch hier das Mikrofon."""
        self.assertIn("marker-icon", self._auftritt(extern=" "))

    def test_pille_nur_bei_repertoire_und_eintraegen(self):
        html = self._lieder(3, repertoire=True)
        self.assertIn('class="badge"', html)
        self.assertIn(">3</span>", html)
        self.assertIn('title="Lieder im Ablauf: 3"', html)
        for wert, felder in ((0, {"repertoire": True}),
                             (3, {"repertoire": False})):
            with self.subTest(wert=wert, **felder):
                self.assertNotIn("badge", self._lieder(wert, **felder))

    def test_beide_spalten_getrennt(self):
        """Mikrofon und Pille liegen in eigenen Spalten — jede Zelle traegt nur
        ihre eigene Auszeichnung, keine die andere mit."""
        self.assertNotIn("badge", self._auftritt(extern="Konzert", repertoire=True))
        self.assertNotIn("marker-icon", self._lieder(2, extern="Konzert", repertoire=True))

    def test_beide_spalten_schmal_und_in_flucht(self):
        """Beide Spalten sind gleich gebaut (dieselben CSS-Klassen), damit ihre
        Zellen untereinander fluchten; der Leerfall bleibt leer statt „—"."""
        tabelle = TerminTabelle([])
        for name in ("auftritt", "lieder"):
            with self.subTest(spalte=name):
                attrs = tabelle.base_columns[name].attrs
                self.assertEqual(attrs["td"]["class"], "marker-cell")
                self.assertEqual(attrs["th"]["class"], "marker-cell-head")
                self.assertFalse(tabelle.base_columns[name].orderable)
        self.assertEqual(self._auftritt(), "")
        self.assertEqual(self._lieder(0, repertoire=True), "")


class KalenderAuftrittIconTest(SimpleTestCase):
    """Das Mikrofon im Kalender-Chip: bei Ankuendigungstext, nur am Starttag."""

    def _termin(self, **felder):
        vorgabe = {
            "id": 7,
            "kurz": "Konzert Lutherkirche",
            "repertoire": False,
            "extern": None,
            "datum": datetime(2026, 11, 1, 18, 30),
        }
        vorgabe.update(felder)
        return SimpleNamespace(**vorgabe)

    def _tag(self, termin, mehrtaegig=False, start=True, ende=True):
        occ = SimpleNamespace(t=termin, mehrtaegig=mehrtaegig, start=start, ende=ende)
        return SimpleNamespace(tag=1, label="Sonntag, 1. November 2026",
                               iso="2026-11-01", im_monat=True, ist_heute=False,
                               wochenende=True, termine=[occ], geburtstage=[])

    def _grid(self, tag):
        """Eine Woche mit einem belegten Tag; die uebrigen bleiben leer, damit
        kein Geburtstags-Chip sein eigenes ``cal-chip-icon`` beisteuert."""
        leer = [
            SimpleNamespace(tag=i, label="", iso="", im_monat=False, ist_heute=False,
                            wochenende=False, termine=[], geburtstage=[])
            for i in (2, 3, 4, 5, 6, 7)
        ]
        return render_to_string("_kalender_grid.html", {
            "wochen": [[tag, *leer]],
            "wochentage": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
            "monatsname": "November", "jahr": 2026,
            "prev_jahr": 2026, "prev_monat": 10,
            "next_jahr": 2026, "next_monat": 12,
            "heute_jahr": 2026, "heute_monat": 11,
            "ist_aktueller_monat": True,
        })

    def test_icon_nur_bei_ankuendigungstext(self):
        self.assertIn("cal-chip-icon",
                      self._grid(self._tag(self._termin(extern="Konzert"))))
        for wert in (None, ""):
            with self.subTest(wert=wert):
                self.assertNotIn("cal-chip-icon",
                                 self._grid(self._tag(self._termin(extern=wert))))

    def test_icon_nur_am_ersten_tag_eines_balkens(self):
        termin = self._termin(extern="Chorfreizeit")
        fort = self._tag(termin, mehrtaegig=True, start=False, ende=False)
        self.assertNotIn("cal-chip-icon", self._grid(fort))
        anfang = self._tag(termin, mehrtaegig=True, start=True, ende=False)
        self.assertIn("cal-chip-icon", self._grid(anfang))

    def test_konzertfarbe_haengt_nicht_am_mikrofon(self):
        """``is-konzert`` folgt ``repertoire``, das Mikrofon ``extern`` — die
        beiden Merkmale sind unabhaengig voneinander."""
        html = self._grid(self._tag(self._termin(repertoire=True, extern=None)))
        self.assertIn("is-konzert", html)
        self.assertNotIn("cal-chip-icon", html)


class RundmailSerieTest(SimpleTestCase):
    """Serienversand der Rundmail: eine Verbindung, Wiederholung, kein Abbruch."""

    def test_alle_erfolgreich_ohne_neu_verbinden(self):
        from intern.mail import versende_serie
        neu = mock.Mock()
        gesendet, fehl = versende_serie([1, 2, 3], lambda e: True, neu)
        self.assertEqual(gesendet, [1, 2, 3])
        self.assertEqual(fehl, [])
        neu.assert_not_called()

    def test_fehler_verbindet_neu_und_wiederholt_einmal(self):
        from intern.mail import versende_serie
        # Empfänger 2 scheitert beim ersten Versuch (Verbindung weg), klappt beim zweiten;
        # Empfänger 3 scheitert zweimal — Empfänger 4 bekommt seine Mail trotzdem.
        ergebnisse = {1: [True], 2: [False, True], 3: [False, False], 4: [True]}
        neu = mock.Mock()
        gesendet, fehl = versende_serie([1, 2, 3, 4], lambda e: ergebnisse[e].pop(0), neu)
        self.assertEqual(gesendet, [1, 2, 4])
        self.assertEqual(fehl, [3])
        self.assertEqual(neu.call_count, 2)

    def test_neu_verbinden_uebersteht_fehler(self):
        from intern.mail import neu_verbinden
        conn = mock.Mock()
        conn.close.side_effect = OSError("tot")
        conn.open.side_effect = OSError("weg")
        neu_verbinden(conn)  # darf nicht werfen
        conn.open.assert_called_once()

    def test_backend_ohne_host_oeffnet_nichts(self):
        from intern.email_backend import DbEmailBackend
        with mock.patch("intern.app_settings.get_config", return_value=""), \
                mock.patch("intern.app_settings.get_config_int", return_value=25), \
                mock.patch("intern.app_settings.get_config_bool", return_value=False):
            backend = DbEmailBackend()
        with mock.patch("smtplib.SMTP") as smtp:
            self.assertFalse(backend.open())
        smtp.assert_not_called()

    def test_thread_teilt_eine_verbindung_und_protokolliert_ergebnis(self):
        from intern.views import mitglieder
        conn = mock.Mock()
        empfaenger = [
            {"pk": 1, "name": "Anna A", "email": "a@x.de"},
            {"pk": 2, "name": "Bert B", "email": "b@x.de"},
        ]
        with mock.patch.object(mitglieder, "get_connection", return_value=conn), \
                mock.patch.object(mitglieder, "konfiguration_gepuffert"), \
                mock.patch.object(mitglieder, "send_config_mail",
                                  side_effect=[True, False, False]) as senden, \
                mock.patch.object(mitglieder, "_log_notify") as log, \
                mock.patch.object(mitglieder.connections, "close_all"):
            user = mock.Mock(first_name="Carla", last_name="C", username="carla")
            mitglieder._rundmail_versenden(user, "Betreff", "Text", empfaenger, [], "", [])
        conn.open.assert_called()
        self.assertTrue(all(c.kwargs["context"]["absender_name"] == "Carla C"
                            for c in senden.call_args_list))
        self.assertTrue(all(c.kwargs["connection"] is conn for c in senden.call_args_list))
        self.assertEqual([c.kwargs["vorname"] for c in senden.call_args_list],
                         ["Anna", "Bert", "Bert"])
        conn.close.assert_called()
        args, kwargs = log.call_args
        self.assertEqual(args[3], 1)
        self.assertEqual(kwargs["failed"], [empfaenger[1]])


class TabellenzustandTest(SimpleTestCase):
    """Die Liste merkt sich Sortierung und Filter im Cookie und leitet vor dem Rendern um."""

    PFAD = "/intern/mitglied/"

    def setUp(self):
        from django.http import HttpResponse
        from django.test import RequestFactory
        from intern.views._decorators import tabellenzustand, zustand_cookie

        self.rf = RequestFactory()
        self.aufrufe = []
        self.status = 200

        def view(request):
            self.aufrufe.append(request)
            return HttpResponse(status=self.status)

        self.view = tabellenzustand(view)
        self.cookie = zustand_cookie(self.PFAD)

    def _get(self, query="", cookie=None, referer=None, **extra):
        if referer:
            extra["HTTP_REFERER"] = referer
        request = self.rf.get(self.PFAD + query, **extra)
        if cookie is not None:
            request.COOKIES[self.cookie] = cookie
        return self.view(request)

    def test_parameter_werden_ohne_offset_gemerkt(self):
        from urllib.parse import unquote
        response = self._get("?sort=stimme&aktiv=true&offset=50")
        self.assertEqual(response.status_code, 200)
        morsel = response.cookies[self.cookie]
        self.assertEqual(unquote(morsel.value), "sort=stimme&aktiv=true")
        self.assertEqual(morsel["path"], self.PFAD)
        self.assertTrue(morsel["httponly"])

    def test_ohne_parameter_von_anderswo_leitet_um_ohne_zu_rendern(self):
        response = self._get(cookie="sort%3Dstimme%26offset%3D50",
                             referer="https://portal.example/intern/termin/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], self.PFAD + "?sort=stimme")
        self.assertEqual(self.aufrufe, [])

    def test_von_derselben_liste_ohne_parameter_vergisst_den_zustand(self):
        response = self._get("?", cookie="sort%3Dstimme",
                             referer="https://portal.example" + self.PFAD + "?sort=stimme")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.aufrufe), 1)
        self.assertEqual(response.cookies[self.cookie]["max-age"], 0)

    def test_ohne_cookie_normal_rendern(self):
        response = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.aufrufe), 1)
        self.assertNotIn(self.cookie, response.cookies)

    def test_leerer_oder_nur_offset_cookie_leitet_nicht_um(self):
        self.assertEqual(self._get(cookie="offset%3D50").status_code, 200)
        self.assertEqual(self._get(cookie="").status_code, 200)

    def test_nachladen_und_post_laufen_durch(self):
        response = self._get("?sort=stimme&offset=50", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertNotIn(self.cookie, response.cookies)
        response = self._get(cookie="sort%3Dstimme", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        request = self.rf.post(self.PFAD + "?sort=stimme", {"columns": ["name"]})
        self.assertNotIn(self.cookie, self.view(request).cookies)
        self.assertEqual(len(self.aufrufe), 3)

    def test_fehlerantwort_wird_nicht_gemerkt(self):
        self.status = 404
        self.assertNotIn(self.cookie, self._get("?sort=stimme").cookies)

    def test_cookie_name_pro_pfad(self):
        from intern.views._decorators import zustand_cookie
        self.assertNotEqual(zustand_cookie("/intern/ordner/1/"),
                            zustand_cookie("/intern/ordner/12/"))

    def test_datei_sprung_wird_nicht_gemerkt(self):
        from urllib.parse import unquote
        response = self._get("?sort=name&datei=7")
        self.assertEqual(unquote(response.cookies[self.cookie].value), "sort=name")

    def test_datei_sprung_ueberlebt_die_umleitung(self):
        response = self._get("?datei=7", cookie="sort%3D-modified",
                             referer="https://portal.example/intern/artikel/X/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], self.PFAD + "?sort=-modified&datei=7")
        self.assertEqual(self.aufrufe, [])


class ArtikelDateiVerweisTest(SimpleTestCase):
    """Upload und Löschen aus der Artikelansicht ändern den Text über zwei
    reine Funktionen in intern.replacements."""

    def test_voranstellen_in_reihenfolge(self):
        from intern.replacements import dateien_voranstellen
        self.assertEqual(
            dateien_voranstellen("Text\n", ["a.jpg", "b.pdf"]),
            "[[Datei:a.jpg]]\n[[Datei:b.pdf]]\nText\n",
        )

    def test_voranstellen_ueberspringt_vorhandene_und_doppelte(self):
        from intern.replacements import dateien_voranstellen
        text = "Oben\n[[Datei: a.jpg |Bild]]\n"
        self.assertEqual(
            dateien_voranstellen(text, ["a.jpg", "b.jpg", "b.jpg", ""]),
            "[[Datei:b.jpg]]\n" + text,
        )

    def test_voranstellen_in_leeren_text(self):
        from intern.replacements import dateien_voranstellen
        self.assertEqual(dateien_voranstellen("", ["a.jpg"]), "[[Datei:a.jpg]]\n")

    def test_entfernen_nimmt_die_eigene_zeile_mit(self):
        from intern.replacements import datei_verweis_entfernen
        self.assertEqual(
            datei_verweis_entfernen("[[Datei:a.jpg]]\nText\n[[Datei:a.jpg|Titel]]\n", "a.jpg"),
            "Text\n",
        )

    def test_entfernen_mitten_im_satz_laesst_den_rest_stehen(self):
        from intern.replacements import datei_verweis_entfernen
        self.assertEqual(
            datei_verweis_entfernen("Siehe [[Datei:a.jpg]] hier.\n", "a.jpg"),
            "Siehe  hier.\n",
        )

    def test_entfernen_laesst_fremde_namen_stehen(self):
        from intern.replacements import datei_verweis_entfernen
        text = "[[Datei:a.jpg.bak]]\n[[Datei:b.jpg]]\n"
        self.assertEqual(datei_verweis_entfernen(text, "a.jpg"), text)


class StandardOrdnerTest(SimpleTestCase):
    """intern.folders: die Standard-Ordner liegen unter Backstage und werden
    ab der Wurzel über ihren ganzen Pfad gesucht."""

    def setUp(self):
        from intern import folders
        folders.invalidate()
        self.addCleanup(folders.invalidate)

    def test_alles_unter_backstage_ausser_dem_verein_zweig(self):
        from intern import folders
        unter_verein = {
            "verein": (folders.VEREIN,),
            "vorstand": (folders.VEREIN, folders.VORSTAND),
            "mitgliedsantraege": (folders.VEREIN, folders.VORSTAND, folders.MITGLIEDSANTRAEGE),
        }
        for schluessel, pfad in folders.PFADE.items():
            if schluessel == "backstage":
                self.assertEqual(pfad, (folders.BACKSTAGE,))
            elif schluessel in unter_verein:
                self.assertEqual(pfad, unter_verein[schluessel])
            else:
                self.assertEqual(pfad[0], folders.BACKSTAGE, schluessel)
                self.assertGreater(len(pfad), 1, schluessel)

    def test_pfade_eindeutig_und_eltern_zuerst(self):
        """Die Ersteinrichtung legt die Ordner in dieser Reihenfolge an."""
        from intern import folders
        pfade = list(folders.PFADE.values())
        self.assertEqual(len(pfade), len(set(pfade)))
        for i, pfad in enumerate(pfade):
            if len(pfad) > 1:
                self.assertIn(pfad[:-1], pfade[:i], pfad)

    def test_startordner_eltern_zuerst_und_ohne_schraegstrich(self):
        """Die Ersteinrichtung legt STARTORDNER nach PFADE an; "/" ist in Ordnernamen gesperrt."""
        from intern import folders
        bekannt = set(folders.PFADE.values())
        for pfad in folders.STARTORDNER:
            if len(pfad) > 1:
                self.assertIn(pfad[:-1], bekannt, pfad)
            self.assertNotIn(pfad, folders.PFADE.values(), pfad)
            bekannt.add(pfad)
        for pfad in (*folders.PFADE.values(), *folders.STARTORDNER):
            for name in pfad:
                self.assertNotIn("/", name, pfad)

    def test_jede_zugriffsfunktion_hat_einen_pfad(self):
        from intern import folders
        for schluessel in folders.PFADE:
            self.assertTrue(callable(getattr(folders, schluessel)), schluessel)

    def test_sucht_jede_ebene_mit_ihrem_elternordner(self):
        from intern import folders
        ids = {
            (folders.VEREIN, None): 1,
            (folders.VORSTAND, 1): 2,
            (folders.MITGLIEDSANTRAEGE, 2): 3,
        }

        def filter_(name, parent_id):
            pk = ids.get((name, parent_id))
            return mock.Mock(first=lambda: SimpleNamespace(pk=pk) if pk else None)

        with mock.patch("filer.models.Folder.objects") as objects:
            objects.filter.side_effect = filter_
            self.assertEqual(folders.mitgliedsantraege(), 3)
            self.assertEqual(objects.filter.call_count, 3)
            # Zweiter Aufruf kommt aus dem Cache.
            self.assertEqual(folders.mitgliedsantraege(), 3)
            self.assertEqual(objects.filter.call_count, 3)

    def test_gleichnamiger_ordner_an_anderer_stelle_zaehlt_nicht(self):
        """Ein "Repertoire" an der Wurzel ist nicht Backstage/Repertoire."""
        from intern import folders

        def filter_(name, parent_id):
            pk = 7 if (name, parent_id) == (folders.REPERTOIRE, None) else None
            return mock.Mock(first=lambda: SimpleNamespace(pk=pk) if pk else None)

        with mock.patch("filer.models.Folder.objects") as objects:
            objects.filter.side_effect = filter_
            self.assertIsNone(folders.musik())


class ForumGelesenTest(SimpleTestCase):
    """Pure half of the forum unread markers (intern/forum_gelesen.py)."""

    def test_eigene_nachricht_nie_ungelesen(self):
        from intern.forum_gelesen import ist_ungelesen

        self.assertFalse(ist_ungelesen(10, 7, 5, 7))
        self.assertTrue(ist_ungelesen(10, 8, 5, 7))
        self.assertTrue(ist_ungelesen(10, None, 5, 7))
        self.assertFalse(ist_ungelesen(5, 8, 5, 7))

    def test_ohne_letzten_besuch_kein_trenner(self):
        from intern.forum_gelesen import trenner_id

        self.assertIsNone(trenner_id([(12, 8), (11, 8)], None, 7))

    def test_nichts_ungelesen(self):
        from intern.forum_gelesen import trenner_id

        self.assertIsNone(trenner_id([(12, 8), (11, 8)], 12, 7))

    def test_nur_eigene_ungelesen(self):
        from intern.forum_gelesen import trenner_id

        self.assertIsNone(trenner_id([(14, 7), (13, 7), (12, 8)], 12, 7))

    def test_trenner_unter_aeltester_fremder_ungelesener(self):
        from intern.forum_gelesen import trenner_id

        nachrichten = [(16, 8), (15, 7), (14, None), (13, 7), (12, 8)]
        self.assertEqual(trenner_id(nachrichten, 12, 7), 14)

    def test_alles_ungelesen(self):
        from intern.forum_gelesen import trenner_id

        self.assertEqual(trenner_id([(3, 8), (2, 9), (1, 8)], 0, 7), 1)

    def test_trenner_bleibt_weg_wenn_aeltere_ungelesene_steht(self):
        """Mehr als 25 ungelesene Nachrichten: der älteste Ungelesene liegt hinter dem
        25er-Fenster von ``forum_view``, die Linie ließe sich dort nicht wahrheitsgemäß
        platzieren — sie bleibt ganz weg (docs/forum.md, „none if it lies further back").
        Daten wie in Forum 250: alles ungelesen bei ``bis_id=12``."""
        from intern.forum_gelesen import trenner_id

        nachrichten = [(68, 4), (67, 4), (61, 4), (25, 9), (24, 9), (23, 9)]
        self.assertIsNone(trenner_id(nachrichten, 12, 2, aeltere_ungelesen=True))

    def test_trenner_bleibt_bei_nur_aelteren_gelesenen(self):
        """Gegenstück: ohne ältere Ungelesene verhält sich ``trenner_id`` wie bisher."""
        from intern.forum_gelesen import trenner_id

        nachrichten = [(68, 4), (67, 4), (61, 4), (60, 4), (12, 3), (10, 31)]
        self.assertEqual(trenner_id(nachrichten, 60, 2, aeltere_ungelesen=False), 61)
        self.assertEqual(trenner_id(nachrichten, 12, 2, aeltere_ungelesen=False), 60)

    def test_mitteilungen_sind_nach_id_sortiert(self):
        """Gepinnt: ``trenner_id`` liefert die kleinste ungelesene id, und
        ``_messages.html`` setzt den Trenner hinter genau diese Nachricht. Das
        trennt nur dann sauber, wenn die Liste selbst nach id absteigt. ``datum``
        taugt dafür nicht — es hat Sekundenauflösung, und bei Gleichstand ist die
        Reihenfolge undefiniert."""
        from intern.models import Mitteilung

        self.assertEqual(list(Mitteilung._meta.ordering), ["-id"])

    def test_trenner_teilt_absteigende_liste_sauber(self):
        """Der Vertrag, den ``_messages.html`` rendert: über dem Trenner steht nur
        Neues (fremd-ungelesen oder eigenes), darunter nur Gelesenes. Die Daten
        sind der Gleichstand aus Forum 146 — vier Nachrichten in einer Sekunde."""
        from intern.forum_gelesen import ist_ungelesen, trenner_id

        ich = 7
        bis = 115
        nachrichten = [(119, 29), (118, 29), (117, 29), (116, 29), (115, 8)]
        trenner = trenner_id(nachrichten, bis, ich)
        self.assertEqual(trenner, 116)

        ueber = [n for n in nachrichten if n[0] >= trenner]
        darunter = [n for n in nachrichten if n[0] < trenner]
        self.assertEqual(len(ueber), 4)
        for nid, sender in ueber:
            self.assertTrue(
                ist_ungelesen(nid, sender, bis, ich) or sender == ich,
                f"#{nid} steht über dem Trenner, ist aber gelesen",
            )
        for nid, sender in darunter:
            self.assertFalse(
                ist_ungelesen(nid, sender, bis, ich),
                f"#{nid} steht unter dem Trenner, ist aber ungelesen",
            )


class ZusageConstraintTest(SimpleTestCase):
    """Der Antwort-Constraint aus ``intern/models.py``.

    Gepinnt, weil er wie eine bloße Deklaration aussieht und ein späterer
    Aufräumer ihn sonst für entbehrlich hält. Ohne ihn wirft
    ``Zusage.objects.update_or_create(person=…, termin=…)`` in
    ``views/termine.py`` bei vorhandenen Dubletten ``MultipleObjectsReturned``,
    und ein angezeigter Zähler zählt dieselbe Antwort doppelt.
    """

    def test_genau_ein_unique_constraint_auf_person_und_termin(self):
        from intern.models import Zusage

        constraints = list(Zusage._meta.constraints)
        self.assertEqual(len(constraints), 1)
        [constraint] = constraints
        self.assertEqual(tuple(constraint.fields), ("person", "termin"))
        self.assertEqual(constraint.name, "uniq_zusage_person_termin")

    def test_kein_zweiter_mechanismus_daneben(self):
        from intern.models import Zusage

        self.assertEqual(list(Zusage._meta.unique_together), [])


class AbstimmungConstraintTest(SimpleTestCase):
    """Der Stimmen-Constraint — bewusst ein Dreier.

    Ein Constraint auf ``(person, abstimmung)`` wäre falsch: die Abstimmung ist
    mehrfach-wählbar (``max_stimmen``, ``views/abstimmung.py``). Verboten ist nur
    die doppelte *gleiche* Stimme, und die kann entstehen, weil die Stimmabgabe
    ``delete()`` + ``bulk_create()`` ist und damit nicht atomar.
    """

    def test_dreier_constraint_erlaubt_mehrfachwahl(self):
        from intern.models import Abstimmung

        constraints = list(Abstimmung._meta.constraints)
        self.assertEqual(len(constraints), 1)
        [constraint] = constraints
        self.assertEqual(
            tuple(constraint.fields), ("person", "abstimmung", "option")
        )

    def test_index_fuer_filter_und_auswertung(self):
        from intern.models import Abstimmung

        felder = [tuple(index.fields) for index in Abstimmung._meta.indexes]
        self.assertIn(("abstimmung", "person"), felder)


class AbstimmungEndePflichtTest(SimpleTestCase):
    """Das Ende der Abstimmung ist Pflicht (``intern/replacements.py``).

    Ohne Datum bliebe die Abstimmung für immer offen — die Direktive greift
    deshalb nicht mehr, und die Zeile steht im Artikel, wie sie geschrieben
    wurde. Reine Textarbeit, kein Datenbankzugriff.
    """

    def test_mit_ende_wird_gelesen(self):
        from intern.replacements import parse_abstimmung_directive

        self.assertEqual(
            parse_abstimmung_directive("{abstimmung:Wahl:2:31.12.2027:a;b}", "Wahl"),
            (2, ["a", "b"], date(2027, 12, 31)),
        )

    def test_ohne_ende_kein_treffer(self):
        from intern.replacements import parse_abstimmung_directive

        self.assertIsNone(
            parse_abstimmung_directive("{abstimmung:Wahl:2:a;b}", "Wahl")
        )

    def test_unmoegliches_datum_zaehlt_nicht(self):
        # „31.02.2027“ passt aufs Muster, ist aber kein Tag im Kalender. Ohne
        # diesen Zweig stünde dort eine Abstimmung ganz ohne Ende.
        from intern.replacements import parse_abstimmung_directive

        self.assertIsNone(
            parse_abstimmung_directive("{abstimmung:Wahl:2:31.02.2027:a;b}", "Wahl")
        )

    def test_unmoegliches_datum_bleibt_rohtext(self):
        from unittest.mock import Mock

        from intern.replacements import ABSTIMMUNG_DIRECTIVE, abstimmung

        zeile = "{abstimmung:Wahl:2:31.02.2027:a;b}"
        treffer = re.match(ABSTIMMUNG_DIRECTIVE, zeile, re.IGNORECASE)
        request = Mock()
        request.resolver_match.kwargs = {"name": "Seite"}

        self.assertEqual(abstimmung(treffer, request), zeile)


class AbstimmungOhneEndeTest(SimpleTestCase):
    """Was die Bearbeiten-Seite vor dem Speichern beanstandet.

    ``abstimmungen_ohne_ende`` sieht nur auf den Zeilenanfang: die geschützten
    und die im Fließtext zitierten Beispiele rendern ohnehin nicht und dürfen
    niemanden aufhalten.
    """

    @staticmethod
    def _pruefen(text):
        from intern.replacements import abstimmungen_ohne_ende

        return abstimmungen_ohne_ende(text)

    def test_zeile_ohne_ende_wird_gemeldet(self):
        text = "Vorspann\n{abstimmung:Wahl:2:a;b}\nNachsatz"

        self.assertEqual(self._pruefen(text), [(2, "{abstimmung:Wahl:2:a;b}")])

    def test_gueltige_zeile_geht_durch(self):
        self.assertEqual(self._pruefen("{abstimmung:Wahl:2:31.12.2027:a;b}"), [])

    def test_unmoegliches_datum_wird_gemeldet(self):
        text = "{abstimmung:Wahl:2:31.02.2027:a;b}"

        self.assertEqual(self._pruefen(text), [(1, text)])

    def test_beispiele_halten_niemanden_auf(self):
        # Geschützte Zeile, Zitat im Fließtext, Platzhalterform der Erklärung.
        text = (
            " {abstimmung:Wahl:2:a;b}\n"
            "Die Syntax ist ${abstimmung:Name der Abstimmung:max:V1;V2}$.\n"
        )

        self.assertEqual(self._pruefen(text), [])

    def test_leerer_text_geht_durch(self):
        self.assertEqual(self._pruefen(None), [])
        self.assertEqual(self._pruefen(""), [])


class ZusageOptionenTest(SimpleTestCase):
    """Der Optionskatalog (``intern/zusage.py``) — die Drift-Bremse.

    Dieselben Werte und Beschriftungen lagen vorher an fünf Stellen, und zwei
    Kopien waren bereits auseinandergelaufen. Dieser Test kreuzt sie gegeneinander,
    damit eine sechste Kopie oder ein neuer Wert nicht unbemerkt daneben entsteht.
    """

    def test_optionen_und_labels_decken_sich(self):
        from intern import zusage

        self.assertEqual(set(zusage.OPTIONEN), set(zusage.OPTION_LABELS))
        self.assertEqual(len(zusage.OPTIONEN), len(set(zusage.OPTIONEN)))

    def test_labels_wortgleich_zu_den_protokoll_schnappschuessen(self):
        """``str(Zusage)`` liegt als ``ChangeLog.object_repr`` in den Altdaten,
        und ``views/aenderungen.py`` rekonstruiert daraus alte Einträge — eine
        geänderte Beschriftung schriebe die Anzeige der Vergangenheit um."""
        from intern import zusage

        self.assertEqual(
            zusage.OPTION_LABELS,
            {"1": "Zusage", "2": "Absage", "3": "Eventuell", "": "Keine Angabe"},
        )

    def test_transitions_ziele_liegen_im_wertebereich(self):
        from intern import zusage

        for start, ziele in zusage.TRANSITIONS.items():
            self.assertIn(start, zusage.OPTIONEN)
            for ziel in ziele:
                self.assertIn(ziel, zusage.OPTIONEN)

    def test_jede_status_kennung_hat_einen_titel(self):
        from intern import zusage

        for kennung in [*zusage.STATUS.values(), zusage.STATUS_OFFEN]:
            self.assertIn(kennung, zusage.STATUS_TITEL)

    def test_leerstring_none_und_unbekanntes_sind_offen(self):
        from intern import zusage

        self.assertEqual(zusage.status_von(""), "na")
        self.assertEqual(zusage.status_von(None), "na")
        self.assertEqual(zusage.status_von("quatsch"), "na")
        self.assertEqual(zusage.titel_von("1"), "Zusage")

    def test_modell_traegt_denselben_katalog_ohne_kopie(self):
        from intern import zusage
        from intern.models import Zusage

        self.assertIs(Zusage.OPTION_LABELS, zusage.OPTION_LABELS)
        self.assertEqual(
            dict(Zusage._meta.get_field("option").choices), zusage.OPTION_LABELS
        )

    def test_baukasten_bietet_die_antworten(self):
        """Die Zusage-Zeile kennt jede Antwort aus dem Katalog.

        Die Beschriftungen sind hier **Verben** („zugesagt"), weil sie in einem Satz
        stehen („Zusage: Konzert am 12.03.26 — zugesagt"); die Langform aus
        ``zusage.OPTION_LABELS`` bleibt davon unberührt und anderweitig wortgleich.
        """
        from intern import zusage
        from intern import filterbau_mitglieder as filterbau

        beschriftungen = dict(filterbau.ZUSAGE_LABELS)
        # Jede echte Antwortoption ist dabei -- "ohne" steht fuer die leere.
        for wert in zusage.OPTIONEN:
            self.assertIn(wert or "ohne", beschriftungen)
        self.assertEqual(beschriftungen["ohne"], "Keine Angabe")
        self.assertEqual(beschriftungen["beantwortet"], "geantwortet")
        self.assertEqual(dict(zusage.OPTION_LABELS)["1"], "Zusage")
        # Jeder Eintrag bringt beide Satzformen mit; „ohne" braucht ein eigenes Wort,
        # „nicht keine Angabe gemacht" liest sich nicht.
        saetze = {w: (ja, nein) for w, _l, ja, nein in filterbau.ZUSAGE_ANTWORTEN}
        self.assertEqual(saetze["1"], ("hat zugesagt", "hat nicht zugesagt"))
        self.assertEqual(saetze["ohne"], ("hat keine Angabe gemacht", "hat eine Angabe gemacht"))


class RepertoireSucheTest(SimpleTestCase):
    """Die Suche der Titelliste greift über Titel, Komponist und Bearbeiter.

    Das QuerySet wird nie ausgewertet — geprüft wird das kompilierte SQL.
    """

    def _query(self, query):
        from django.http import QueryDict

        from intern.filterbau_titel import TITEL
        from intern.models import Lied

        qs, _bedingungen = TITEL.aus_daten(Lied.objects.all(), QueryDict(query))
        return qs

    def test_suche_umfasst_komponist_und_bearbeiter(self):
        sql = str(self._query("f=und:suche:enthaelt:bach").query)
        for spalte in ("titel", "komponist", "bearbeiter"):
            self.assertIn(f'"{spalte}" LIKE', sql)

    def test_alter_suchparameter_greift_weiter(self):
        # Der gemerkte Filter im Cookie traegt noch „titel" -- jetzt die Suche.
        sql = str(self._query("titel=bach").query)
        for spalte in ("titel", "komponist", "bearbeiter"):
            self.assertIn(f'"{spalte}" LIKE', sql)

    def test_leere_suche_filtert_nicht(self):
        from intern.models import Lied

        for query in ("titel=", "f=und:suche:enthaelt:"):
            self.assertEqual(
                str(self._query(query).query), str(Lied.objects.all().query), query
            )


class TabellenPreferenzenTest(SimpleTestCase):
    """Die globale Vorgabezeile (``person=None``) ist vom ``unique_together``
    **nicht** gedeckt: NULLs gelten im Unique-Index als verschieden, und Django
    kann das nur auf PostgreSQL über ``nulls_distinct=False`` ändern — auf MySQL
    und SQLite wirft es. Deshalb muss der Lesepfad Dubletten aushalten.
    """

    def test_vorgabezeile_bleibt_nullable(self):
        from intern.models import TabellenPreferenzen

        self.assertTrue(TabellenPreferenzen._meta.get_field("person").null)

    def test_unique_together_gilt_fuer_mitgliedszeilen(self):
        from intern.models import TabellenPreferenzen

        self.assertEqual(
            [tuple(t) for t in TabellenPreferenzen._meta.unique_together],
            [("person", "tabelle")],
        )

    def test_lesepfad_haelt_dubletten_aus(self):
        """``visible_fields`` darf kein ``get()`` auf die Vorgabezeile machen —
        eine zweite Vorgabezeile würde sonst jede Tabelle mit
        ``MultipleObjectsReturned`` zerlegen."""
        import inspect

        from intern.views import files

        quelle = inspect.getsource(files.visible_fields)
        self.assertNotIn("objects.get(", quelle)
        self.assertIn(".first()", quelle)


class KonzertOnDeleteTest(SimpleTestCase):
    def test_geloeschtes_lied_nullt_den_ablaufplatz(self):
        """``SET_NULL`` statt ``CASCADE``: ein gelöschtes Lied nimmt seinen Platz im
        Ablauf mit, aber nicht den ganzen Programmpunkt. ``on_delete`` erzeugt kein
        DDL — die Änderung wirkt ohne Schema-Neuaufbau."""
        from django.db import models as django_models

        from intern.models import Konzert

        self.assertIs(
            Konzert._meta.get_field("lied").remote_field.on_delete,
            django_models.SET_NULL,
        )


class ChangeLogIndexTest(SimpleTestCase):
    def test_zeitstempel_indiziert_ohne_doppelten_user_index(self):
        from intern.models import ChangeLog

        felder = [tuple(index.fields) for index in ChangeLog._meta.indexes]
        self.assertIn(("timestamp",), felder)
        # Der FK bringt seinen Index selbst mit; ein zweiter wäre eine Kopie.
        self.assertNotIn(("user",), felder)


class RegisterKonsistenzTest(SimpleTestCase):
    """Die handgepflegten Feldkarten gegen ``_meta``.

    Pro Modell und Feld werden mehrere Karten von Hand nachgeführt
    (``_AUDIT_FIELDS``, ``FIELD_LABELS``, ``_CHANGELOG_FIELD_LABELS``,
    ``_FILE_ID_FIELDS``). Ein Feldname darin ist eine
    **Zeichenkette**: wird ein Feld umbenannt und die Karte nicht, verstummt das
    Änderungsprotokoll für dieses Feld still, ohne dass etwas rot wird. Dieser Test
    kreuzt darum jede Karte gegen die Modelle — und sucht doppelte Dict-Schlüssel,
    denn ein wiederholter Schlüssel im Literal überschreibt den früheren lautlos
    (so geschehen bei ``FIELD_LABELS["gruppe"]``).
    """

    @staticmethod
    def _feldnamen(modell):
        """Alle ansprechbaren Feldnamen eines Modells, inkl. ``*_id``-Attnamen."""
        namen = set()
        for feld in modell._meta.get_fields():
            namen.add(feld.name)
            if hasattr(feld, "attname"):
                namen.add(feld.attname)
        return namen

    def _auditierte_feldnamen(self):
        from django.apps import apps

        from intern.signals import _AUDIT_FIELDS

        alle = set()
        for modellname in _AUDIT_FIELDS:
            alle |= self._feldnamen(apps.get_model("intern", modellname))
        return alle

    def test_audit_felder_gibt_es_wirklich(self):
        from django.apps import apps

        from intern.signals import _AUDIT_FIELDS

        for modellname, felder in _AUDIT_FIELDS.items():
            with self.subTest(modell=modellname):
                vorhanden = self._feldnamen(apps.get_model("intern", modellname))
                self.assertEqual([f for f in felder if f not in vorhanden], [])

    def test_lab_karten_nennen_keine_verschwundenen_felder(self):
        from intern.views.aenderungen import _FK_RESOLVE, _FILE_ID_FIELDS

        vorhanden = self._auditierte_feldnamen()
        for karte, namen in (
            ("_FK_RESOLVE", [k for k in _FK_RESOLVE]),
            ("_FILE_ID_FIELDS", sorted(_FILE_ID_FIELDS)),
        ):
            with self.subTest(karte=karte):
                self.assertEqual([n for n in namen if n not in vorhanden], [])

    def test_lied_hat_keine_dateifelder_mehr(self):
        """Migration 0006 ist der Punkt ohne Rückweg: Die vier Spalten sind
        fort, und die Rollenzeile trägt die Rolle."""
        from intern.models import Lied

        vorhanden = self._feldnamen(Lied)
        self.assertEqual(
            [f for f in ("original", "aufnahme", "pdf", "noten") if f in vorhanden], []
        )

    def test_wert_uebersetzungen_zielen_auf_auditierte_felder(self):
        from django.apps import apps

        from intern.signals import _AUDIT_FIELDS
        from intern.views.aenderungen import _VALUE_TRANSLATIONS

        for (modellname, feld) in _VALUE_TRANSLATIONS:
            with self.subTest(ziel=f"{modellname}.{feld}"):
                self.assertIn(modellname, _AUDIT_FIELDS)
                vorhanden = self._feldnamen(apps.get_model("intern", modellname))
                self.assertIn(feld, vorhanden)

    def test_modellgenaue_label_weichen_vom_flachen_ab(self):
        """Sonst wäre der Eintrag überflüssig — und genau das Verdrängen, das er
        verhindert, fiele niemandem auf."""
        from intern.views.aenderungen import FIELD_LABELS, _MODELL_FELD_LABELS

        for (modellname, feld), label in _MODELL_FELD_LABELS.items():
            with self.subTest(ziel=f"{modellname}.{feld}"):
                self.assertIn(feld, FIELD_LABELS)
                self.assertNotEqual(label, FIELD_LABELS[feld])

    @staticmethod
    def _dict_schluessel(module, name):
        """Die Schlüssel eines Dict-Literals, gelesen aus der **Quelle** — nur so
        sind doppelte Schlüssel sichtbar, denn nach dem Import hat das Literal den
        früheren Eintrag längst verworfen."""
        quelle = Path(module.__file__).read_text(encoding="utf-8")
        for knoten in ast.walk(ast.parse(quelle)):
            if isinstance(knoten, ast.Assign) and any(
                getattr(ziel, "id", None) == name for ziel in knoten.targets
            ):
                schluessel = []
                for k in knoten.value.keys:
                    try:
                        schluessel.append(ast.literal_eval(k))
                    except ValueError:
                        pass
                return schluessel
        raise AssertionError(f"{name} nicht als Dict-Literal gefunden")

    def test_keine_doppelten_schluessel_in_den_karten(self):
        import intern.signals as signals
        from intern import tables
        from intern.views import aenderungen

        karten = [
            (aenderungen, "FIELD_LABELS"),
            (aenderungen, "MODEL_LABELS"),
            (aenderungen, "_MODELL_FELD_LABELS"),
            (tables, "_CHANGELOG_FIELD_LABELS"),
            (tables, "_CHANGELOG_MODEL_LABELS"),
            (signals, "_AUDIT_FIELDS"),
        ]
        for module, name in karten:
            with self.subTest(karte=name):
                schluessel = self._dict_schluessel(module, name)
                doppelt = {s for s in schluessel if schluessel.count(s) > 1}
                self.assertEqual(doppelt, set())


class MitteilungFormatiertTest(SimpleTestCase):
    """``formatiert()`` muss leeren und fehlenden Text aushalten.

    Die Spalte erlaubt NULL (Altdaten, Nachrichten aus dem XMPP-Bot), und
    ``apply_replacements`` scheitert an ``None`` — auf der Forenseite ein Crash.
    """

    def test_ohne_text_kein_crash(self):
        from intern.models import Mitteilung

        self.assertEqual(Mitteilung(mitteilung=None).formatiert(), "")
        self.assertEqual(Mitteilung(mitteilung="").formatiert(), "")

    def test_text_wird_weiterhin_ersetzt(self):
        from intern.models import Mitteilung

        self.assertIn("<h4>Titel</h4>", Mitteilung(mitteilung="=====Titel=====").formatiert())


class ForumTabelleTest(SimpleTestCase):
    """Die Anzahl-Spalte der Forenliste (``intern/tables.py``).

    Reine Formatierung: der Datensatz ist ein Dummy, kein Datenbankzugriff.
    """

    def _zelle(self, record, gesamt):
        from intern.tables import ForumTabelle

        return ForumTabelle([]).render_anzahl_mitteilungen(record=record, value=gesamt)

    def test_ohne_ungelesene_nur_die_gesamtzahl(self):
        html = self._zelle(SimpleNamespace(ungelesen=0), 17)

        self.assertNotIn("badge", html)
        self.assertIn('<span class="gesamtzahl">17</span>', html)

    def test_badge_steht_vor_der_gesamtzahl(self):
        html = self._zelle(SimpleNamespace(ungelesen=3), 17)

        self.assertIn('<span class="badge badge-primary" title="ungelesen">3</span>', html)
        self.assertIn('<span class="gesamtzahl">17</span>', html)
        self.assertLess(html.index("badge"), html.index("gesamtzahl"))

    def test_ohne_annotation_kein_badge(self):
        # Ein Aufrufer ohne ForumQuerySet.mit_ungelesen() darf die Spalte nicht sprengen.
        html = self._zelle(SimpleNamespace(), 17)

        self.assertNotIn("badge", html)
        self.assertIn('<span class="gesamtzahl">17</span>', html)

    def test_deaktiviertes_forum_heller(self):
        from intern.tables import ForumTabelle

        klasse = ForumTabelle._meta.row_attrs["class"]
        self.assertEqual(klasse(SimpleNamespace(aktiv=True, ungelesen=0)), "")
        self.assertEqual(klasse(SimpleNamespace(aktiv=False, ungelesen=0)), "forum-inaktiv")
        self.assertEqual(
            klasse(SimpleNamespace(aktiv=False, ungelesen=2)), "ungelesen forum-inaktiv"
        )

    def test_bild_aus_dem_annotierten_pfad(self):
        from intern import tables

        with mock.patch.object(tables, "vorschau_url", return_value="/media/vorschau.png") as url:
            html = tables.ForumTabelle([]).render_bild(
                record=SimpleNamespace(bild_pfad="filer/forum.png", bild_oeffentlich=False)
            )
        url.assert_called_once_with("filer/forum.png", oeffentlich=False)
        self.assertIn('src="/media/vorschau.png"', html)

    def test_ohne_bild_leere_zelle(self):
        from intern.tables import ForumTabelle

        self.assertEqual(ForumTabelle([]).render_bild(record=SimpleNamespace(bild_pfad=None)), "")

    def test_bildspalte_vor_dem_thema_und_standardmaessig_aus(self):
        from intern.tables import FORUM_SPALTEN_AUS, ForumTabelle

        spalten = list(ForumTabelle.base_columns)
        self.assertEqual(spalten.index("bild") + 1, spalten.index("thema"))
        self.assertEqual(FORUM_SPALTEN_AUS, {"bild"})


class DatenschutzPruefungTest(SimpleTestCase):
    """Welche Pfade die Datenschutz-Bestaetigung vorschaltet.

    Die Bestaetigungsseite selbst und An-/Abmelden muessen frei bleiben, sonst
    entsteht eine Umleitungsschleife oder man kommt nicht mehr hinaus; die
    Medienpruefung, sonst scheitert jedes Bild an nginx' auth_request.
    """

    def test_interner_bereich_ist_pruefpflichtig(self):
        self.assertTrue(datenschutz_pruefpflichtig("/intern/artikel/Aktuell/"))
        self.assertTrue(datenschutz_pruefpflichtig("/intern/mitglied/"))

    def test_ausserhalb_bleibt_frei(self):
        for pfad in ("/", "/datenschutz/", "/carddav/", "/caldav/", "/admin/", "/static/x.css"):
            self.assertFalse(datenschutz_pruefpflichtig(pfad), pfad)

    def test_ausnahmen_bleiben_frei(self):
        from django.urls import reverse
        for name in ("datenschutz_bestaetigen", "login", "logout", "media_auth"):
            self.assertFalse(datenschutz_pruefpflichtig(reverse(name)), name)

    def test_ausnahmen_treffen_echte_pfade(self):
        # Eine umbenannte URL liesse die Ausnahme ins Leere laufen.
        from django.urls import reverse
        pfade = [
            reverse(n) for n in (
                "datenschutz_bestaetigen", "login", "logout", "media_auth", "register",
            )
        ]
        for praefix in ("/intern/datenschutz-bestaetigen/", "/intern/login/",
                        "/intern/logout/", "/intern/media-auth/", "/intern/register"):
            self.assertIn(praefix, DATENSCHUTZ_FREI)
            self.assertTrue(any(p.startswith(praefix) for p in pfade), praefix)


class DavGzipTest(SimpleTestCase):
    """CardDAV/CalDAV bekommen gzip ohne Dateinamen (``intern/middleware.py``).

    ktor in DAVx⁵ ab 4.5 lehnt das FNAME-Flag ab, das Djangos BREACH-Schutz
    setzt; die HTML-Seiten behalten es.
    """

    INHALT = b"<?xml version='1.0'?>" + b"<D:multistatus/>" * 50

    def _flags(self, pfad):
        from django.http import HttpResponse
        from django.test import RequestFactory
        request = RequestFactory().generic(
            "PROPFIND", pfad, HTTP_ACCEPT_ENCODING="gzip,deflate,identity"
        )
        mw = GZip(lambda r: HttpResponse(self.INHALT, status=207))
        response = mw(request)
        self.assertEqual(response["Content-Encoding"], "gzip")
        return response.content[3]

    def test_dav_ohne_dateiname(self):
        import gzip
        for pfad in ("/carddav/", "/carddav", "/caldav/7/termine/", "/caldav"):
            self.assertFalse(self._flags(pfad) & gzip.FNAME, pfad)

    def test_html_behaelt_dateiname(self):
        import gzip
        self.assertTrue(self._flags("/intern/artikel/Aktuell/") & gzip.FNAME)

    def test_settings_verwendet_unterklasse(self):
        from django.conf import settings
        self.assertIn("intern.middleware.GZip", settings.MIDDLEWARE)
        self.assertNotIn("django.middleware.gzip.GZipMiddleware", settings.MIDDLEWARE)


class SitzungAuffrischenTest(SimpleTestCase):
    """Die Drosselung der Sitzungsfrist (``intern/middleware.py``).

    Reine Logik, ``jetzt`` wird übergeben — kein Datenbankzugriff.
    """

    def test_ohne_stand_faellig(self):
        # Sitzung aus der Zeit vor der Drosselung oder gerade angelegt.
        self.assertTrue(muss_auffrischen(None, 1000, intervall=300))

    def test_innerhalb_des_intervalls_nicht_faellig(self):
        self.assertFalse(muss_auffrischen(1000, 1000, intervall=300))
        self.assertFalse(muss_auffrischen(1000, 1299, intervall=300))

    def test_genau_am_intervall_faellig(self):
        self.assertTrue(muss_auffrischen(1000, 1300, intervall=300))

    def test_aelter_faellig(self):
        self.assertTrue(muss_auffrischen(1000, 99999, intervall=300))

    def test_stand_aus_der_zukunft_faellig(self):
        # Systemuhr zurückgestellt: sonst bliebe die Sitzung bis dahin ungeschrieben.
        self.assertTrue(muss_auffrischen(5000, 1000, intervall=300))

    def test_unbrauchbarer_stand_faellig(self):
        self.assertTrue(muss_auffrischen("kaputt", 1000, intervall=300))


class Tables2SignaturTest(SimpleTestCase):
    """Der Zwischenspeicher für ``django_tables2.utils.signature``.

    Er ersetzt eine Funktion einer Fremdbibliothek (siehe
    ``intern/tables2_beschleunigung.py``); dieser Test hält fest, dass er
    dieselben Antworten gibt wie das Original — auch für den Fall, in dem
    ``inspect.signature`` ``self`` wegkürzt.
    """

    def _vergleiche(self, fn):
        self.assertEqual(signature_gepuffert(fn), tables2_original(fn))
        # zweiter Aufruf kommt aus dem Zwischenspeicher
        self.assertEqual(signature_gepuffert(fn), tables2_original(fn))

    def test_funktion(self):
        def render(record, value, **kwargs):
            return ""

        self._vergleiche(render)

    def test_lambda(self):
        self._vergleiche(lambda record: record)

    def test_gebundene_methode_ohne_self(self):
        class Tabelle:
            def render_spalte(self, record, value):
                return ""

        t = Tabelle()
        # gebunden: ohne self — ungebunden: mit self. Beide Formen derselben
        # Funktion duerfen sich im Zwischenspeicher nicht ueberschreiben.
        self._vergleiche(t.render_spalte)
        self._vergleiche(Tabelle.render_spalte)
        self.assertEqual(signature_gepuffert(t.render_spalte)[0], ("record", "value"))
        self.assertEqual(
            signature_gepuffert(Tabelle.render_spalte)[0], ("self", "record", "value")
        )

    def test_eingebaut(self):
        from django_tables2 import utils

        self.assertIs(utils.signature, signature_gepuffert)


class Tables2AttributeTest(SimpleTestCase):
    """Der Zwischenspeicher für ``BoundColumn.attrs``.

    Er darf nur greifen, wo die Attribute nicht von der Zeile abhängen — sonst
    bekäme jede Zeile die Attribute der ersten.
    """

    def _tabelle(self, spalten_attrs, daten):
        import django_tables2 as tables

        class Tabelle(tables.Table):
            wert = tables.Column(attrs=spalten_attrs)

        return Tabelle(daten)

    def test_feste_attribute_werden_gepuffert(self):
        t = self._tabelle({"td": {"class": "rechts"}}, [{"wert": 1}, {"wert": 2}])
        spalte = list(t.columns)[0]
        erst = spalte.attrs
        self.assertIs(spalte.attrs, erst)  # zweiter Zugriff aus dem Puffer
        self.assertEqual(erst["td"]["class"], "rechts")

    def test_attribute_je_zeile_werden_nicht_gepuffert(self):
        # data-wert hängt am Datensatz: hier muss jede Zelle neu rechnen.
        t = self._tabelle(
            {"td": {"data-wert": lambda record: record["wert"]}},
            [{"wert": 1}, {"wert": 2}],
        )
        zeilen = list(t.rows)
        werte = [
            str(dict(bound.attrs["td"]).get("data-wert"))
            for zeile in zeilen
            for bound, _zelle in zeile.items()
        ]
        self.assertEqual(werte, ["1", "2"])

    def test_html_der_zellen_stimmt(self):
        from django.test import RequestFactory

        t = self._tabelle(
            {"td": {"data-wert": lambda record: record["wert"]}},
            [{"wert": 7}, {"wert": 8}],
        )
        html = t.as_html(RequestFactory().get("/"))
        self.assertIn('data-wert="7"', html)
        self.assertIn('data-wert="8"', html)

    def test_eingebaut(self):
        from django_tables2.columns.base import BoundColumn

        self.assertIs(BoundColumn.attrs.fget, attrs_gepuffert)


class AnfragespeicherTest(SimpleTestCase):
    """Der Zwischenspeicher, der genau eine Anfrage lang lebt.

    Reine Logik, keine Datenbank — ``erzeugen`` ist hier ein Zähler.
    """

    def setUp(self):
        self.aufrufe = 0

    def _erzeugen(self):
        self.aufrufe += 1
        return self.aufrufe

    def test_ohne_anfrage_wird_nichts_gemerkt(self):
        anfrage_verwerfen()
        self.assertEqual(gemerkt("a", self._erzeugen), 1)
        self.assertEqual(gemerkt("a", self._erzeugen), 2)

    def test_innerhalb_einer_anfrage_nur_einmal(self):
        anfrage_anlegen()
        try:
            self.assertEqual(gemerkt("a", self._erzeugen), 1)
            self.assertEqual(gemerkt("a", self._erzeugen), 1)
            # anderer Schlüssel, andere Rechnung
            self.assertEqual(gemerkt("b", self._erzeugen), 2)
        finally:
            anfrage_verwerfen()

    def test_leeren_erzwingt_neuberechnung(self):
        anfrage_anlegen()
        try:
            self.assertEqual(gemerkt("a", self._erzeugen), 1)
            anfrage_leeren()
            self.assertEqual(gemerkt("a", self._erzeugen), 2)
            # der Speicher ist danach weiter offen
            self.assertEqual(gemerkt("a", self._erzeugen), 2)
        finally:
            anfrage_verwerfen()

    def test_verwerfen_beendet_das_merken(self):
        anfrage_anlegen()
        gemerkt("a", self._erzeugen)
        anfrage_verwerfen()
        self.assertEqual(gemerkt("a", self._erzeugen), 2)
        self.assertEqual(gemerkt("a", self._erzeugen), 3)


class SchnellSelectTest(SimpleTestCase):
    """``SchnellSelect`` muss zeichengleich zu ``forms.Select`` rendern.

    Das Widget ersetzt Djangos Vorlage je ``<option>`` (siehe ``intern/forms.py``).
    Weicht eine kommende Django-Fassung ab, soll dieser Test es melden, statt die
    Abweichung still auszuliefern.
    """

    FAELLE = [
        ("leer", [("", "---------"), ("1", "Eins")], None),
        ("ausgewaehlt", [("", "---"), ("1", "Eins"), ("2", "Zwei")], "2"),
        ("gruppen", [("A", [("1", "Eins"), ("2", "Zwei")]), ("B", [("3", "Drei")])], "3"),
        ("sonderzeichen", [("<x>", 'Fu"ss & Ma<ss>'), ("ü", "Öl & Wasser")], "<x>"),
        ("zahlenwert", [(1, "Eins"), (2, "Zwei")], 1),
    ]

    def test_gleiche_ausgabe_wie_django(self):
        for name, choices, wert in self.FAELLE:
            with self.subTest(fall=name):
                attrs = {"class": "filter-inline", "id": "id_f"}
                original = forms.Select(attrs=attrs, choices=choices)
                schnell = SchnellSelect(attrs=attrs, choices=choices)
                self.assertHTMLEqual(
                    schnell.render("f", wert), original.render("f", wert)
                )

    def test_mehrfachauswahl_gleiche_ausgabe(self):
        choices = [("1", "Eins"), ("2", "Zwei"), ("3", "Drei")]
        original = forms.SelectMultiple(choices=choices)
        schnell = SchnellSelectMultiple(choices=choices)
        self.assertHTMLEqual(
            schnell.render("f", ["1", "3"]), original.render("f", ["1", "3"])
        )

    def test_maskierung_bleibt(self):
        # Die Maskierung ist der Grund, warum hier nicht mit Zeichenketten
        # zusammengebaut werden darf.
        schnell = SchnellSelect(choices=[("a", '<script>alert("x")</script>')])
        html = schnell.render("f", "a")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_deaktiviertes_feld(self):
        choices = [("1", "Eins"), ("2", "Zwei")]
        original = forms.Select(choices=choices)
        schnell = SchnellSelect(choices=choices)
        original.attrs["disabled"] = True
        schnell.attrs["disabled"] = True
        self.assertHTMLEqual(schnell.render("f", "1"), original.render("f", "1"))


class VorlagenKommentarTest(SimpleTestCase):
    """``{# … #}`` gilt in Django nur bis zum Zeilenende.

    Über mehrere Zeilen geschrieben ist es kein Kommentar mehr: Django gibt den
    Text aus. Im ``<head>`` beendet das die Kopfzone, der Browser schiebt alles
    Weitere in den Körper — die Seite sieht zerlegt aus. Genau das ist einmal in
    Betrieb gegangen, deshalb dieser Test. Mehrzeilig gehört
    ``{% comment %}…{% endcomment %}``.
    """

    @staticmethod
    def _vorlagen():
        wurzel = Path(__file__).resolve().parent.parent
        for verzeichnis in (wurzel / "intern" / "templates", wurzel / "intern" / "startseite"):
            yield from sorted(verzeichnis.rglob("*.html"))

    def test_keine_mehrzeiligen_rautenkommentare(self):
        gefunden = []
        for pfad in self._vorlagen():
            for nummer, zeile in enumerate(pfad.read_text(encoding="utf-8").splitlines(), 1):
                # Jedes {# muss in derselben Zeile sein #} haben.
                if zeile.count("{#") > zeile.count("#}"):
                    gefunden.append(f"{pfad.name}:{nummer}: {zeile.strip()[:70]}")
        self.assertEqual(
            gefunden, [],
            "Mehrzeilige {# #}-Kommentare landen im HTML — "
            "{% comment %}…{% endcomment %} benutzen:\n" + "\n".join(gefunden),
        )

    def test_gerenderte_seite_traegt_keinen_kommentarrest(self):
        # Die Gegenprobe am Ergebnis: eine Vorlage mit dem Fehler faellt hier auf,
        # auch wenn sie den Test oben umgeht.
        kaputt = Template("{# Anfang\n   Ende #}<p>Inhalt</p>").render(Context({}))
        self.assertIn("{#", kaputt)   # so sieht der Fehler aus
        sauber = Template(
            "{% comment %}\n   Anfang\n   Ende\n{% endcomment %}<p>Inhalt</p>"
        ).render(Context({}))
        self.assertNotIn("{#", sauber)
        self.assertEqual(sauber.strip(), "<p>Inhalt</p>")


class SyntaxhilfeTest(SimpleTestCase):
    """Die Leiste im Artikel-Editor ist zum Anklicken da, nicht zum Abtippen.

    Jede Pille trägt ihr Muster selbst (``data-einfuegen``); ``wiki-einfuegen.js``
    setzt es an der Cursorposition ein. Wird eine Pille wieder zum ``<span>``
    oder verliert sie ihr Muster, fällt sie stumm auf Lesen zurück — das fiele
    sonst niemandem auf. Liest die Vorlage als Text, keine Datenbank.
    """

    # Gruppe 1 das Element, Gruppe 2 alle Attribute — auch die vor ``class``.
    PILLE = re.compile(r"<(\w+)([^>]*\bclass=\"ae-cheat\"[^>]*)>")

    @classmethod
    def _leiste(cls):
        wurzel = Path(__file__).resolve().parent.parent
        vorlage = wurzel / "intern" / "templates" / "artikel.html"
        return vorlage.read_text(encoding="utf-8")

    def _pillen(self):
        return self.PILLE.findall(self._leiste())

    def test_jede_pille_ist_ein_knopf(self):
        # Ohne type="button" schickt ein Klick im Editor-Formular den Artikel ab.
        for element, attribute in self._pillen():
            with self.subTest(pille=attribute[:40]):
                self.assertEqual(element, "button")
                self.assertIn('type="button"', attribute)

    def test_jede_pille_bringt_ihr_muster_mit(self):
        pillen = self._pillen()

        self.assertGreaterEqual(len(pillen), 12)
        for _element, attribute in pillen:
            with self.subTest(pille=attribute[:40]):
                self.assertIn("data-einfuegen=", attribute)

    def test_abstimmung_zeigt_die_pflichtform(self):
        # Das Ende ist Pflicht (ABSTIMMUNG_DIRECTIVE) — die Leiste darf keine
        # Form zeigen, die im Artikel nichts anzeigen würde.
        leiste = self._leiste()

        self.assertIn("{abstimmung:Titel:1:TT.MM.JJJJ:A;B}", leiste)
        self.assertIn('data-geruest="abstimmung"', leiste)

    def test_einfuegeskript_ist_eingebunden(self):
        self.assertIn("intern/js/wiki-einfuegen.js", self._leiste())


class ArtikelVorschauTest(SimpleTestCase):
    """Der Umschalter Bearbeiten/Vorschau im Artikel-Editor.

    Die Vorschau rendert über ``apply_replacements``; eine Abstimmung darin
    liest den Artikelnamen aus ``resolver_match.kwargs["name"]``. Hinge die
    Vorschau-URL nicht unter dem Artikel, fände sie ihre Stimmen nicht.
    """

    def test_url_traegt_den_artikelnamen(self):
        from django.urls import resolve, reverse

        treffer = resolve(reverse("article_preview", args=["Probe"]))

        self.assertEqual(treffer.url_name, "article_preview")
        self.assertEqual(treffer.kwargs["name"], "Probe")

    def test_umschalter_und_skript_sind_eingebunden(self):
        vorlage = (Path(__file__).resolve().parent / "templates" / "artikel.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("intern/js/wiki-vorschau.js", vorlage)
        self.assertIn("{% url 'article_preview' name=id %}", vorlage)
        # Ohne type="button" schickte ein Klick auf den Umschalter das Formular ab.
        for modus in ("edit", "vorschau"):
            with self.subTest(modus=modus):
                self.assertIn(f'type="button" class="ae-modus-seg" data-modus="{modus}"', vorlage)


class StatikQuellkartenTest(SimpleTestCase):
    """Eine ``sourceMappingURL`` ohne die zugehörige ``.map`` legt den Start lahm.

    ``ManifestStaticFilesStorage`` schreibt beim ``collectstatic`` jede Referenz
    einer statischen Datei auf ihren Hash-Namen um und wirft ``ValueError``,
    wenn das Ziel fehlt. In ``start.sh`` steht ``set -e``: das Kommando bricht
    ab, gunicorn kommt nie hoch. Genau so ist einmal ein mitgeliefertes
    Leaflet mit ``//# sourceMappingURL=leaflet.js.map`` in Betrieb gegangen.
    Entweder die ``.map`` mit ablegen oder die Zeile aus dem Vendor-Bündel
    entfernen.
    """

    QUELLKARTE = re.compile(r"sourceMappingURL=([^\s*'\"]+)")

    def test_jede_quellkarte_ist_vorhanden(self):
        wurzel = Path(__file__).resolve().parent / "static"
        gefunden = []
        for pfad in sorted(wurzel.rglob("*")):
            if pfad.suffix not in (".js", ".css") or not pfad.is_file():
                continue
            for treffer in self.QUELLKARTE.finditer(pfad.read_text(encoding="utf-8")):
                ziel = treffer.group(1)
                if ziel.startswith("data:"):
                    continue          # eingebettet, kein eigener Dateizugriff
                if not (pfad.parent / ziel).exists():
                    gefunden.append(f"{pfad.relative_to(wurzel)} → {ziel}")
        self.assertEqual(
            gefunden, [],
            "collectstatic bricht an diesen Referenzen ab — .map beilegen "
            "oder die Zeile entfernen:\n" + "\n".join(gefunden),
        )


class ChangelogTest(SimpleTestCase):
    """``CHANGELOG.md`` in genau der Form, auf die ``update.sh`` parst.

    Der Workflow baut zu einem Versions-Tag nur, wenn der getaggte Commit einen
    gefüllten Abschnitt für diese Version trägt (``update.sh``). Das Skript
    vergleicht dazu das zweite Feld der Überschriftzeile mit dem Tagnamen —
    ``## v1.0.1 — 2026-09-21`` ergibt ``v1.0.1``. Verrutscht das Format, fällt
    das sonst erst beim Freigeben auf, und dann steht der Auftritt schon im
    Kalender. „Unveröffentlicht" ist der Sammelabschnitt und darf leer sein;
    ihn zur Freigabe auf die Version umzubenennen ist der ganze Trick.
    """

    UEBERSCHRIFT = re.compile(r"^##\s+(\S+)(.*)$")
    VERSION = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z][0-9A-Za-z.-]*))?$")
    DATUM = re.compile(r"^\s+—\s+\d{4}-\d{2}-\d{2}\s*$")
    STICHPUNKT = re.compile(r"^\s*[-*]\s+\S")
    SAMMELT = "Unveröffentlicht"

    @classmethod
    def _pfad(cls):
        return Path(__file__).resolve().parent.parent / "CHANGELOG.md"

    def _abschnitte(self):
        """[(Kopf, Rest der Überschriftzeile, Zeilen), …] in Dateireihenfolge."""
        abschnitte = []
        for zeile in self._pfad().read_text(encoding="utf-8").splitlines():
            treffer = self.UEBERSCHRIFT.match(zeile)
            if treffer:
                abschnitte.append((treffer.group(1), treffer.group(2), []))
            elif abschnitte:
                abschnitte[-1][2].append(zeile)
        return abschnitte

    @classmethod
    def _ordnung(cls, version):
        """Sortierschlüssel; die Endfassung steht über ihren Vorabversionen.

        Die Vorabkennung wird blockweise verglichen, Ziffernfolgen als Zahl — wie
        ``sort -V`` es auf dem Server tut. Rein lexikografisch stünde ``rc10``
        unter ``rc2``, und der Hook, der nach demselben Schema sortiert, wäre
        anderer Meinung als dieser Test.
        """
        gross, klein, flick, vorab = cls.VERSION.match(version).groups()
        bloecke = tuple(
            (0, int(teil), "") if teil.isdigit() else (1, 0, teil)
            for teil in re.findall(r"\d+|\D+", vorab or "")
        )
        return (int(gross), int(klein), int(flick), 0 if vorab else 1, bloecke)

    def test_datei_mit_titel(self):
        pfad = self._pfad()
        self.assertTrue(pfad.exists(), f"{pfad.name} fehlt — der Hook weist jedes Tag ab.")
        erste = pfad.read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(erste, "# Änderungen")

    def test_jede_ueberschrift_ist_lesbar(self):
        falsch = []
        for kopf, rest, _ in self._abschnitte():
            if kopf == self.SAMMELT:
                continue
            if not self.VERSION.match(kopf):
                falsch.append(f"## {kopf}{rest} — kein v<x.y.z> und nicht „{self.SAMMELT}\"")
            elif not self.DATUM.match(rest):
                falsch.append(f"## {kopf}{rest} — es fehlt „ — JJJJ-MM-TT\"")
        self.assertEqual(
            falsch, [],
            "Der update-Hook findet diese Abschnitte nicht:\n" + "\n".join(falsch),
        )

    def test_jeder_versionsabschnitt_ist_gefuellt(self):
        leer = [
            kopf for kopf, _, zeilen in self._abschnitte()
            if kopf != self.SAMMELT
            and not any(self.STICHPUNKT.match(z) for z in zeilen)
        ]
        self.assertEqual(
            leer, [],
            "Ohne Stichpunkt weist der Hook das Tag ab: " + ", ".join(leer),
        )

    def test_versionen_stehen_absteigend(self):
        versionen = [
            kopf for kopf, _, _ in self._abschnitte()
            if kopf != self.SAMMELT and self.VERSION.match(kopf)
        ]
        self.assertEqual(len(versionen), len(set(versionen)),
                         f"Version doppelt aufgeführt: {versionen}")
        self.assertEqual(
            versionen, sorted(versionen, key=self._ordnung, reverse=True),
            f"Die jüngste Auslieferung steht oben: {versionen}",
        )

    def test_ordnung_setzt_endfassung_ueber_ihre_vorabversionen(self):
        # Die Gegenprobe zur Sortierung, ohne auf den Inhalt der Datei zu warten:
        # genau diese Reihenfolge erzeugt der Server mit
        # "sed 's/-/~/' | sort -V". rc10 gehört über rc2.
        erwartet = ["v1.1.0", "v1.0.1", "v1.0.0", "v1.0.0-rc10", "v1.0.0-rc2", "v1.0.0-rc1"]
        self.assertEqual(sorted(erwartet, key=self._ordnung, reverse=True), erwartet)

    def test_sammelabschnitt_hoechstens_einmal_und_oben(self):
        koepfe = [kopf for kopf, _, _ in self._abschnitte()]
        self.assertLessEqual(koepfe.count(self.SAMMELT), 1)
        if self.SAMMELT in koepfe:
            self.assertEqual(koepfe[0], self.SAMMELT,
                             f"„{self.SAMMELT}\" gehört nach oben: {koepfe}")


class AuslieferungenZerlegungTest(SimpleTestCase):
    """``zerlege`` — Text rein, Auslieferungen raus. Ohne Dateizugriff."""

    TEXT = (
        "# Änderungen\n"
        "\n"
        "Ein Abschnitt je Auslieferung. Was noch kein Tag hat, sammelt sich unter\n"
        "„Unveröffentlicht\"; zur Freigabe wird diese Überschrift umbenannt.\n"
        "\n"
        "## v1.0.0-rc4 — 2026-09-23\n"
        "\n"
        "- Erster Punkt über\n"
        "  drei Zeilen verteilt\n"
        "\n"
        "  Zweiter Absatz desselben Punktes.\n"
        "\n"
        "- Zweiter Punkt mit `code` und **fett**.\n"
    )

    def test_vorspann_ist_kein_releaseinhalt(self):
        (erste,) = zerlege(self.TEXT)
        self.assertEqual(erste.kennung, "v1.0.0-rc4")
        for punkt in erste.stichpunkte:
            for absatz in punkt.absaetze:
                self.assertNotIn("zur Freigabe", absatz)

    def test_datum_und_absaetze(self):
        (erste,) = zerlege(self.TEXT)
        self.assertEqual(erste.datum, date(2026, 9, 23))
        self.assertEqual(len(erste.stichpunkte), 2)
        self.assertEqual(
            erste.stichpunkte[0].absaetze,
            ("Erster Punkt über drei Zeilen verteilt",
             "Zweiter Absatz desselben Punktes."),
        )
        self.assertEqual(
            erste.stichpunkte[1].absaetze,
            ("Zweiter Punkt mit `code` und **fett**.",),
        )

    def test_fortsetzungszeilen_werden_ein_absatz(self):
        (erste,) = zerlege("## v1.0.0 — 2026-01-02\n\n- a\n  b\n  c\n")
        self.assertEqual(erste.stichpunkte[0].absaetze, ("a b c",))

    def test_leerzeile_im_punkt_bleibt_derselbe_punkt(self):
        # In der echten Datei kommt das vor (v1.0.0-rc3, der Punkt über die
        # Startseite): eine Leerzeile trennt den Absatz ab, nicht den Punkt.
        (erste,) = zerlege("## v1.0.0 — 2026-01-02\n\n- a\n\n  b\n")
        self.assertEqual(len(erste.stichpunkte), 1)
        self.assertEqual(erste.stichpunkte[0].absaetze, ("a", "b"))

    def test_abschnitt_ohne_datum_und_ohne_punkte(self):
        (erste,) = zerlege("## Unveröffentlicht\n")
        self.assertEqual(erste.kennung, "Unveröffentlicht")
        self.assertIsNone(erste.datum)
        self.assertEqual(erste.stichpunkte, ())

    def test_gruppen_werden_erkannt(self):
        (erste,) = zerlege(
            "## v1.0.0 — 2026-01-02\n"
            "\n"
            "### Hinzugefügt\n"
            "\n"
            "- Ein neuer Punkt.\n"
            "- Noch einer.\n"
            "\n"
            "### Behoben\n"
            "\n"
            "- Ein Fehler weniger.\n"
        )
        self.assertEqual([g.name for g in erste.gruppen], ["Hinzugefügt", "Behoben"])
        self.assertEqual(
            erste.gruppen[0].stichpunkte,
            (Stichpunkt(("Ein neuer Punkt.",)), Stichpunkt(("Noch einer.",))),
        )
        self.assertEqual(
            erste.gruppen[1].stichpunkte, (Stichpunkt(("Ein Fehler weniger.",)),)
        )
        # ``stichpunkte`` klopft die Gruppen flach — alles, was nur den Text
        # braucht, muss die Gruppierung nicht kennen.
        self.assertEqual(len(erste.stichpunkte), 3)

    def test_punkte_vor_der_ersten_gruppe_haben_keinen_namen(self):
        # Der update-Hook verlangt keine Gruppe; die Anzeige muss auch mit einer
        # Datei ohne ``###`` funktionieren.
        (erste,) = zerlege("## v1.0.0 — 2026-01-02\n\n- Ohne Gruppe.\n")
        self.assertEqual([g.name for g in erste.gruppen], [""])
        self.assertEqual(erste.gruppen[0].stichpunkte, (Stichpunkt(("Ohne Gruppe.",)),))

    def test_leere_gruppe_entfaellt(self):
        (erste,) = zerlege(
            "## v1.0.0 — 2026-01-02\n"
            "\n"
            "### Sicherheit\n"
            "\n"
            "### Behoben\n"
            "\n"
            "- Ein Fehler weniger.\n"
        )
        self.assertEqual([g.name for g in erste.gruppen], ["Behoben"])

    def test_tiefere_ueberschrift_ist_kein_inhalt(self):
        (erste,) = zerlege(
            "## v1.0.0 — 2026-01-02\n\n#### Zwischentitel\n\n- Ein Punkt.\n"
        )
        self.assertEqual(erste.stichpunkte, (Stichpunkt(("Ein Punkt.",)),))

    def test_unbrauchbarer_text_ergibt_leere_liste(self):
        self.assertEqual(zerlege(""), [])
        self.assertEqual(zerlege("# Änderungen\n\nnur Prosa\n"), [])
        self.assertEqual(zerlege("## \n"), [])


class AuslieferungenAuszeichnungTest(SimpleTestCase):
    """``auszeichnen`` — code, fett, kursiv; escape-first."""

    def test_code_fett_kursiv(self):
        self.assertEqual(auszeichnen("`Termin.extern`"), "<code>Termin.extern</code>")
        self.assertEqual(auszeichnen("**neben**"), "<strong>neben</strong>")
        self.assertEqual(auszeichnen("*im*"), "<em>im</em>")

    def test_escapen_steht_vor_allem_anderen(self):
        self.assertEqual(auszeichnen("a < b & c"), "a &lt; b &amp; c")
        self.assertNotIn("<script", auszeichnen("<script>alert(1)</script>"))

    def test_stern_im_codespan_wird_kein_em(self):
        # Das Code-Span wird zuerst herausgenommen; sonst würde aus dem
        # Sternchen des Codeinhalts ein <em>.
        self.assertEqual(auszeichnen("`--status-*`"), "<code>--status-*</code>")

    def test_realer_punkt_aus_der_datei(self):
        # v1.0.0-rc4, der Punkt über die (S)-Pille — code und fett gemischt.
        absatz = None
        for auslieferung in lies_auslieferungen():
            for punkt in auslieferung.stichpunkte:
                for text in punkt.absaetze:
                    if "`(S)`" in text:
                        absatz = text
        self.assertIsNotNone(absatz)
        markup = auszeichnen(absatz)
        self.assertIn("<code>(S)</code>", markup)
        self.assertIn("<strong>neben</strong>", markup)
        self.assertNotIn("**", markup)
        self.assertNotIn("`", markup)

    def test_absaetze_der_datei_haben_keine_umbrueche(self):
        for auslieferung in lies_auslieferungen():
            for punkt in auslieferung.stichpunkte:
                for absatz in punkt.absaetze:
                    self.assertNotIn("\n", absatz)
                    self.assertNotIn("<br", auszeichnen(absatz))

    def test_html_im_text_bleibt_sichtbar(self):
        # Die Datei beschreibt HTML mit Worten — ``<br>`` und ``<h1>`` stehen in
        # Backticks. Kein Zeichen davon darf als Tag in der Ausgabe landen: nach
        # dem Entfernen der drei Tags, die ``auszeichnen`` selbst setzt, bleibt
        # kein rohes ``<`` übrig, und was im Rohtext stand, steht dort escaped.
        erlaubt = ("<code>", "</code>", "<strong>", "</strong>", "<em>", "</em>")
        geprueft = 0
        for auslieferung in lies_auslieferungen():
            for punkt in auslieferung.stichpunkte:
                for absatz in punkt.absaetze:
                    markup = auszeichnen(absatz)
                    rest = markup
                    for tag in erlaubt:
                        rest = rest.replace(tag, "")
                    self.assertNotIn("<", rest, absatz)
                    if "<" in absatz:
                        self.assertIn("&lt;", markup, absatz)
                        geprueft += 1
        self.assertGreater(
            geprueft, 0, "kein Absatz mit HTML im Text — die Probe greift ins Leere"
        )


class AuslieferungenFilterTest(SimpleTestCase):
    """Der Filter ``auszeichnung`` setzt ``mark_safe``."""

    def test_auszeichnung_wird_nicht_escaped(self):
        gerendert = Template(
            "{% load auslieferungen_tags %}{{ t|auszeichnung }}"
        ).render(Context({"t": "`x`"}))
        self.assertEqual(gerendert, "<code>x</code>")

    def test_rohtext_bleibt_escaped(self):
        gerendert = Template(
            "{% load auslieferungen_tags %}{{ t|auszeichnung }}"
        ).render(Context({"t": "a < b"}))
        self.assertEqual(gerendert, "a &lt; b")


class AuslieferungenChargeTest(SimpleTestCase):
    """``charge`` und der Nachlade-Vertrag aus ``views/_pagination.py``."""

    @staticmethod
    def _abschnitte(anzahl):
        return [Auslieferung(f"v1.0.{i}", None, ()) for i in range(anzahl)]

    def test_erste_mittlere_letzte_charge(self):
        abschnitte = self._abschnitte(5)

        fenster, has_more, next_offset = charge(abschnitte, 0)
        self.assertEqual(fenster, abschnitte[0:2])
        self.assertTrue(has_more)
        self.assertEqual(next_offset, 2)

        fenster, has_more, next_offset = charge(abschnitte, 2)
        self.assertEqual(fenster, abschnitte[2:4])
        self.assertTrue(has_more)
        self.assertEqual(next_offset, 4)

        fenster, has_more, next_offset = charge(abschnitte, 4)
        self.assertEqual(fenster, abschnitte[4:5])
        self.assertFalse(has_more)
        self.assertEqual(next_offset, 6)

    def test_offset_jenseits_des_endes_ist_leer(self):
        self.assertEqual(charge(self._abschnitte(3), 99), ([], False, 101))
        self.assertEqual(charge([], 0), ([], False, ABSCHNITTE_PRO_CHARGE))

    def test_chargen_der_echten_datei_verlieren_nichts(self):
        alle = lies_auslieferungen()
        gesammelt = []
        offset = 0
        while True:
            fenster, has_more, offset = charge(alle, offset)
            gesammelt.extend(fenster)
            if not has_more:
                break
        self.assertEqual(gesammelt, alle)

    def test_parse_offset_und_ist_nachladen(self):
        from django.test import RequestFactory
        from intern.views._pagination import _MAX_OFFSET, ist_nachladen, parse_offset

        rf = RequestFactory()
        self.assertEqual(parse_offset(rf.get("/intern/changelog/")), 0)
        self.assertEqual(parse_offset(rf.get("/intern/changelog/", {"offset": "abc"})), 0)
        self.assertEqual(parse_offset(rf.get("/intern/changelog/", {"offset": "-5"})), 0)
        self.assertEqual(parse_offset(rf.get("/intern/changelog/", {"offset": "4"})), 4)
        self.assertEqual(
            parse_offset(rf.get("/intern/changelog/", {"offset": "10**30"})), 0
        )
        # Ein Wert über der 64-Bit-Grenze liefert der Datenbank keinen leeren
        # Ergebnissatz, sondern einen Fehler — deshalb die Deckelung.
        self.assertEqual(
            parse_offset(rf.get("/intern/changelog/", {"offset": "99" * 20})),
            _MAX_OFFSET,
        )
        self.assertEqual(parse_offset(rf.get("/intern/changelog/", {"offset": "1e9"})), 0)
        self.assertFalse(ist_nachladen(rf.get("/intern/changelog/")))
        self.assertTrue(ist_nachladen(
            rf.get("/intern/changelog/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        ))


class LaufendeKennungTest(SimpleTestCase):
    """``laufende_kennung`` — welche Auslieferung läuft."""

    KENNUNGEN = ["v1.0.0", "v1.0.0-rc4", "v0.9"]

    def test_exakter_treffer(self):
        self.assertEqual(
            laufende_kennung("CantorHub v1.0.0-rc4", self.KENNUNGEN), "v1.0.0-rc4"
        )

    def test_git_describe_nimmt_das_laengste_praefix(self):
        # Ohne die Längenregel träfe "v1.0.0-rc4-3-g7c8b717" auch auf "v1.0.0".
        self.assertEqual(
            laufende_kennung("CantorHub v1.0.0-rc4-3-g7c8b717", self.KENNUNGEN),
            "v1.0.0-rc4",
        )
        self.assertEqual(
            laufende_kennung("CantorHub v1.0.0-rc4-dirty", self.KENNUNGEN),
            "v1.0.0-rc4",
        )

    def test_ohne_treffer_keine_marke(self):
        # Die Entwicklung kennt kein git describe — dann lieber keine Marke
        # als eine falsche.
        self.assertIsNone(laufende_kennung("CantorHub v0.1234", self.KENNUNGEN))
        self.assertIsNone(laufende_kennung("CantorHub", self.KENNUNGEN))
        self.assertIsNone(laufende_kennung("CantorHub v9.9.9", self.KENNUNGEN))

    def test_gegenprobe_an_der_echten_datei(self):
        kennungen = [a.kennung for a in lies_auslieferungen()]
        for kennung in kennungen:
            if kennung == ChangelogTest.SAMMELT:
                continue
            self.assertEqual(laufende_kennung("CantorHub " + kennung, kennungen), kennung)


class AuslieferungenDateiTest(SimpleTestCase):
    """Die Zerlegung der echten Datei — im Gleichlauf mit ``ChangelogTest``."""

    def test_jede_auslieferung_ist_lesbar(self):
        abschnitte = lies_auslieferungen()
        self.assertGreater(len(abschnitte), 0)
        for auslieferung in abschnitte:
            if auslieferung.kennung == ChangelogTest.SAMMELT:
                continue
            self.assertRegex(auslieferung.kennung, ChangelogTest.VERSION.pattern)
            self.assertIsNotNone(auslieferung.datum, auslieferung.kennung)

    def test_jeder_eintrag_hat_hoechstens_drei_saetze(self):
        # Die Schreibregel der Datei (siehe Vorspann): ein Eintrag sagt, *was*
        # sich ändert. Wie es dazu kam, steht im Commit — dort ist Platz, hier
        # nicht.
        zu_lang = []
        for auslieferung in lies_auslieferungen():
            for gruppe in auslieferung.gruppen:
                for punkt in gruppe.stichpunkte:
                    for absatz in punkt.absaetze:
                        saetze = [
                            satz for satz in re.split(r"(?<=[.!?])\s+", absatz.strip())
                            if satz
                        ]
                        if len(saetze) > 3:
                            zu_lang.append(
                                f"{auslieferung.kennung}: {len(saetze)} Sätze — "
                                f"{absatz[:70]}…"
                            )
        self.assertEqual(zu_lang, [], "Einträge zu lang:\n" + "\n".join(zu_lang))

    def test_eintraege_enthalten_keine_markdown_links(self):
        # Der Zerleger kennt keine Links: ``[x](y)`` stünde als roher Klammertext
        # auf der Seite. Der Vorspann darf sie tragen (er wird nicht angezeigt),
        # die Einträge nicht — und Tabellen, Zäune und Zitate ebenso wenig.
        gefunden = []
        for auslieferung in lies_auslieferungen():
            for gruppe in auslieferung.gruppen:
                for punkt in gruppe.stichpunkte:
                    for absatz in punkt.absaetze:
                        if "](" in absatz:
                            gefunden.append(
                                f"{auslieferung.kennung}: {absatz[:70]}…"
                            )
        self.assertEqual(
            gefunden, [],
            "Der Zerleger rendert keine Links — sie stünden als Rohtext:\n"
            + "\n".join(gefunden),
        )

    def test_zerlegung_stimmt_mit_dem_waechter_ueberein(self):
        # Die Datei ist zweimal beschrieben: hier für die Anzeige, in
        # ChangelogTest für den update-Hook. Laufen die Muster auseinander,
        # zerfällt die Anzeige still — deshalb die Gegenprobe mit den Mustern
        # des Wächters, statt sie hier ein zweites Mal zu tippen.
        aus_parser = [
            (a.kennung, a.datum.isoformat() if a.datum else None,
             sum(1 for p in a.stichpunkte))
            for a in lies_auslieferungen()
        ]
        aus_waechter = []
        for kopf, rest, zeilen in ChangelogTest()._abschnitte():
            aus_waechter.append((
                kopf,
                rest.strip().removeprefix("—").strip() or None,
                sum(1 for z in zeilen if ChangelogTest.STICHPUNKT.match(z)),
            ))
        self.assertEqual(aus_parser, aus_waechter)


class AuslieferungenFragmentTest(SimpleTestCase):
    """Das Fragment — es trägt den Erstaufruf und die nachgeladene Charge."""

    ABSCHNITTE = [
        Auslieferung("v1.0.0", date(2026, 1, 2), (
            Gruppe("Hinzugefügt", (Stichpunkt(("Ein Punkt.",)),)),
            Gruppe("Behoben", (Stichpunkt(("Ein Fehler weniger.",)),)),
        )),
        Auslieferung("Unveröffentlicht", None, (
            Gruppe("", (Stichpunkt(("Noch nichts.",)),)),
        )),
    ]

    def _rendern(self, laufende):
        return render_to_string(
            "_auslieferungen_abschnitte.html",
            {"abschnitte": self.ABSCHNITTE, "laufende": laufende},
        )

    def test_laufende_ist_markiert(self):
        markup = self._rendern("v1.0.0")
        self.assertIn("auslieferung--laufend", markup)
        self.assertIn("Deine Version", markup)
        self.assertIn(
            '<time class="auslieferung-datum" datetime="2026-01-02">02.01.2026</time>',
            markup,
        )
        self.assertIn("<p>Ein Punkt.</p>", markup)

    def test_ohne_treffer_keine_marke(self):
        markup = self._rendern(None)
        self.assertNotIn("auslieferung--laufend", markup)
        self.assertNotIn("Deine Version", markup)

    def test_gruppenueberschrift_nur_mit_namen(self):
        markup = self._rendern("v1.0.0")
        self.assertIn('<h3 class="auslieferung-gruppe">Hinzugefügt</h3>', markup)
        self.assertIn('<h3 class="auslieferung-gruppe">Behoben</h3>', markup)
        # Die namenlose Gruppe (Punkte ohne ``###`` in der Datei) bekommt keine
        # Überschrift, ihre Punkte aber stehen da.
        self.assertEqual(markup.count('<h3 class="auslieferung-gruppe">'), 2)
        self.assertIn("<p>Noch nichts.</p>", markup)

    def test_abschnitt_ohne_datum_hat_keine_zeitzeile(self):
        markup = render_to_string(
            "_auslieferungen_abschnitte.html",
            {"abschnitte": [self.ABSCHNITTE[1]], "laufende": None},
        )
        self.assertNotIn("<time", markup)
        self.assertIn("Unveröffentlicht", markup)


class AuslieferungenSchaleTest(SimpleTestCase):
    """Die Seitenschale hält den Nachlade-Vertrag ein."""

    def test_schale_bindet_dasselbe_fragment_ein_und_haelt_die_sentinel_id(self):
        # Erstaufruf und Nachladen müssen dasselbe Markup erzeugen; die id des
        # Sentinels steht im Markup und im Skript und muss beide Male gleich
        # lauten.
        quelle = (
            Path(__file__).resolve().parent / "templates" / "auslieferungen.html"
        ).read_text(encoding="utf-8")
        self.assertIn('{% include "_auslieferungen_abschnitte.html"', quelle)
        self.assertGreaterEqual(quelle.count("auslieferungen-sentinel"), 2)
        self.assertIn("X-Requested-With", quelle)


class FarbTokenTest(SimpleTestCase):
    """Jede Farbe ist ein Custom Property mit einem ``[data-theme="dark"]``-Wert.

    Die Regel steht in ``CLAUDE.md``, war aber bisher von keinem Test gedeckt —
    ein im Dark-Block vergessenes Token fällt sonst erst dem Mitglied auf, das
    nachts ins Portal schaut, und auch dann nur als „sieht komisch aus".
    Geprüft werden die Stimmpalette, die Kategorienpalette, die Ampel-Familie
    und die abgeleiteten Marken-Töne; der Aufbau trägt jede weitere Familie, die
    dazukommt. Der Fall, an dem er sich bewährt hat: ``--brand-dark`` stand
    monatelang ohne Dark-Wert da und war als Schrift auf der dunklen Karte 2,7:1
    — siehe ``--brand-text``.

    Absichtlich *nicht* geprüft: dass der Dark-Wert ein anderer ist. ``--brand``
    ist in beiden Themes derselbe und ``--aufst-eventuell`` ebenfalls — beides
    ist so gewollt.
    """

    PRAEFIXE = ("--brand-", "--stimme-", "--kat-", "--status-")
    DEKLARATION = re.compile(r"^\s*(--[a-z0-9-]+)\s*:", re.MULTILINE)

    #: Absichtlich themenunabhängig. Der Ampel-Vollton ist die kräftige Füllung
    #: für Hover- und Aktiv-Zustände und trägt dort weißen Text; er bleibt in
    #: beiden Themes derselbe, während bg/text/border im Dark-Block weicher
    #: werden. Steht so in docs/frontend.md, Abschnitt „Status (Ampel) colours".
    #: ``--brand-dark/light/ring`` sind ebenfalls themenunabhängig: sie mischen
    #: allein ``--brand`` und kennen den Untergrund nicht. Nur ``--brand-text``
    #: führt einen eigenen Dark-Wert, weil die Markenfarbe als *Schrift* auf der
    #: dunklen Karte einen anderen Ton braucht als als *Fläche*.
    #: Wer hier etwas einträgt, nimmt es aus der Prüfung — also nur mit Grund.
    OHNE_DARK_WERT = {
        "--status-success-solid",
        "--status-warning-solid",
        "--status-danger-solid",
        "--brand-dark",
        "--brand-light",
        "--brand-ring",
    }

    def _bloecke(self):
        """Die Token-Namen aus ``:root`` und aus dem Dark-Block."""
        css = (Path(__file__).resolve().parent
               / "static" / "intern" / "css" / "intern.css").read_text(encoding="utf-8")
        # Der Dark-Block ist der erste [data-theme="dark"] { … } im Dokument;
        # danach folgen nur noch einzelne [data-theme="dark"] .selektor-Regeln.
        start = css.index('[data-theme="dark"] {')
        hell = css[:start]
        hell = hell[hell.index(":root {"):hell.index("\n}")]
        dunkel = css[start:css.index("\n}", start)]
        return (
            {m.group(1) for m in self.DEKLARATION.finditer(hell)},
            {m.group(1) for m in self.DEKLARATION.finditer(dunkel)},
        )

    def test_jedes_farbtoken_hat_einen_dark_wert(self):
        hell, dunkel = self._bloecke()
        relevant = {t for t in hell
                    if t.startswith(self.PRAEFIXE) and t not in self.OHNE_DARK_WERT}
        self.assertTrue(relevant, ":root enthält keine Farbtokens — Parser kaputt?")
        self.assertEqual(
            sorted(relevant - dunkel), [],
            'Diese Tokens fehlen im [data-theme="dark"]-Block',
        )

    def test_stimmpalette_ist_vollstaendig(self):
        """Vier Stimmlagen, je Vollton und abgeleitete Textfarbe.

        Chorleiter und Musiker stehen bewusst nicht dabei: sie sind Rollen,
        keine Stimmlage, und tragen den neutralen ``--t4``.
        """
        erwartet = {f"--stimme-{lage}{art}"
                    for lage in "satb" for art in ("", "-text")}
        for name, block in zip((":root", '[data-theme="dark"]'), self._bloecke()):
            self.assertEqual(erwartet - block, set(), f"unvollständig in {name}")
            self.assertNotIn(
                "--stimme-c", block,
                "Chorleiter ist eine Rolle, keine Stimmlage — neutral lassen",
            )


class DatenbankUrlTest(SimpleTestCase):
    """Die eine Datenbank-Variable — Parser aus config/datenbank.py.

    Ersetzt DB_HOST/DB_NAME/DB_USER/DB_PASSWORD/DB_PORT. Ein Fehler hier trifft
    jeden Start, deshalb sind auch die Fehlerfälle geprüft: ein unvollständiger
    Wert soll laut abbrechen und nicht stillschweigend auf SQLite ausweichen.
    """

    def test_mysql_vollstaendig(self):
        from config.datenbank import datenbank_aus_url
        cfg = datenbank_aus_url("mysql://chor:geheim@db:3307/cantorhub", "/data")
        self.assertEqual(cfg["ENGINE"], "django.db.backends.mysql")
        self.assertEqual(cfg["NAME"], "cantorhub")
        self.assertEqual(cfg["USER"], "chor")
        self.assertEqual(cfg["PASSWORD"], "geheim")
        self.assertEqual(cfg["HOST"], "db")
        self.assertEqual(cfg["PORT"], "3307")
        self.assertEqual(cfg["OPTIONS"]["charset"], "utf8mb4")

    def test_mysql_ohne_port_nimmt_3306(self):
        from config.datenbank import datenbank_aus_url
        self.assertEqual(
            datenbank_aus_url("mysql://u:p@db/ch", "/data")["PORT"], "3306"
        )

    def test_sonderzeichen_im_passwort(self):
        # Ein @ im Passwort muss als %40 kodiert sein, sonst zerfiele die URL an
        # der falschen Stelle — hier zählt, dass wir es wieder auspacken.
        from config.datenbank import datenbank_aus_url
        cfg = datenbank_aus_url("mysql://u:p%40ss%2Fwort@db:3306/ch", "/data")
        self.assertEqual(cfg["PASSWORD"], "p@ss/wort")

    def test_sqlite_absoluter_pfad(self):
        # Drei und vier Schrägstriche bedeuten dasselbe; der Unterschied ist eine
        # Fussangel der URL-Form, keine Absicht des Betreibers.
        from config.datenbank import datenbank_aus_url
        for url in ("sqlite:////data/db.sqlite3", "sqlite:///data/db.sqlite3"):
            cfg = datenbank_aus_url(url, "/anderswo")
            self.assertEqual(cfg["ENGINE"], "django.db.backends.sqlite3")
            self.assertEqual(cfg["NAME"], "/data/db.sqlite3", msg=url)

    def test_leere_url_nimmt_datenverzeichnis(self):
        from config.datenbank import datenbank_aus_url
        cfg = datenbank_aus_url("", "/data")
        self.assertEqual(cfg["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(cfg["NAME"], "/data/db.sqlite3")
        self.assertEqual(cfg["OPTIONS"]["timeout"], 20)
        self.assertEqual(cfg["OPTIONS"]["transaction_mode"], "IMMEDIATE")

    def test_unbekanntes_schema_bricht_ab(self):
        from config.datenbank import KonfigurationsFehler, datenbank_aus_url
        with self.assertRaises(KonfigurationsFehler):
            datenbank_aus_url("postgres://u:p@db/ch", "/data")

    def test_unvollstaendige_angaben_brechen_ab(self):
        from config.datenbank import KonfigurationsFehler, datenbank_aus_url
        for url in ("mysql://u:p@db/", "mysql:///ch", "sqlite://", "sqlite://host/x"):
            with self.assertRaises(KonfigurationsFehler, msg=url):
                datenbank_aus_url(url, "/data")


class HostsAusUrlTest(SimpleTestCase):
    """ALLOWED_HOSTS/CSRF_TRUSTED_ORIGINS aus VEREINS_URL."""

    def test_hostname_und_origin(self):
        from config.datenbank import hosts_aus_url
        hosts, origins = hosts_aus_url("https://chor.example.de")
        self.assertIn("chor.example.de", hosts)
        self.assertIn("https://chor.example.de", origins)

    def test_lokale_eintraege_bleiben_immer(self):
        # nginx spricht gunicorn über 127.0.0.1 an — die auth_request-Unteranfrage
        # für jede Datei unter /media/ trägt diesen Host.
        from config.datenbank import hosts_aus_url
        hosts, _ = hosts_aus_url("https://chor.example.de")
        self.assertIn("localhost", hosts)
        self.assertIn("127.0.0.1", hosts)

    def test_port_bleibt_im_origin(self):
        from config.datenbank import hosts_aus_url
        hosts, origins = hosts_aus_url("http://narsil:8000")
        self.assertIn("narsil", hosts)          # ALLOWED_HOSTS ohne Port
        self.assertIn("http://narsil:8000", origins)   # Origin mit Port

    def test_leere_url_nur_lokal(self):
        from config.datenbank import hosts_aus_url
        hosts, origins = hosts_aus_url("")
        self.assertEqual(hosts, ["localhost", "127.0.0.1"])
        self.assertEqual(len(origins), 2)

    def test_unbrauchbare_url_bricht_nicht(self):
        # Ein verstellter Wert darf den Start nicht verhindern; apps.ready()
        # protokolliert stattdessen eine Warnung.
        from config.datenbank import hosts_aus_url
        for url in ("kein-schema.de", "ftp://x.de", "   "):
            hosts, _ = hosts_aus_url(url)
            self.assertEqual(hosts, ["localhost", "127.0.0.1"], msg=url)


class GeheimnisTest(SimpleTestCase):
    """Die Schlüsseldatei im Datenverzeichnis (config/geheimnis.py)."""

    def test_erzeugt_und_liest_denselben_wert(self):
        import tempfile
        from config.geheimnis import schluessel_lesen_oder_erzeugen
        with tempfile.TemporaryDirectory() as verzeichnis:
            pfad = Path(verzeichnis) / "secret_key"
            erster = schluessel_lesen_oder_erzeugen(pfad)
            self.assertTrue(erster)
            # Zweiter Start: derselbe Schlüssel, sonst wären alle Sitzungen weg.
            self.assertEqual(schluessel_lesen_oder_erzeugen(pfad), erster)

    def test_rechte_sind_0600(self):
        import stat
        import tempfile
        from config.geheimnis import schluessel_lesen_oder_erzeugen
        with tempfile.TemporaryDirectory() as verzeichnis:
            pfad = Path(verzeichnis) / "secret_key"
            schluessel_lesen_oder_erzeugen(pfad)
            modus = stat.S_IMODE(pfad.stat().st_mode)
            self.assertEqual(modus, 0o600, msg=f"Rechte {modus:o}")

    def test_unbeschreibbares_verzeichnis_meldet_sich(self):
        # Fehlendes oder nur lesbares Datenverzeichnis: lieber ein lesbarer
        # Fehler als ein Portal, das bei jedem Neustart alle Sitzungen verwirft.
        from config.geheimnis import GeheimnisFehler, schluessel_lesen_oder_erzeugen
        with self.assertRaises(GeheimnisFehler):
            schluessel_lesen_oder_erzeugen("/gibt/es/nicht/secret_key")


class VerwaisteBlobsTest(SimpleTestCase):
    """Die Regel hinter ``cleanup_verwaiste_blobs`` (intern/blob_aufraeumen.py).

    Sie entscheidet über unwiederbringliches Löschen und muss deshalb in beide
    Richtungen festgenagelt sein: kein lebender Blob darf fallen, und keine
    Leiche darf durchkommen.
    """

    BLOB = "filer_public/de/ad/deadf6ff-8436-467d-8e98-04314a39226b/126.jpg"
    THUMB = (
        "filer_public_thumbnails/filer_public/de/ad/"
        "deadf6ff-8436-467d-8e98-04314a39226b/126.jpg__32x32_q85_crop.jpg"
    )
    ALT = "filer_public/11/22/11223344-0000-0000-0000-000000000000/126.jpg"

    def test_bekannter_blob_bleibt(self):
        self.assertEqual(verwaiste_pfade([self.BLOB], {self.BLOB}), [])

    def test_unbekannter_blob_faellt(self):
        self.assertEqual(verwaiste_pfade([self.BLOB], set()), [self.BLOB])

    def test_thumbnail_faellt_mit_seiner_quelle(self):
        # Quelle bekannt: das Thumbnail bleibt. Quelle weg: es geht mit.
        self.assertEqual(verwaiste_pfade([self.THUMB], {self.BLOB}), [])
        self.assertEqual(verwaiste_pfade([self.THUMB], set()), [self.THUMB])

    def test_thumbnail_ueberlebt_andere_datei_im_quellverzeichnis(self):
        # Verglichen wird das Verzeichnis, nicht der zurueckgerechnete Name:
        # ein Originalname darf selbst „__" tragen.
        heikel = (
            "filer_public_thumbnails/filer_public/de/ad/"
            "deadf6ff-8436-467d-8e98-04314a39226b/a__b.jpg__32x32_q85.jpg"
        )
        self.assertEqual(verwaiste_pfade([heikel], {self.BLOB}), [])

    def test_versionsvorschau_neben_ihrem_blob_bleibt(self):
        # Die 96x96-Vorschauen der Dateiversionen landen mangels
        # Storage-Konfiguration innerhalb von filer_public/ statt unter der
        # Thumbnail-base_dir (docs/files.md). Sie stehen in keiner Spalte:
        # pfadweise verglichen waeren sie Waisen und fielen bei jedem Lauf weg.
        vorschau = (
            "filer_public/de/ad/deadf6ff-8436-467d-8e98-04314a39226b/"
            "126.jpg__96x96_q85_crop.jpg"
        )
        self.assertEqual(verwaiste_pfade([vorschau], {self.BLOB}), [])
        # Ist der Blob weg, geht die Vorschau mit.
        self.assertEqual(verwaiste_pfade([vorschau], set()), [vorschau])

    def test_dateiversion_haelt_ihren_blob(self):
        # Der Fall, an dem filer_check --delete-orphans scheitert: eine alte
        # Fassung hat keine File-Zeile, ihr Pfad steht nur in DateiVersion.
        self.assertEqual(
            verwaiste_pfade([self.BLOB, self.ALT], {self.BLOB, self.ALT}), []
        )
        self.assertEqual(
            verwaiste_pfade([self.BLOB, self.ALT], {self.BLOB}), [self.ALT]
        )

    def test_fremde_pfade_bleiben_unangetastet(self):
        # Was nicht unter den filer-Praefixen liegt, geht die Regel nichts an.
        fremd = ["tiles/12/34/56.png", "secret_key", "filer_publicX/a.jpg"]
        self.assertEqual(verwaiste_pfade(fremd, set()), [])

    def test_thumbnailpraefix_ist_kein_blobpraefix(self):
        # Ohne den Trenner im Vergleich waere „filer_public_thumbnails/…" ein
        # Treffer auf „filer_public" — jedes Thumbnail gaelte dann als Blob,
        # den die Datenbank nicht kennt.
        quelle = "filer_public/de/ad/deadf6ff-8436-467d-8e98-04314a39226b"
        self.assertEqual(zugeordnetes_verzeichnis(self.THUMB), quelle)
        # Der Blob selbst landet im Blob-Zweig und zeigt auf dasselbe
        # Verzeichnis — nicht auf eines unterhalb des Thumbnail-Praefixes.
        self.assertEqual(zugeordnetes_verzeichnis(self.BLOB), quelle)
        self.assertIsNone(zugeordnetes_verzeichnis("tiles/12/34/56.png"))


class MitgliedschaftTest(SimpleTestCase):
    """Die zwei Achsen aus ``intern/mitgliedschaft.py``.

    ``is_active`` traegt den Portalzugang, das Tag „Mitglied" die
    Vereinsmitgliedschaft — vorher steckte beides in einem Feld. Die Entscheidungen
    stehen deshalb als reine Funktionen da, und dieser Test haelt sie fest: vor allem
    den Fall, der den Anlass gab (ein Konto **ohne** Tag ist auch ohne Eintrittsdatum
    keine Neuaufnahme, sonst bekaeme das Chorleiter-Konto beim Wiedereinschalten
    Willkommensmail und ein Eintrittsdatum).
    """

    EIN_DATUM = datetime(2026, 6, 17, 20, 0)

    def test_erstaufnahme_nur_mit_tag_und_ohne_datum(self):
        self.assertTrue(ist_erstaufnahme(None, True))
        # Kein Tag: Wiedereinschalten ist eine Reaktivierung, keine Aufnahme.
        self.assertFalse(ist_erstaufnahme(None, False))
        # Datum vorhanden: die Person war schon einmal aufgenommen.
        self.assertFalse(ist_erstaufnahme(self.EIN_DATUM, True))
        self.assertFalse(ist_erstaufnahme(self.EIN_DATUM, False))

    def test_erstaufnahme_gibt_wahrheitswert(self):
        # ``ist_mitglied`` kommt aus einem QuerySet-``exists()``; der Rueckgabewert
        # muss trotzdem ein echtes bool sein, weil er die Mailauswahl steuert.
        self.assertIs(ist_erstaufnahme(None, 1), True)
        self.assertIs(ist_erstaufnahme(None, 0), False)

    def test_aktion_folgt_dem_tag(self):
        # Mit Tag gibt es nur „beenden" — auch beim Foerdermitglied ohne Zugang.
        self.assertEqual(mitgliedschafts_aktion(True, None), "beenden")
        self.assertEqual(mitgliedschafts_aktion(True, self.EIN_DATUM), "beenden")
        # Ohne Tag verraet das Eintrittsdatum das ehemalige Mitglied.
        self.assertEqual(mitgliedschafts_aktion(False, self.EIN_DATUM), "wieder_aufnehmen")
        self.assertEqual(mitgliedschafts_aktion(False, None), "aufnehmen")

    def test_bestaetigungslink_folgt_dem_konto(self):
        # Aktiv heisst bestaetigt: der Link ist verbraucht, auch ohne Tag.
        self.assertEqual(bestaetigungslink_zustand(True, True), "erledigt")
        self.assertEqual(bestaetigungslink_zustand(True, False), "erledigt")
        # Gesperrt mit Tag: die Bestaetigung steht aus.
        self.assertEqual(bestaetigungslink_zustand(False, True), "offen")
        # Gesperrt ohne Tag (Mitgliedschaft beendet): ein laufender Link
        # darf das Konto nicht wieder oeffnen.
        self.assertEqual(bestaetigungslink_zustand(False, False), "ungueltig")

    def test_antragslink_nur_ohne_zugang_und_ohne_tag(self):
        # Das Konto, fuer das „Mitglied bearbeiten" die Aufnahme anbietet.
        self.assertTrue(antragslink_gilt(False, False))
        # Schon Mitglied — auch gesperrt (Bestaetigung offen, Foerdermitglied).
        self.assertFalse(antragslink_gilt(False, True))
        self.assertFalse(antragslink_gilt(True, True))
        # Zugang ohne Tag (Chorleitung, Gast): nichts zu beantragen.
        self.assertFalse(antragslink_gilt(True, False))

    def test_antrag_bestand_ohne_benutzername_und_passwort(self):
        from unittest import mock
        from intern.forms import MitgliedAntragBestandForm, MitgliedBeitrittForm
        with mock.patch("intern.app_settings.get_document_url", return_value="/x"):
            bestand = MitgliedAntragBestandForm()
            neu = MitgliedBeitrittForm()
        for feld in ("username", "password1", "password2"):
            self.assertNotIn(feld, bestand.fields)
        # Sonst dieselben Felder wie der Neuantrag, Einwilligungen eingeschlossen.
        self.assertEqual(
            set(bestand.fields), set(neu.fields) - {"username", "password1", "password2"}
        )

    def test_datenschutzbestaetigung_nur_fuer_zugang_ohne_mitgliedschaft(self):
        # Chorleitung, Gast: einmal bestaetigen, dann nicht mehr.
        self.assertTrue(braucht_datenschutzbestaetigung(True, False, False))
        self.assertFalse(braucht_datenschutzbestaetigung(True, False, True))
        # Mitglieder bestaetigen ueber Antrag und Datenbestaetigung, nie hier.
        self.assertFalse(braucht_datenschutzbestaetigung(True, True, False))
        # Ohne Zugang gibt es keine Seite, auf die man geleitet wuerde.
        self.assertFalse(braucht_datenschutzbestaetigung(False, False, False))

    def test_foerdermitglied_bekommt_keinen_zugang(self):
        self.assertTrue(aufnahme_setzt_aktiv(False))
        self.assertFalse(aufnahme_setzt_aktiv(True))

    def test_gruppennamen_stehen_in_der_einrichtung(self):
        """Die Gruppen, die der Code per ``get()`` erwartet, stehen in ``einrichtung.GRUPPEN``.

        Sonst legt die Ersteinrichtung sie auf einer neuen Installation nicht an und
        die Aufnahme liefe ins Leere. „kein Bild" und „DSGVO" legt ``_setze_tag()``
        per ``get_or_create`` beim ersten Gebrauch selbst an; „Gründer" ist nur noch
        ein Etikett des Altimports.
        """
        from intern.einrichtung import GRUPPE_VORSTAND, GRUPPEN

        for name in (GRUPPE_MITGLIED, GRUPPE_FOERDERMITGLIED, GRUPPE_VORSTAND):
            self.assertIn(name, GRUPPEN)
        for name in (GRUPPE_GRUENDER, GRUPPE_KEIN_BILD, GRUPPE_DATENSCHUTZ_BESTAETIGT):
            self.assertNotIn(name, GRUPPEN)

    def test_kein_bild_ohne_foto_einwilligung(self):
        """Ohne Foto-Haekchen gibt es das Tag „kein Bild", mit Haekchen nicht."""
        self.assertTrue(kein_bild_aus_einwilligung(False))
        self.assertFalse(kein_bild_aus_einwilligung(True))


class LoginSperrhinweisTest(SimpleTestCase):
    """Ein gesperrtes Konto bekommt beim Login den Sperrhinweis statt „Passwort falsch".

    Die Datenbestätigung sperrt das Konto bis zum Absenden des Formulars
    (``send_bestaetigung_mail``); ohne den Hinweis hielte das Mitglied sein
    Passwort für falsch. Den Hinweis gibt es nur bei richtigem Passwort.
    """

    def _formular(self, konto, password="geheim"):
        from intern.forms import CantorAuthenticationForm
        from intern.models import User

        modell = mock.Mock(DoesNotExist=User.DoesNotExist)
        if konto is None:
            modell._default_manager.get_by_natural_key.side_effect = User.DoesNotExist
        else:
            modell._default_manager.get_by_natural_key.return_value = konto
        form = CantorAuthenticationForm(
            data={"username": "anna", "password": password}
        )
        with mock.patch("django.contrib.auth.forms.authenticate", return_value=None), \
                mock.patch("intern.forms.User", modell):
            self.assertFalse(form.is_valid())
        return form

    def _konto(self, aktiv):
        return SimpleNamespace(
            is_active=aktiv, check_password=lambda pw: pw == "geheim"
        )

    def test_gesperrt_mit_richtigem_passwort(self):
        self.assertTrue(self._formular(self._konto(aktiv=False)).zugang_gesperrt)

    def test_gesperrt_mit_falschem_passwort(self):
        form = self._formular(self._konto(aktiv=False), password="falsch")
        self.assertFalse(form.zugang_gesperrt)

    def test_aktiv_mit_falschem_passwort(self):
        form = self._formular(self._konto(aktiv=True), password="falsch")
        self.assertFalse(form.zugang_gesperrt)

    def test_unbekannter_name(self):
        self.assertFalse(self._formular(None).zugang_gesperrt)


# ---------------------------------------------------------------------------
# Telefonnummern
# ---------------------------------------------------------------------------


class TelefonnummerTest(SimpleTestCase):
    """Normalisierung der Telefonfelder (intern/telefon.py) — DB-frei."""

    def test_gruppierung_deutschland(self):
        from intern.telefon import normalisiere
        self.assertEqual(normalisiere("069 1234567"), "+49 69 1234567")
        self.assertEqual(normalisiere("030 123456"), "+49 30 123456")
        self.assertEqual(normalisiere("0170-1234567"), "+49 170 1234567")
        self.assertEqual(normalisiere("01573 1234567"), "+49 1573 1234567")
        self.assertEqual(normalisiere("0211 123456"), "+49 211 123456")
        self.assertEqual(normalisiere("0202 123456"), "+49 202 123456")
        self.assertEqual(normalisiere("06151 123456"), "+49 6151 123456")
        self.assertEqual(normalisiere("0800 1234567"), "+49 800 1234567")

    def test_eingabeformen_ergeben_dasselbe(self):
        from intern.telefon import normalisiere
        for roh in (
            "0170 1234567", "0170-1234567", "0170/12 34 567", "(0170) 1234567",
            "0049 170 1234567", "+49 170 1234567", "+49 (0)170 1234567",
            "170 1234567",      # vergessene Verkehrsausscheidungsziffer
        ):
            self.assertEqual(normalisiere(roh), "+49 170 1234567", msg=roh)

    def test_idempotent(self):
        from intern.telefon import normalisiere
        for roh in ("069 1234567", "01573 1234567", "06151 123456", "+41 44 123 45 67"):
            einmal = normalisiere(roh)
            self.assertEqual(normalisiere(einmal), einmal, msg=roh)

    def test_fremdes_land_ohne_gruppierung(self):
        # Ohne Nummernplan wird nicht geraten: Ziffern kompakt, nur die Trenner fallen.
        from intern.telefon import normalisiere
        self.assertEqual(normalisiere("+41 44 123 45 67"), "+41441234567")
        self.assertEqual(normalisiere("+43 1 234567"), "+431234567")
        self.assertEqual(normalisiere("+1 212 555 0123"), "+12125550123")

    def test_konfigurierte_landesvorwahl(self):
        from intern.telefon import normalisiere
        self.assertEqual(normalisiere("0170 1234567", "+43"), "+431701234567")
        self.assertEqual(normalisiere("044 1234567", "+41"), "+41441234567")
        # Ein geleerter oder unsinniger Schlüssel darf kein Formular lahmlegen.
        self.assertEqual(normalisiere("0221 1234567", ""), "+49 221 1234567")
        self.assertEqual(normalisiere("0221 1234567", "unsinn"), "+49 221 1234567")

    def test_leer_bleibt_leer(self):
        from intern.telefon import normalisiere
        self.assertEqual(normalisiere(""), "")
        self.assertEqual(normalisiere("   "), "")
        self.assertEqual(normalisiere(None), "")

    def test_unlesbares_ist_none(self):
        from intern.telefon import normalisiere
        for roh in (
            "keine", "Büro, Frau Schulz", "0170-1234567 (nur abends)",
            "069 123, 0170 456",        # zwei Nummern in einem Feld
            "12", "1234567",            # ohne Vorwahl nicht herstellbar
            "++49170", "0170 123 456 789 012",
        ):
            self.assertIsNone(normalisiere(roh), msg=roh)

    def test_laenge_passt_zum_modellfeld(self):
        from intern.models import User
        from intern.telefon import MAX_LAENGE, normalisiere
        self.assertEqual(MAX_LAENGE, User._meta.get_field("telefon").max_length)
        self.assertLessEqual(len(normalisiere("+49 170 123456789")), MAX_LAENGE)

    def test_feldliste(self):
        from intern.mitglied_felder import PRIVACY_FIELDS
        from intern.telefon import FELDER
        self.assertEqual(
            set(FELDER),
            {"telefon", "telefon_mobil", "telefon_job", "telefon_job_mobil", "fax"},
        )
        self.assertTrue(set(FELDER) <= set(PRIVACY_FIELDS))

    def test_vorwahllaenge(self):
        from intern.telefon import _de_vorwahllaenge
        self.assertEqual(_de_vorwahllaenge("301234567"), 2)
        self.assertEqual(_de_vorwahllaenge("2111234567"), 3)
        self.assertEqual(_de_vorwahllaenge("1711234567"), 3)
        self.assertEqual(_de_vorwahllaenge("15731234567"), 4)
        self.assertEqual(_de_vorwahllaenge("6151123456"), 4)

    def test_formular_meldet_unlesbare_nummer(self):
        from intern.forms import TelefonNormalisierungMixin

        class Probeformular(TelefonNormalisierungMixin, forms.Form):
            telefon = forms.CharField(required=False)

        with mock.patch("intern.app_settings.get_config", return_value="+49"):
            form = Probeformular(data={"telefon": "0170/1234567"})
            self.assertTrue(form.is_valid())
            self.assertEqual(form.cleaned_data["telefon"], "+49 170 1234567")

            form = Probeformular(data={"telefon": "nur abends"})
            self.assertFalse(form.is_valid())
            self.assertIn("telefon", form.errors)


class MitgliederSpaltenTest(SimpleTestCase):
    """Die Mitgliederliste übergibt der Tabelle eine Seite als Liste, kein Queryset.

    Ohne Queryset kennt django_tables2 das Modell nicht und bildet die Überschrift
    aus dem Feldnamen („First name“). Jede Spalte braucht daher ihren deutschen
    Namen in der Tabelle selbst.
    """

    def test_ueberschriften_ohne_queryset(self):
        from intern.tables import MitgliederTabelle

        koepfe = {c.name: str(c.header) for c in MitgliederTabelle([]).columns}
        self.assertEqual(koepfe["first_name"], "Vorname")
        self.assertEqual(koepfe["last_name"], "Nachname")
        self.assertEqual(koepfe["last_login"], "Letzte Anmeldung")
        self.assertEqual(koepfe["strasse"], "Straße")
        self.assertEqual(koepfe["aktiv"], "Zugang")
        # Der Rückfall auf den Feldnamen erzeugt „Wort wort“ aus einem Unterstrich.
        for name, kopf in koepfe.items():
            with self.subTest(name=name):
                self.assertNotEqual(kopf, name.replace("_", " ").capitalize() if "_" in name else None)


class ForumAnzeigeAbTest(SimpleTestCase):
    """``FORUM_ANZEIGE_AB``: ein Tippfehler darf keine Forenseite umwerfen."""

    def test_gueltiges_datum(self):
        self.assertEqual(
            app_settings.lese_forum_anzeige_ab("2025-01-15"), datetime(2025, 1, 15)
        )

    def test_leer_und_ungueltig_fallen_auf_den_standard(self):
        standard = datetime.combine(
            date.fromisoformat(app_settings.FORUM_ANZEIGE_AB_STANDARD), time()
        )
        for roh in (None, "", "  ", "15.01.2025", "kaputt"):
            with self.subTest(roh=roh):
                self.assertEqual(app_settings.lese_forum_anzeige_ab(roh), standard)

    def test_standard_steht_im_katalog(self):
        from intern.apps import _CONFIG_DEFAULTS

        werte = {row[0]: row[1] for row in _CONFIG_DEFAULTS}
        self.assertEqual(
            werte["FORUM_ANZEIGE_AB"], app_settings.FORUM_ANZEIGE_AB_STANDARD
        )


class NamensverweisTest(SimpleTestCase):
    """Namensverweise (Absender alter Beiträge) erkennt man an ``last_name`` NULL.

    NULL, nicht "": kein Formular schreibt NULL, und unter MariaDB (PAD SPACE)
    wäre ``last_name = ''`` auch für ``' '`` wahr. Die Suite sieht keine
    Datenbank, darum pinnt der Test die Form der Bedingung.
    """

    def test_bedingung(self):
        from intern.models import NAMENSVERWEIS

        self.assertEqual(NAMENSVERWEIS, Q(last_name__isnull=True))

    def test_anzeige_nur_vorname(self):
        from intern.models import User

        verweis = User(first_name="Max", last_name=None)
        self.assertTrue(verweis.ist_namensverweis)
        self.assertEqual(str(verweis), "Max")
        self.assertEqual(verweis.get_full_name(), "Max")

    def test_echtes_konto(self):
        from intern.models import User

        self.assertEqual(str(User(first_name="Max", last_name="Muster")), "Max Muster")
        self.assertFalse(User(first_name="Max", last_name="").ist_namensverweis)


class MitteilungStichtagTest(SimpleTestCase):
    """Kein Forenbeitrag vor ``FORUM_ANZEIGE_AB`` erreicht eine Ansicht.

    Der Standardmanager filtert jede Abfrage. Zwei Wege führen an ihm vorbei:
    ``Mitteilung.alle`` und Joins über ``mitteilung`` (``Count``, ``Max``,
    ``mitteilung__…``). Beide sind hier je Datei gezählt; eine neue Stelle macht
    den Test rot, bis jemand den Stichtag dort bewusst geprüft und die Zahl
    angepasst hat.
    """

    _JOIN = re.compile(r'mitteilung__|(?:Count|Max|Min|Sum|Avg)\(\s*"mitteilung"')
    _ALLE = re.compile(r"Mitteilung\.alle\b")

    # Datei → Anzahl Join-Stellen, mit dem Grund, warum sie so stimmen.
    JOINS = {
        # Max("mitteilung__id") setzt nur die Lesemarke — bewusst ungefiltert.
        "forum_gelesen.py": 1,
        # Raumreihenfolge der Brücke nach letztem Beitrag — keine Anzeige.
        "management/commands/ejabberd_bot.py": 1,
        # ab_stichtag (Signatur + Docstring), extra_data (Count, Max mit
        # ab_stichtag), mit_ungelesen (Count + drei Lookups, mit ab_stichtag).
        "models.py": 8,
        # Suche: Feld ``mitteilung`` über den Standardmanager; Reaktionen mit
        # ab_stichtag.
        "views/forums.py": 2,
    }
    # Datei → Anzahl ``Mitteilung.alle`` (ungefiltert, nur technische Pfade).
    ALLE = {
        # Relay, Dedupe, Stanza-IDs der Brücke — Verhalten wie vor dem Stichtag.
        "management/commands/ejabberd_bot.py": 9,
        # has_history in mitglied_delete: alte Beiträge sind auch Geschichte.
        "views/mitglieder.py": 1,
    }

    def _zaehle(self, muster):
        wurzel = Path(__file__).resolve().parent
        treffer = {}
        for pfad in sorted(wurzel.rglob("*.py")):
            rel = pfad.relative_to(wurzel).as_posix()
            if rel.startswith("migrations/") or rel == "tests.py":
                continue
            n = len(muster.findall(pfad.read_text(encoding="utf-8")))
            if n:
                treffer[rel] = n
        return treffer

    def test_join_stellen_sind_geprueft(self):
        self.assertEqual(self._zaehle(self._JOIN), self.JOINS)

    def test_ungefilterter_manager_nur_wo_geprueft(self):
        self.assertEqual(self._zaehle(self._ALLE), self.ALLE)

    def test_forum_joins_tragen_den_stichtag(self):
        import inspect

        from intern.models import ForumQuerySet

        quelle = inspect.getsource(ForumQuerySet)
        self.assertEqual(quelle.count("ab_stichtag()"), 3)

    def test_standardmanager_filtert(self):
        from intern.models import Mitteilung, MitteilungManager

        self.assertIsInstance(Mitteilung._default_manager, MitteilungManager)
        stichtag = datetime(2025, 3, 1)
        with mock.patch.object(
            app_settings, "get_forum_anzeige_ab", return_value=stichtag
        ):
            where = Mitteilung.objects.all().query.where
        (bedingung,) = where.children
        self.assertEqual(bedingung.lhs.target.name, "datum")
        self.assertEqual(bedingung.lookup_name, "gte")
        self.assertEqual(bedingung.rhs, stichtag)


class RechteHilfeTest(SimpleTestCase):
    """Der Hilfe-Dialog auf /intern/gruppen/: jedes Recht hat Stellen, ein zweites
    Recht ist ein bekanntes, und die Inhaber stehen nach ihrer Quelle."""

    def test_jedes_recht_hat_stellen(self):
        from intern.views.gruppen import PERMISSION_DEFS, PERMISSION_DETAILS

        rechte = [perm for perm, _, _ in PERMISSION_DEFS]
        self.assertEqual(set(PERMISSION_DETAILS), set(rechte))
        for perm in rechte:
            self.assertTrue(PERMISSION_DETAILS[perm], perm)

    def test_zweites_recht_ist_bekannt(self):
        from intern.views.gruppen import PERMISSION_DEFS, PERMISSION_DETAILS

        rechte = {perm for perm, _, _ in PERMISSION_DEFS}
        for perm, stellen in PERMISSION_DETAILS.items():
            for stelle in stellen:
                self.assertIn(len(stelle), (2, 3), perm)
                if len(stelle) == 3:
                    self.assertIn(stelle[2], rechte, perm)
                    self.assertNotEqual(stelle[2], perm)

    def test_inhaber_nach_quelle(self):
        from intern.views.gruppen import rechte_inhaber

        ergebnis = rechte_inhaber(
            ["intern.add_ort", "intern.view_forum_archiv", "intern.delete_ort"],
            {"Vorstand": {"intern.add_ort", "intern.view_forum_archiv"},
             "Leer": {"intern.add_ort"}},
            {"Vorstand": ["Anna"], "Leer": []},
            {"intern.add_ort": ["Bert"]},
            ["Chris"],
        )
        self.assertEqual(ergebnis["intern.add_ort"], [
            {"quelle": "Vorstand", "namen": ["Anna"]},
            {"quelle": "Leer", "namen": []},
            {"quelle": "Direkt zugewiesen", "namen": ["Bert"]},
            {"quelle": "Admin", "namen": ["Chris"]},
        ])
        # Das Archivrecht haben Admins nicht von selbst (darf_forum_archiv).
        self.assertEqual(ergebnis["intern.view_forum_archiv"], [
            {"quelle": "Vorstand", "namen": ["Anna"]},
        ])
        self.assertEqual(ergebnis["intern.delete_ort"], [
            {"quelle": "Admin", "namen": ["Chris"]},
        ])

    def test_eigene_quellen(self):
        from intern.views.gruppen import PERMISSION_DEFS, rechte_hilfe, rechte_quellen

        quellen = rechte_quellen(
            {"Vorstand": {"intern.add_ort"}, "Mitglied": {"intern.add_ort", "intern.notify_user"}},
            {"intern.delete_ort"},
            False,
        )
        self.assertEqual(quellen, {
            "intern.notify_user": ["Mitglied"],
            "intern.add_ort": ["Vorstand", "Mitglied"],
            "intern.delete_ort": ["Direkt zugewiesen"],
        })
        # Admin: jedes Recht außer dem Archivrecht, das ausdrücklich vergeben wird.
        admin = rechte_quellen({}, set(), True)
        self.assertEqual(len(admin), len(PERMISSION_DEFS) - 1)
        self.assertNotIn("intern.view_forum_archiv", admin)
        hilfe = rechte_hilfe(["intern.add_ort"], {"intern.add_ort": {"quellen": ["Vorstand"]}})
        self.assertEqual(hilfe["intern.add_ort"]["titel"], "Orte · anlegen")
        self.assertEqual(hilfe["intern.add_ort"]["quellen"], ["Vorstand"])


class FilterbauParseTest(SimpleTestCase):
    """Die Kette des Filter-Baukastens lesen: `f=verbindung:feld:operator:werte`."""

    def _lesen(self, *zeilen):
        from intern.filterbau_mitglieder import MITGLIEDER

        daten = QueryDict("", mutable=True)
        for zeile in zeilen:
            daten.appendlist("f", zeile)
        return MITGLIEDER.lese_bedingungen(daten)

    def test_zeile(self):
        from intern.filterbau import Bedingung

        self.assertEqual(
            self._lesen("und:gruppen:in:1,4"),
            [Bedingung("und", "gruppen", "in", ("1", "4"))],
        )

    def test_erste_bedingung_ohne_konnektor(self):
        # Vor der ersten Zeile ist nichts, womit sie sich verknuepfen koennte.
        self.assertEqual(self._lesen("oder:gruppen:in:1")[0].verbindung, "und")

    def test_konnektoren_bleiben(self):
        gelesen = self._lesen("und:gruppen:in:1", "oder:stimme:in:S")
        self.assertEqual([b.verbindung for b in gelesen], ["und", "oder"])

    def test_verwirft_unbekanntes(self):
        # Ein unbekanntes Feld, ein unbekannter Operator, zu wenig Teile, leere Werte.
        for zeile in (
            "und:erfunden:in:1",
            "und:gruppen:erfunden:1",
            "und:gruppen:in",
            "und:gruppen:in:",
            "und:gruppen:in:,,",
            "",
        ):
            self.assertEqual(self._lesen(zeile), [], zeile)

    def test_unbekannter_konnektor_ist_und(self):
        self.assertEqual(self._lesen("vielleicht:gruppen:in:1")[0].verbindung, "und")

    def test_leere_werte_zwischendurch_fallen_heraus(self):
        self.assertEqual(self._lesen("und:gruppen:in:1,,4")[0].werte, ("1", "4"))

    def test_ohne_f_keine_bedingungen(self):
        from intern.filterbau_mitglieder import MITGLIEDER

        self.assertEqual(MITGLIEDER.lese_bedingungen(QueryDict("")), [])


class FilterbauAltTest(SimpleTestCase):
    """Die Parameter der Zeit vor dem Baukasten.

    ``@tabellenzustand`` merkt sich die Query ein Jahr im Cookie und leitet einen
    Aufruf ohne Parameter dorthin um. Kennte die Ansicht die alten Namen nicht mehr,
    saehe man eine ungefilterte Liste, die wie eine gefilterte aussieht.
    """

    def _lesen(self, **params):
        from intern.filterbau_mitglieder import MITGLIEDER

        daten = QueryDict("", mutable=True)
        for name, werte in params.items():
            for wert in werte:
                daten.appendlist(name, wert)
        return MITGLIEDER.lese_bedingungen(daten)

    def test_gruppen_werden_einschluss(self):
        from intern.filterbau import Bedingung

        self.assertEqual(
            self._lesen(gruppen=["1", "2"]),
            [Bedingung("und", "gruppen", "in", ("1", "2"))],
        )

    def test_gruppen_nicht_werden_ausschluss(self):
        from intern.filterbau import Bedingung

        self.assertEqual(
            self._lesen(gruppen_nicht=["7"]),
            [Bedingung("und", "gruppen", "nicht-in", ("7",))],
        )

    def test_stimmen(self):
        self.assertEqual(self._lesen(stimme=["S", "A"])[0].werte, ("S", "A"))

    def test_f_hat_vorrang(self):
        # Steht ein `f` in der Query, ist es der neue Weg -- die Altparameter daneben
        # sind dann Reste und werden nicht zusaetzlich ausgewertet.
        from intern.filterbau_mitglieder import MITGLIEDER

        daten = QueryDict("f=und:gruppen:in:1&gruppen=9", mutable=True)
        self.assertEqual(MITGLIEDER.lese_bedingungen(daten)[0].werte, ("1",))

    def test_leere_altwerte(self):
        self.assertEqual(self._lesen(gruppen=[""], gruppen_nicht=[""]), [])


class FilterbauQTest(SimpleTestCase):
    """``baue_q`` ohne Datenbank.

    Verglichen wird die **Verknuepfungsform**, nicht die Gleichheit der Q-Objekte: die
    Blaetter ueber Mehrfachrelationen sind EXISTS-Unterabfragen (`Exists`), und die
    sind nur sich selbst gleich. Die Form ist ohnehin das, worum es hier geht --
    UND bindet staerker als ODER. ``+`` ist eine Bedingung, ``-`` eine verneinte.
    """

    def _q(self, *zeilen):
        from intern.filterbau import Bedingung
        from intern.filterbau_mitglieder import MITGLIEDER

        bedingungen = []
        for i, (verbindung, feld, operator, werte) in enumerate(zeilen):
            bedingungen.append(
                Bedingung(
                    verbindung if i else "und", feld, operator, tuple(werte.split(","))
                )
            )
        return MITGLIEDER.baue_q(bedingungen)

    def _form(self, q):
        from django.db.models.expressions import NegatedExpression

        if not isinstance(q, Q):
            return "-" if isinstance(q, NegatedExpression) else "+"
        kinder = [self._form(k) for k in q.children]
        if len(kinder) == 1:
            return kinder[0]
        wort = " und " if q.connector == "AND" else " oder "
        return "(%s)" % wort.join(kinder)

    def test_einschluss(self):
        self.assertEqual(self._form(self._q(("und", "gruppen", "in", "1,4"))), "+")

    def test_ausschluss_ist_negiert(self):
        self.assertEqual(self._form(self._q(("und", "gruppen", "nicht-in", "7"))), "-")

    def test_reine_und_kette(self):
        # Der Fall des Nutzers: in A und in B und nicht in C.
        self.assertEqual(
            self._form(self._q(
                ("und", "gruppen", "in", "1"),
                ("und", "gruppen", "in", "2"),
                ("und", "gruppen", "nicht-in", "3"),
            )),
            "(+ und + und -)",
        )

    def test_und_bindet_staerker_als_oder(self):
        # A oder B und C muss A oder (B und C) sein, nicht (A oder B) und C.
        self.assertEqual(
            self._form(self._q(
                ("und", "gruppen", "in", "1"),
                ("oder", "gruppen", "in", "2"),
                ("und", "gruppen", "in", "3"),
            )),
            "(+ oder (+ und +))",
        )

    def test_zwei_abschnitte(self):
        self.assertEqual(
            self._form(self._q(
                ("und", "stimme", "in", "S"),
                ("oder", "gruppen", "in", "1"),
                ("und", "gruppen", "in", "2"),
            )),
            "(+ oder (+ und +))",
        )

    def test_ohne_bedingungen_filtert_nichts(self):
        self.assertEqual(self._q(), Q())
        self.assertFalse(self._q())

    def test_verneinte_gruppe_bleibt_beim_ergebnis_frei_von_dubletten(self):
        """Der Filter ueber eine Mehrfachrelation ist eine EXISTS-Unterabfrage.

        Als Join mit Verneinung prueft Django die einzelne Verknuepfungszeile statt
        der Person: wer ausser der ausgeschlossenen Gruppe noch eine andere hat,
        rutschte durch — genau das war der Fehler. Ohne Join gibt es auch keine
        doppelten Koepfe, deshalb braucht es kein ``.distinct()``.
        """
        from intern.models import User
        from intern.filterbau import Bedingung
        from intern.filterbau_mitglieder import MITGLIEDER

        qs = User.objects.all().filter(MITGLIEDER.baue_q([
            Bedingung("und", "gruppen", "in", ("1", "2")),
            Bedingung("und", "gruppen", "nicht-in", ("3",)),
        ]))
        sql = str(qs.query)
        self.assertIn("EXISTS", sql)
        # Die Unterabfrage haengt an der Person, nicht an der Verknuepfungszeile.
        self.assertNotIn('U1."id" = "intern_user_groups"."id"', sql)
        self.assertFalse(qs.query.distinct)


class FilterbauKetteTest(SimpleTestCase):
    """Die Anzeige der Kette in der Titelleiste."""

    def setUp(self):
        from django.test import RequestFactory

        self.rf = RequestFactory()

    @staticmethod
    def _art(element):
        """Ein Anzeigeelement auf seine Art eindampfen -- lesbarer als fuenf Schluessel."""
        if "verb" in element:
            return element["verb"]
        if "klammer" in element:
            return element["klammer"]
        if element.get("chip_type") == "mehr":
            return "+n"
        return "nicht" if element.get("nicht") else "chip"

    def _kette(self, *zeilen, pfad="/intern/mitglied/", max_chips=None, namen=None, **params):
        from intern.filterbau import Bedingung
        from intern.filterbau_mitglieder import MITGLIEDER

        bedingungen = [
            Bedingung(verbindung if i else "und", feld, operator, tuple(werte.split(",")))
            for i, (verbindung, feld, operator, werte) in enumerate(zeilen)
        ]
        daten = [":".join((b.verbindung, b.feld, b.operator, ",".join(b.werte)))
                 for b in bedingungen]
        request = self.rf.get(pfad, {**params, "f": daten})
        if max_chips is None:
            return MITGLIEDER.kette(bedingungen, request, namen=namen)
        return MITGLIEDER.kette(bedingungen, request, namen=namen, max_chips=max_chips)

    def test_reine_und_kette_ohne_klammern(self):
        ergebnis = self._kette(
            ("und", "gruppen", "in", "1"),
            ("und", "gruppen", "in", "2"),
            ("und", "gruppen", "nicht-in", "3"),
        )
        self.assertEqual(
            [FilterbauKetteTest._art(e) for e in ergebnis["elemente"]],
            ["chip", "und", "chip", "und", "nicht"],
        )
        self.assertFalse([e for e in ergebnis["elemente"] if "klammer" in e])
        self.assertEqual(ergebnis["versteckt"], 0)

    def test_klammern_um_jeden_mehrfachen_abschnitt(self):
        # A oder (B und C): nur der zweite Abschnitt traegt eine Bedingung zuviel.
        ergebnis = self._kette(
            ("und", "gruppen", "in", "1"),
            ("oder", "gruppen", "in", "2"),
            ("und", "stimme", "in", "S"),
        )
        self.assertEqual(
            [self._art(e) for e in ergebnis["elemente"]],
            ["chip", "oder", "(", "chip", "und", "chip", ")"],
        )

    def test_klammern_um_beide_abschnitte(self):
        ergebnis = self._kette(
            ("und", "gruppen", "in", "1"),
            ("und", "stimme", "in", "S"),
            ("oder", "gruppen", "in", "2"),
            ("und", "stimme", "in", "A"),
            max_chips=4,
        )
        self.assertEqual(
            [self._art(e) for e in ergebnis["elemente"]],
            ["(", "chip", "und", "chip", ")", "oder", "(", "chip", "und", "chip", ")"],
        )

    def test_einzelne_bedingung_ohne_klammer(self):
        # Eine Bedingung ist schon fuer sich ein Ausdruck.
        ergebnis = self._kette(
            ("und", "stimme", "in", "S"), ("oder", "gruppen", "in", "1")
        )
        self.assertEqual(
            [self._art(e) for e in ergebnis["elemente"]], ["chip", "oder", "chip"]
        )

    def test_deckel_und_klammern_schliessen_sich_aus(self):
        # Abgekuerzt waeren unvollstaendige Klammern nur Rauschen.
        ergebnis = self._kette(
            ("und", "gruppen", "in", "1"),
            ("oder", "gruppen", "in", "2"),
            ("und", "stimme", "in", "S"),
            ("und", "stimme", "in", "A"),
        )
        self.assertEqual(ergebnis["versteckt"], 1)
        self.assertEqual(
            [self._art(e) for e in ergebnis["elemente"]],
            ["chip", "oder", "chip", "und", "chip"],
        )

    def test_titel_traegt_den_vollen_satz(self):
        ergebnis = self._kette(
            ("und", "gruppen", "in", "1"),
            ("und", "gruppen", "nicht-in", "3"),
        )
        self.assertEqual(
            ergebnis["titel"], "ist in Gruppe 1 und ist nicht in Gruppe 3"
        )

    def test_chip_url_entfernt_genau_eine_bedingung(self):
        from urllib.parse import parse_qs, urlsplit

        ergebnis = self._kette(
            ("und", "gruppen", "in", "1"),
            ("und", "gruppen", "in", "2"),
            ("und", "stimme", "in", "S"),
            sort="last_name",
        )
        erste = ergebnis["elemente"][0]
        abfrage = parse_qs(urlsplit(erste["url"]).query)
        self.assertEqual(abfrage["f"], ["und:gruppen:in:2", "und:stimme:in:S"])
        self.assertEqual(abfrage["sort"], ["last_name"])

    def test_letzter_chip_laesst_kein_leeres_f(self):
        from urllib.parse import urlsplit

        ergebnis = self._kette(("und", "stimme", "in", "S"))
        self.assertNotIn("f", urlsplit(ergebnis["elemente"][0]["url"]).query)

    def test_stimme_wird_beschriftet(self):
        ergebnis = self._kette(("und", "stimme", "in", "S,A"))
        self.assertEqual(ergebnis["elemente"][0]["text"], "ist Sopran, Alt")

    def test_unbekannte_gruppe_bleibt_als_kennung(self):
        # Ohne Namensaufloesung stehen die Schluessel -- immer noch besser als nichts.
        ergebnis = self._kette(("und", "gruppen", "in", "1"))
        self.assertEqual(ergebnis["elemente"][0]["text"], "ist in Gruppe 1")

    def test_gruppennamen_werden_eingesetzt(self):
        ergebnis = self._kette(
            ("und", "gruppen", "in", "1,2"),
            ("und", "gruppen", "nicht-in", "9"),
            namen={"gruppen": {"1": "Vorstand", "2": "Kassenprüfer"}},
        )
        self.assertEqual(
            [e["text"] for e in ergebnis["elemente"] if "text" in e],
            ["ist in Gruppe Vorstand, Kassenprüfer", "ist nicht in Gruppe 9"],
        )
        self.assertIn("Vorstand, Kassenprüfer", ergebnis["titel"])


class FilterbauVorlagenTest(SimpleTestCase):
    """Feld- und Operatorauswahl des Baukastens, und das Rechte-Gate."""

    def test_felder_kontext_nur_die_erlaubten(self):
        from intern.filterbau_mitglieder import MITGLIEDER

        # Ohne Verwalterrecht: kein einziges Feld aus PRIVACY_FIELDS, kein Zugang.
        schluessel = [f["key"] for f in MITGLIEDER.felder_kontext(False)]
        self.assertIn("name", schluessel)
        self.assertIn("stimme", schluessel)
        self.assertIn("gruppen", schluessel)
        for gesperrt in ("email", "xmpp", "telefon", "fax", "strasse", "plz", "ort",
                         "geburtstag", "zugang"):
            self.assertNotIn(gesperrt, schluessel, gesperrt)

    def test_felder_kontext_mit_verwalterrecht(self):
        from intern.filterbau_mitglieder import MITGLIEDER

        schluessel = {f["key"] for f in MITGLIEDER.felder_kontext(True)}
        self.assertLessEqual({"email", "telefon", "ort", "geburtstag"}, schluessel)
        # Die Reihenfolge folgt der Tabelle.
        self.assertEqual(
            [f["key"] for f in MITGLIEDER.felder_kontext(True)][:2], ["name", "stimme"]
        )

    def test_operatoren(self):
        from intern.filterbau_mitglieder import MITGLIEDER

        felder = {f["key"]: f for f in MITGLIEDER.felder_kontext(True)}
        self.assertEqual(
            [o["key"] for o in felder["gruppen"]["operatoren"]], ["in", "nicht-in"]
        )
        self.assertTrue(felder["gruppen"]["operatoren"][1]["nicht"])
        self.assertFalse(felder["gruppen"]["operatoren"][0]["nicht"])
        # Das Textfeld traegt die Wortoperatoren; jeder bringt seinen Satzbaustein mit.
        self.assertEqual(
            [o["key"] for o in felder["name"]["operatoren"]],
            ["enthaelt", "enthaelt-nicht", "beginnt", "endet", "ist"],
        )
        self.assertEqual(felder["name"]["operatoren"][0]["satz"], "{feld} enthält {w}")
        self.assertEqual(felder["gruppen"]["operatoren"][0]["satz"], "ist in Gruppe {w}")

    def test_leerzeile_fuer_gesperrtes_feld_ist_none(self):
        from intern.filterbau_mitglieder import MITGLIEDER

        self.assertIsNone(MITGLIEDER.bedingung_fuer_feld("email", False))
        self.assertEqual(MITGLIEDER.bedingung_fuer_feld("email", True).feld, "email")


class FilterbauEscapingTest(SimpleTestCase):
    """Werte werden einzeln kodiert -- ein getippter Name darf Komma und Doppelpunkt
    enthalten, und beides sind hier Trennzeichen."""

    def _rundlauf(self, werte):
        from urllib.parse import quote

        from django.http import QueryDict

        from intern import filterbau
        from intern.filterbau_mitglieder import MITGLIEDER

        bedingung = filterbau.Bedingung("und", "name", "enthaelt", werte)
        # Wie im echten Leben: kodieren, dann als Query-String uebertragen (das macht
        # die Chip-Adresse), dann von Django dekodieren lassen.
        uebertragen = "f=" + quote(filterbau.kodiere(bedingung), safe="")
        gelesen = MITGLIEDER.lese_bedingungen(QueryDict(uebertragen, mutable=True), True)
        return gelesen[0].werte if gelesen else ()

    def test_komma_und_doppelpunkt(self):
        self.assertEqual(self._rundlauf(("Müller, Peter: Test",)), ("Müller, Peter: Test",))

    def test_prozentzeichen(self):
        self.assertEqual(self._rundlauf(("100%",)), ("100%",))

    def test_mehrere_werte_bleiben_getrennt(self):
        self.assertEqual(self._rundlauf(("a,b", "c:d")), ("a,b", "c:d"))

    def test_alte_werte_bleiben_gueltig(self):
        from django.http import QueryDict

        from intern import filterbau
        from intern.filterbau_mitglieder import MITGLIEDER

        gelesen = MITGLIEDER.lese_bedingungen(
            QueryDict("f=und:gruppen:in:1,4", mutable=True), True
        )
        self.assertEqual(gelesen[0].werte, ("1", "4"))


class FilterbauRechteTest(SimpleTestCase):
    """Das Recht greift beim **Lesen**, nicht nur im Dropdown.

    Ohne das umginge eine handgeschriebene Adresse die Oberflaeche und verriete ueber
    die Treffermenge, was die Tabelle verschweigt: der Filter laeuft vor der
    Datenschutz-Schwaerzung.
    """

    def _lesen(self, zeilen, kann_verwalten):
        from django.http import QueryDict

        from intern import filterbau
        from intern.filterbau_mitglieder import MITGLIEDER

        daten = QueryDict("", mutable=True)
        for zeile in zeilen:
            daten.appendlist("f", zeile)
        return MITGLIEDER.lese_bedingungen(daten, kann_verwalten)

    def test_gesperrtes_feld_faellt_heraus(self):
        self.assertEqual(self._lesen(["und:email:enthaelt:gmail"], False), [])

    def test_mit_verwalterrecht_bleibt_es(self):
        gelesen = self._lesen(["und:email:enthaelt:gmail"], True)
        self.assertEqual(gelesen[0].feld, "email")

    def test_erlaubte_felder_bleiben(self):
        gelesen = self._lesen(
            ["und:email:enthaelt:gmail", "und:name:enthaelt:Meier"], False
        )
        self.assertEqual([b.feld for b in gelesen], ["name"])

    def test_zugang_ist_gesperrt(self):
        self.assertEqual(self._lesen(["und:zugang:hat:"], False), [])

    def test_ein_gesperrtes_feld_wird_nicht_zur_ersten_bedingung(self):
        # Faellt die erste weg, rueckt die naechste nach und traegt keinen Konnektor.
        gelesen = self._lesen(
            ["und:email:enthaelt:gmail", "oder:name:enthaelt:Meier"], False
        )
        self.assertEqual([(b.verbindung, b.feld) for b in gelesen], [("und", "name")])


class FilterbauAltTest2(SimpleTestCase):
    """Die festen Felder von vor dem Baukasten: zugang, status, konzert."""

    def _lesen(self, **params):
        from django.http import QueryDict

        from intern import filterbau
        from intern.filterbau_mitglieder import MITGLIEDER

        daten = QueryDict("", mutable=True)
        for name, wert in params.items():
            daten[name] = wert
        return MITGLIEDER.lese_bedingungen(daten, True)

    def test_zugang_true(self):
        self.assertEqual(
            self._lesen(zugang="true")[0],
            filterbau_bedingung("und", "zugang", "hat", ()),
        )

    def test_zugang_false(self):
        gelesen = self._lesen(zugang="false")
        self.assertEqual((gelesen[0].feld, gelesen[0].operator), ("zugang", "hat-nicht"))

    def test_zugang_unknown_ergibt_nichts(self):
        # „Egal" war der dritte Zustand des Schalters und ist keine Bedingung.
        self.assertEqual(self._lesen(zugang="unknown"), [])

    def test_status_mit_termin(self):
        gelesen = self._lesen(status="1", konzert="7")
        self.assertEqual(gelesen[0].feld, "zusage")
        self.assertEqual(gelesen[0].werte, ("7", "1"))

    def test_status_null_heisst_nicht_geantwortet(self):
        # Das Termin-Feld ist entfallen; „keine Zeile" ist jetzt „hat nicht geantwortet".
        gelesen = self._lesen(status="0", konzert="7")
        self.assertEqual(
            (gelesen[0].feld, gelesen[0].operator, gelesen[0].werte),
            ("zusage", "hat-nicht", ("7", "beantwortet")),
        )

    def test_termin_ohne_status_filtert_nicht(self):
        # Der Termin war nur Kontext fuer den Status und filterte allein nichts.
        self.assertEqual(self._lesen(konzert="7"), [])


def filterbau_bedingung(*args):
    from intern.filterbau import Bedingung

    return Bedingung(*args)


class FilterbauQNeuTest(SimpleTestCase):
    """Die Q-Bauer der neuen Felder."""

    def _q(self, feld, operator, *werte):
        from intern.filterbau_mitglieder import FELDER

        return FELDER[feld].q(operator, tuple(werte))

    def _sql(self, feld, operator, *werte):
        """Das kompilierte SQL -- Mehrfachrelationen sind EXISTS-Unterabfragen, und
        die lassen sich nicht als Q-Objekt vergleichen."""
        from intern.models import User

        return str(User.objects.all().filter(self._q(feld, operator, *werte)).query)

    def test_name_enthaelt_ueber_beide_namen(self):
        self.assertEqual(
            self._q("name", "enthaelt", "Mei"),
            Q(first_name__icontains="Mei") | Q(last_name__icontains="Mei"),
        )

    def test_name_enthaelt_nicht_ist_negiert(self):
        self.assertEqual(
            self._q("name", "enthaelt-nicht", "Mei"),
            ~(Q(first_name__icontains="Mei") | Q(last_name__icontains="Mei")),
        )

    def test_textoperatoren(self):
        self.assertEqual(self._q("ort", "beginnt", "Ber"), Q(ort__istartswith="Ber"))
        self.assertEqual(self._q("ort", "endet", "lin"), Q(ort__iendswith="lin"))
        self.assertEqual(self._q("ort", "ist", "Berlin"), Q(ort__iexact="Berlin"))

    def test_zugang(self):
        self.assertEqual(self._q("zugang", "hat"), Q(is_active=True))
        self.assertEqual(self._q("zugang", "hat-nicht"), Q(is_active=False))

    def test_zusage_ist_exists_und_haengt_an_der_person(self):
        # Eine Mehrfachrelation wird als EXISTS-Unterabfrage geprueft, nicht als Join
        # -- siehe FilterbauQTest. Das SQL haengt an der Person, nicht an einer
        # Verknuepfungszeile.
        sql = self._sql("zusage", "hat", "7", "1")
        self.assertIn("EXISTS", sql)
        self.assertIn("intern_zusage", sql)
        self.assertIn('"termin_id" = 7', sql)
        self.assertIn('"person_id" = ("intern_user"."id")', sql)
        self.assertNotIn("NOT EXISTS", sql)
        self.assertIn("NOT EXISTS", self._sql("zusage", "hat-nicht", "7", "1"))

    def test_zusage_antwort(self):
        sql = self._sql("zusage", "hat", "7", "2")
        self.assertIn("EXISTS", sql)
        self.assertIn('"option" = 2', sql)
        self.assertIn('"termin_id" = 7', sql)

    def test_zusage_ohne_angabe_ist_die_leere_option(self):
        # Die leere Option ist eine echte Zeile -- „ohne Angabe" ist etwas anderes als
        # „hat nicht geantwortet".
        sql = self._sql("zusage", "hat", "7", "ohne")
        self.assertIn('"option" = ', sql)
        self.assertNotIn('"option" = 1', sql)

    def test_zusage_beantwortet(self):
        self.assertIn(
            '"option" IN (1, 2, 3)', self._sql("zusage", "hat", "7", "beantwortet")
        )

    def test_datum(self):
        self.assertEqual(self._q("geburtstag", "vor", "1990-01-01"),
                         Q(geburtstag__lt="1990-01-01"))
        self.assertEqual(self._q("geburtstag", "nach", "1990-01-01"),
                         Q(geburtstag__gt="1990-01-01"))

    def test_zeitstempel_vergleichen_das_datum(self):
        # last_login ist ein DateTimeField -- ohne __date faende „vor dem 1.1." den
        # 1.1. selbst nicht mehr.
        self.assertEqual(self._q("last_login", "vor", "2026-01-01"),
                         Q(last_login__date__lt="2026-01-01"))


class FilterbauVorgabeTest(SimpleTestCase):
    """Die Zugangs-Vorgabe des Verwalters und ihr Opt-out."""

    def _daten(self, query=""):
        from django.http import QueryDict

        return QueryDict(query, mutable=True)

    def test_ohne_verwalterrecht_keine_vorgabe(self):
        from intern import filterbau
        from intern.filterbau_mitglieder import MITGLIEDER

        self.assertEqual(MITGLIEDER.vorgabe([], self._daten(), False), [])

    def test_verwalter_bekommt_die_vorgabe(self):
        from intern import filterbau
        from intern.filterbau_mitglieder import MITGLIEDER

        gelesen = MITGLIEDER.vorgabe([], self._daten(), True)
        self.assertEqual((gelesen[0].feld, gelesen[0].operator), ("zugang", "hat"))

    def test_egal_schaltet_sie_ab(self):
        from intern import filterbau
        from intern.filterbau_mitglieder import MITGLIEDER

        self.assertEqual(
            MITGLIEDER.vorgabe([], self._daten("zugang=egal"), True), []
        )

    def test_alte_egal_wahl_schaltet_sie_ebenso_ab(self):
        # Der alte Schalter hatte den dritten Zustand „unknown" -- dieselbe Aussage.
        from intern import filterbau
        from intern.filterbau_mitglieder import MITGLIEDER

        self.assertEqual(
            MITGLIEDER.vorgabe([], self._daten("zugang=unknown"), True), []
        )

    def test_eigene_zugangsbedingung_gewinnt(self):
        from intern import filterbau
        from intern.filterbau_mitglieder import MITGLIEDER

        eigen = [filterbau.Bedingung("und", "zugang", "hat-nicht", ())]
        self.assertEqual(MITGLIEDER.vorgabe(eigen, self._daten(), True), eigen)

    def test_chip_der_vorgabe_setzt_egal(self):
        from django.test import RequestFactory

        from intern import filterbau
        from intern.filterbau_mitglieder import MITGLIEDER

        bedingung = filterbau.Bedingung("und", "zugang", "hat", ())
        request = RequestFactory().get(
            "/intern/mitglied/", {"f": filterbau.kodiere(bedingung)}
        )
        ergebnis = MITGLIEDER.kette([bedingung], request)
        self.assertEqual(ergebnis["elemente"][0]["url"], "/intern/mitglied/?zugang=egal")

    def test_andere_bedingung_setzt_kein_egal(self):
        from django.test import RequestFactory

        from intern import filterbau
        from intern.filterbau_mitglieder import MITGLIEDER

        bedingung = filterbau.Bedingung("und", "stimme", "in", ("S",))
        request = RequestFactory().get(
            "/intern/mitglied/", {"f": filterbau.kodiere(bedingung)}
        )
        ergebnis = MITGLIEDER.kette([bedingung], request)
        self.assertEqual(ergebnis["elemente"][0]["url"], "/intern/mitglied/")


class FilterbauChipTextTest(SimpleTestCase):
    """Der Chip liest sich als Satz — „ist in Gruppe Vorstand", nicht „Gruppen: Vorstand".

    Die Verneinung steckt im Satz („ist nicht in …"); das rote Hinterlegen kommt
    weiterhin aus ``ist_verneinend``, aber es steht kein zweites „nicht" davor.
    """

    def setUp(self):
        from django.test import RequestFactory

        self.rf = RequestFactory()

    def _chip(self, feld, operator, *werte, namen=None):
        from intern import filterbau
        from intern.filterbau_mitglieder import MITGLIEDER

        bedingung = filterbau.Bedingung("und", feld, operator, tuple(werte))
        request = self.rf.get("/intern/mitglied/", {"f": filterbau.kodiere(bedingung)})
        return MITGLIEDER.kette([bedingung], request, namen)["elemente"][0]

    def _text(self, feld, operator, *werte, namen=None):
        return self._chip(feld, operator, *werte, namen=namen)["text"]

    def test_textfeld_als_satz(self):
        self.assertEqual(self._text("name", "enthaelt", "Mei"), "Name enthält Mei")
        self.assertEqual(self._text("name", "beginnt", "Mei"), "Name beginnt mit Mei")
        self.assertEqual(self._text("name", "endet", "Mei"), "Name endet mit Mei")
        self.assertEqual(self._text("name", "ist", "Mei"), "Name ist Mei")
        self.assertEqual(self._text("ort", "enthaelt", "Ber"), "Ort enthält Ber")

    def test_verneinung_steht_im_satz_und_bleibt_rot(self):
        chip = self._chip("name", "enthaelt-nicht", "Mei")
        self.assertEqual(chip["text"], "Name enthält nicht Mei")
        self.assertTrue(chip["nicht"])
        self.assertEqual(chip["chip_type"], "false")
        # Kein zweites „nicht" davor — der Satz traegt es schon.
        self.assertFalse(chip["text"].startswith("nicht"))

    def test_gruppen_als_satz(self):
        self.assertEqual(
            self._text("gruppen", "in", "1", "2", namen={"gruppen": {"1": "Vorstand", "2": "Kassenprüfer"}}),
            "ist in Gruppe Vorstand, Kassenprüfer",
        )
        self.assertEqual(
            self._text("gruppen", "nicht-in", "3", namen={"gruppen": {"3": "Webmaster"}}),
            "ist nicht in Gruppe Webmaster",
        )

    def test_stimme_als_satz(self):
        self.assertEqual(self._text("stimme", "in", "S"), "ist Sopran")
        self.assertEqual(self._text("stimme", "nicht-in", "S", "A"), "ist nicht Sopran, Alt")

    def test_zugang_ohne_wert(self):
        self.assertEqual(self._text("zugang", "hat"), "hat Zugang")
        self.assertEqual(self._text("zugang", "hat-nicht"), "hat keinen Zugang")

    def test_datum_als_satz(self):
        self.assertEqual(
            self._text("geburtstag", "vor", "1990-01-01"), "Geburtstag vor dem 01.01.1990"
        )
        self.assertEqual(
            self._text("last_login", "nach", "2026-01-01"), "Letzte Anmeldung nach dem 01.01.2026"
        )

    def test_zusage_liest_als_satz(self):
        namen = {"termin": {"7": "Konzert am 12.03.26"}}
        self.assertEqual(
            self._text("zusage", "hat", "7", "beantwortet", namen=namen),
            "hat geantwortet zu Konzert am 12.03.26",
        )
        self.assertEqual(
            self._text("zusage", "hat-nicht", "7", "1", namen=namen),
            "hat nicht zugesagt zu Konzert am 12.03.26",
        )
        # „ohne Angabe" braucht ein eigenes Wort fuer die Verneinung.
        self.assertEqual(
            self._text("zusage", "hat", "7", "ohne", namen=namen),
            "hat keine Angabe gemacht zu Konzert am 12.03.26",
        )
        self.assertEqual(
            self._text("zusage", "hat-nicht", "7", "ohne", namen=namen),
            "hat eine Angabe gemacht zu Konzert am 12.03.26",
        )

    def test_unbekannter_termin_bleibt_als_kennung(self):
        self.assertEqual(self._text("zusage", "hat", "7", "1"), "hat zugesagt zu 7")

    def test_termin_feld_gibt_es_nicht_mehr(self):
        # „Zusage" deckt es ab: „hat / geantwortet" ist genau das, was es konnte.
        from intern.filterbau_mitglieder import FELDER, FELD_REIHENFOLGE

        self.assertNotIn("termin", FELDER)
        self.assertNotIn("termin", FELD_REIHENFOLGE)


class FilterbauSchalterTest(SimpleTestCase):
    """Wo der Drei-Zustand-Schalter steht.

    Ja/Nein-Felder ohne Wert sind feste Schalter unter der Kette und fehlen im
    Feld-Dropdown. In einer Zeile gibt es den Schalter nur bei einem Einzelwert; eine
    Mehrfachauswahl bekommt die Auswahlliste „ist in / ist nicht in", Text- und
    Datumsfelder ihre Wortoperatoren.
    """

    def _arten(self, felder):
        from intern.filterbau import hat_schalter, ist_fest

        return (
            {k for k, f in felder.items() if ist_fest(f)},
            {k for k, f in felder.items() if hat_schalter(f)},
        )

    def test_mitgliederliste(self):
        from intern.filterbau_mitglieder import FELDER

        self.assertEqual(self._arten(FELDER), ({"zugang"}, {"zusage"}))

    def test_repertoire(self):
        from intern.filterbau_titel import FELDER

        fest, schalter = self._arten(FELDER)
        self.assertEqual(fest, {"aktiv", "hymne", "acapella", "weihnacht",
                                "original", "aufnahme", "pdf", "noten", "text"})
        self.assertEqual(schalter, {"tempo", "tonart"})

    def test_feste_felder_fehlen_im_dropdown(self):
        from intern.filterbau_mitglieder import MITGLIEDER
        from intern.filterbau_titel import TITEL

        felder = {f["key"]: f for f in MITGLIEDER.felder_kontext(True)}
        self.assertNotIn("zugang", felder)
        self.assertFalse(felder["gruppen"]["schalter"])
        self.assertTrue(felder["zusage"]["schalter"])
        self.assertFalse(felder["name"]["schalter"])
        self.assertEqual(
            [f["key"] for f in TITEL.felder_kontext()],
            ["suche", "tempo", "tonart", "solist", "dirigent"],
        )

    def test_feste_schalter_mit_stellung(self):
        from intern.filterbau import Bedingung
        from intern.filterbau_titel import TITEL

        feste = {f["key"]: f for f in TITEL.feste_kontext(
            [Bedingung("und", "hymne", "ja", ()), Bedingung("und", "aufnahme", "nein", ())]
        )}
        self.assertEqual(feste["hymne"]["stellung"], "ja")
        self.assertEqual(feste["hymne"]["wert"], "und:hymne:ja:")
        self.assertEqual(feste["aufnahme"]["stellung"], "nein")
        self.assertEqual(feste["weihnacht"]["stellung"], "egal")
        self.assertEqual(feste["weihnacht"]["wert"], "")

    def test_zugang_traegt_den_egal_marker(self):
        # Steht der Zugangs-Schalter auf „egal", schickt das Formular den Marker mit --
        # sonst haengte die Vorgabe „hat Zugang" sofort wieder an.
        from intern.filterbau_mitglieder import MITGLIEDER
        from intern.filterbau_titel import TITEL

        feste = {f["key"]: f for f in MITGLIEDER.feste_kontext([], True)}
        self.assertEqual(feste["zugang"]["marker"], {"zugang": "egal"})
        self.assertEqual(MITGLIEDER.feste_kontext([], False), [])
        self.assertFalse(any(f["marker"] for f in TITEL.feste_kontext([])))


class FilterbauFestTest(SimpleTestCase):
    """Die festen Bedingungen gelten fuer die ganze Kette: ``fest und (Kette)``."""

    def setUp(self):
        from django.test import RequestFactory

        self.rf = RequestFactory()

    def _b(self, *zeilen):
        from intern.filterbau import Bedingung

        return [Bedingung(v, f, o, tuple(w.split(",")) if w else ())
                for v, f, o, w in zeilen]

    def test_q_haengt_fest_vor_die_ganze_kette(self):
        from intern.filterbau_titel import TITEL

        # Mitten in einer ODER-Kette darf „Hymne" nicht nur an einem Abschnitt haengen.
        q = TITEL.baue_q(self._b(
            ("und", "tempo", "ist", "s"),
            ("oder", "hymne", "ja", ""),
            ("oder", "tonart", "ist", "C"),
        ))
        self.assertEqual(
            q, Q(hymne=True) & (Q(tempo__in=("s",)) | Q(tonart__in=("C",)))
        )

    def test_lesen_ordnet_feste_nach_vorn(self):
        from django.http import QueryDict

        from intern.filterbau_titel import TITEL

        daten = QueryDict("", mutable=True)
        daten.setlist("f", ["und:tempo:ist:s", "oder:hymne:ja:", "oder:tonart:ist:C"])
        gelesen = TITEL.lese_bedingungen(daten)
        self.assertEqual(
            [(b.verbindung, b.feld) for b in gelesen],
            [("und", "hymne"), ("und", "tempo"), ("oder", "tonart")],
        )

    def test_kette_klammert_den_rest(self):
        from intern.filterbau_titel import TITEL

        ergebnis = TITEL.kette(
            self._b(("und", "hymne", "ja", ""), ("und", "tempo", "ist", "s"),
                    ("oder", "tonart", "ist", "C")),
            self.rf.get("/intern/titel/"),
        )
        self.assertEqual(
            [FilterbauKetteTest._art(e) for e in ergebnis["elemente"]],
            ["chip", "und", "(", "chip", "oder", "chip", ")"],
        )

    def test_reine_und_kette_ohne_klammern(self):
        from intern.filterbau_titel import TITEL

        ergebnis = TITEL.kette(
            self._b(("und", "hymne", "ja", ""), ("und", "tempo", "ist", "s")),
            self.rf.get("/intern/titel/"),
        )
        self.assertEqual(
            [FilterbauKetteTest._art(e) for e in ergebnis["elemente"]],
            ["chip", "und", "chip"],
        )


class FilterbauTitelTest(SimpleTestCase):
    """Das Register des Repertoires: Q-Bauer je Feldart und die alten Parameter."""

    def _q(self, feld, operator, *werte):
        from intern.filterbau_titel import FELDER

        return FELDER[feld].q(operator, tuple(werte))

    def _sql(self, feld, operator, *werte):
        from intern.models import Lied

        return str(Lied.objects.all().filter(self._q(feld, operator, *werte)).query)

    def _lesen(self, query):
        from django.http import QueryDict

        from intern.filterbau_titel import TITEL

        return [
            (b.feld, b.operator, b.werte)
            for b in TITEL.lese_bedingungen(QueryDict(query))
        ]

    def test_schalter_auf_boolean(self):
        self.assertEqual(self._q("hymne", "ja"), Q(hymne=True))
        self.assertEqual(self._q("hymne", "nein"), Q(hymne=False))

    def test_datei_vorhanden_oder_nicht(self):
        # Rollenzeile per EXISTS, ohne Join und ohne die alten Lied-Felder.
        sql_ja = self._sql("aufnahme", "ja")
        self.assertIn("EXISTS", sql_ja)
        self.assertIn("intern_lieddatei", sql_ja)
        self.assertIn("aufnahme", sql_ja)
        sql_nein = self._sql("pdf", "nein")
        self.assertIn("NOT (EXISTS", sql_nein)
        self.assertNotIn('"intern_lied"."pdf', sql_nein)

    def test_tempo(self):
        self.assertEqual(self._q("tempo", "ist", "s"), Q(tempo__in=("s",)))
        self.assertEqual(self._q("tempo", "ist-nicht", "s"), ~Q(tempo__in=("s",)))

    def test_solist_ist_exists_und_haengt_am_lied(self):
        # Wie die Gruppen der Mitgliederliste: eine verneinte Join-Bedingung pruefte
        # die Verknuepfungszeile statt des Lieds.
        sql = self._sql("solist", "in", "3")
        self.assertIn("EXISTS", sql)
        self.assertNotIn("NOT EXISTS", sql)
        self.assertIn("NOT EXISTS", self._sql("dirigent", "nicht-in", "3"))

    def test_kette_hymne_und_acapella_und_nicht_aufnahme(self):
        from intern.filterbau_titel import TITEL
        from intern.filterbau import Bedingung

        from intern.models import Lied

        q = TITEL.baue_q([
            Bedingung("und", "hymne", "ja", ()),
            Bedingung("und", "acapella", "ja", ()),
            Bedingung("und", "aufnahme", "nein", ()),
        ])
        sql = str(Lied.objects.all().filter(q).query)
        self.assertIn("hymne", sql)
        self.assertIn("acapella", sql)
        self.assertIn("NOT (EXISTS", sql)

    def test_kein_feld_traegt_ein_recht(self):
        from intern.filterbau_titel import FELDER, TITEL

        self.assertEqual(TITEL.erlaubte_felder(False), frozenset(FELDER))

    def test_alte_parameter(self):
        self.assertEqual(
            self._lesen("titel=bach&sheet=true&notensatz=false&original=1"),
            [
                ("original", "ja", ()),
                ("pdf", "ja", ()),
                ("noten", "nein", ()),
                ("suche", "enthaelt", ("bach",)),
            ],
        )

    def test_alte_schalter_und_personen(self):
        self.assertEqual(
            self._lesen("hymne=false&tempo=s&solist=3&solist=4"),
            [
                ("hymne", "nein", ()),
                ("tempo", "ist", ("s",)),
                ("solist", "in", ("3", "4")),
            ],
        )

    def test_egal_und_konzert_ergeben_nichts(self):
        # „unknown" war die Mitte des alten Schalters; das Konzert steht neben der
        # Kette und wird in der Ansicht angewandt.
        self.assertEqual(self._lesen("aktiv=unknown&konzert=7"), [])


class AblageKetteTest(SimpleTestCase):
    """dateiablage.kette_bilden: nach „Geändert" sortiert, vorne die jüngste,
    von identischen Fassungen bleibt die älteste."""

    def _f(self, pfad, sha1, tag):
        from intern.dateiablage import Fassung
        return Fassung(pfad, sha1, datetime(2026, 1, tag), 1, "", "a.pdf", None)

    def _bilden(self, ziel, eingehend, jetzt=None):
        from intern.dateiablage import kette_bilden
        aktuell, versionen, weg = kette_bilden(ziel, eingehend, jetzt)
        return aktuell.pfad, [v.pfad for v in versionen], weg

    def setUp(self):
        self.jetzt = datetime(2026, 10, 1)
        self.ziel = [self._f("z", "Z", 10), self._f("z1", "Z1", 2)]

    def test_juengere_eingehende_steht_vorne(self):
        ein = [self._f("e", "E", 20), self._f("e1", "E1", 1)]
        self.assertEqual(self._bilden(self.ziel, ein), ("e", ["e1", "z1", "z"], []))

    def test_aeltere_eingehende_wird_einsortiert(self):
        ein = [self._f("e", "E", 5)]
        self.assertEqual(self._bilden(self.ziel, ein), ("z", ["z1", "e"], []))

    def test_datum_auf_jetzt_holt_sie_nach_vorne(self):
        from intern.dateiablage import kette_bilden
        aktuell, versionen, _ = kette_bilden(self.ziel, [self._f("e", "E", 5)], self.jetzt)
        self.assertEqual((aktuell.pfad, aktuell.datum), ("e", self.jetzt))
        self.assertEqual([v.pfad for v in versionen], ["z1", "z"])

    def test_von_identischen_bleibt_die_aelteste(self):
        """Die jüngere identische Fassung verschwindet — auch wenn sie vorne stand."""
        ein = [self._f("e", "Z1", 20)]
        self.assertEqual(self._bilden(self.ziel, ein), ("z", ["z1"], ["e"]))

    def test_identische_versionen_die_juengere_geht(self):
        ziel = [self._f("z", "Z", 10), self._f("z2", "A", 4), self._f("z1", "A", 2)]
        self.assertEqual(self._bilden(ziel, []), ("z", ["z1"], ["z2"]))

    def test_vorne_identisch_mit_aelterer_version(self):
        """Die vordere Fassung gleicht einer älteren: die ältere bleibt, vorne
        steht danach die jüngste übrige."""
        ziel = [self._f("z", "A", 10), self._f("y", "Y", 5), self._f("a", "A", 1)]
        self.assertEqual(self._bilden(ziel, []), ("y", ["a"], ["z"]))

    def test_wiederherstellen(self):
        """Die Version steckt schon in der Kette (gleicher Pfad); mit „jetzt"
        steht sie vorne, die bisherige vordere geht in die Historie."""
        from intern.dateiablage import kette_bilden
        aktuell, versionen, weg = kette_bilden(self.ziel, [self.ziel[1]], self.jetzt)
        self.assertEqual((aktuell.pfad, aktuell.datum), ("z1", self.jetzt))
        self.assertEqual(([v.pfad for v in versionen], weg), (["z"], []))

    def test_gleichstand_eingehend_vorne_aelteste_aus_dem_ziel(self):
        ein = [self._f("e", "E", 10)]
        self.assertEqual(self._bilden(self.ziel, ein)[0], "e")
        ein = [self._f("e", "Z1", 2)]
        self.assertEqual(self._bilden(self.ziel, ein), ("z", ["z1"], ["e"]))

    def test_leerer_sha1_ist_nie_doppelt(self):
        ziel = [self._f("z", "", 10)]
        ein = [self._f("e", "", 5)]
        self.assertEqual(self._bilden(ziel, ein), ("z", ["e"], []))


class AblageEntscheidungTest(SimpleTestCase):
    """Konfliktart, Wahl und Vorrang — ohne Wahl wird übersprungen."""

    def test_konfliktarten(self):
        from intern.dateiablage import konflikt_art
        alt, neu = datetime(2026, 1, 1), datetime(2026, 2, 1)
        self.assertEqual(konflikt_art({"A", "B"}, "B", neu, alt), "identisch")
        self.assertEqual(konflikt_art({"A"}, "C", alt, neu), "name")
        self.assertEqual(konflikt_art({"A"}, "C", neu, alt), "name_aelter")
        self.assertEqual(konflikt_art({"A"}, "", alt, neu), "name")

    def test_entscheidungen_lesen_verwirft_unbekanntes(self):
        from intern.dateiablage import entscheidungen_lesen
        self.assertEqual(
            entscheidungen_lesen(["File:1@2=verschmelzen", "File:3@0=quatsch", "kaputt", ""]),
            {"File:1@2": "verschmelzen"},
        )

    def test_wahl_muss_zur_art_passen(self):
        from intern.dateiablage import wahl
        self.assertEqual(wahl("verschieben", "identisch", "loeschen"), "loeschen")
        self.assertIsNone(wahl("verknuepfen", "identisch", "loeschen"))
        self.assertIsNone(wahl("verschieben", "name", None))
        self.assertIsNone(wahl("verschieben", "name", "abbrechen"))
        self.assertIsNone(wahl("kopieren", "name", "verschmelzen"))

    def test_jede_option_hat_eine_wirkung(self):
        from intern.dateiablage import OPTIONEN
        bekannt = {"verschmelzen", "jetzt", "einsortieren", "loeschen"}
        for schluessel, werte in OPTIONEN.items():
            self.assertTrue(set(werte) <= bekannt, schluessel)

    def test_name_frei_ohne_gross_klein(self):
        from intern.dateiablage import name_frei
        self.assertFalse(name_frei(["Noten", "Audio"], "noten"))
        self.assertFalse(name_frei(["Noten "], " NOTEN"))
        self.assertTrue(name_frei(["Noten"], "Noten 2"))
        self.assertTrue(name_frei([], "Noten"))


class DateiVerweiseTest(SimpleTestCase):
    """Warnung und Umhängen lesen dieselben Tabellen — und die kennen jeden FK
    und jedes M2M eines intern-Modells auf filer.File (außer dem Suchindex,
    der mit der Zeile geht)."""

    def test_tabelle_deckt_alle_fks(self):
        from django.apps import apps
        from filer.models import File

        from intern.models import DateiIndex
        from intern.verwendung import DATEI_M2M_VERWEISE, DATEI_PK_VERWEISE

        verweise = [
            (modell, feld)
            for modell in apps.get_app_config("intern").get_models()
            for feld in modell._meta.get_fields()
            # Ein M2M ist nicht concrete (seine Spalten liegen in der
            # Zwischentabelle); auto_created schließt die Rückrichtungen aus.
            if (getattr(feld, "concrete", False)
                or (feld.many_to_many and not feld.auto_created))
            and isinstance(getattr(feld, "related_model", None), type)
            and issubclass(feld.related_model, File)
            and modell is not DateiIndex
        ]
        self.assertEqual(
            set(DATEI_PK_VERWEISE),
            {(m, f.name) for m, f in verweise if not f.many_to_many},
        )
        self.assertEqual(
            set(DATEI_M2M_VERWEISE),
            {(m, f.name) for m, f in verweise if f.many_to_many},
        )

    def test_versionsdatum_ist_setzbar(self):
        """Der Stand einer Fassung wird gesetzt, nicht beim Anlegen überschrieben."""
        from intern.models import DateiVersion
        feld = DateiVersion._meta.get_field("datum")
        self.assertFalse(feld.auto_now_add)
        self.assertFalse(feld.auto_now)

    def test_lied_ordner_zeigt_auf_filer_ordner(self):
        """Die Ordner-Achse: `Lied.ordner` hängt an filer.Folder und wird von
        der Prüfung gegen filer.File nicht erfasst."""
        from django.db.models import SET_NULL
        from filer.models import Folder

        from intern.models import Lied

        feld = Lied._meta.get_field("ordner")
        self.assertIs(feld.related_model, Folder)
        self.assertTrue(feld.null)
        self.assertEqual(feld.remote_field.on_delete, SET_NULL)

    def test_lieddatei_ist_eine_datei_je_rolle(self):
        from intern.models import LiedDatei

        self.assertEqual(LiedDatei._meta.unique_together, (("lied", "rolle"),))


class LiedrollenTest(SimpleTestCase):
    """Das Register der Lied-Rollen ist vollständig und eindeutig — die eine
    Quelle, aus der Modell, Tabelle, Filter und Audit-Labels lesen."""

    def test_schluessel_sind_eindeutig(self):
        from intern import liedrollen

        self.assertEqual(len(liedrollen.SCHLUESSEL), len(set(liedrollen.SCHLUESSEL)))

    def test_jede_rolle_hat_label_und_endungen(self):
        from intern import liedrollen

        for rolle in liedrollen.ROLLEN:
            self.assertTrue(rolle.key)
            self.assertTrue(rolle.label)
            self.assertTrue(rolle.endungen)
            self.assertTrue(all(e.startswith(".") and e == e.lower() for e in rolle.endungen))

    def test_labels_decken_das_register(self):
        from intern import liedrollen

        self.assertEqual(set(liedrollen.LABELS), set(liedrollen.SCHLUESSEL))

    def test_rolle_fuer_endung(self):
        from intern import liedrollen

        self.assertEqual(liedrollen.rolle_fuer_endung(".pdf"), "notenblatt")
        self.assertEqual(liedrollen.rolle_fuer_endung("PDF"), "notenblatt")
        self.assertEqual(liedrollen.rolle_fuer_endung(".mscz"), "notensatz")
        self.assertEqual(liedrollen.rolle_fuer_endung(".mp3"), "original")
        self.assertEqual(liedrollen.rolle_fuer_endung(".odt"), "text")
        self.assertIsNone(liedrollen.rolle_fuer_endung(".docx"))
        self.assertIsNone(liedrollen.rolle_fuer_endung(""))

    def test_label_kennt_die_beschriftungen(self):
        from intern import liedrollen

        self.assertEqual(liedrollen.label("notenblatt"), "Notenblatt")
        self.assertEqual(liedrollen.label("text"), "Liedtext")
        self.assertEqual(liedrollen.label("unbekannt"), "unbekannt")


class LiedablageTest(SimpleTestCase):
    """Die reine Namenslogik des Lied-Ordners — ohne Datenbank prüfbar."""

    def test_ordnername_entschaerft(self):
        from intern import liedablage

        self.assertEqual(liedablage.ordnername("A/B"), "A-B")
        self.assertEqual(liedablage.ordnername("A\\B"), "A-B")
        self.assertEqual(liedablage.ordnername("  Titel  "), "Titel")
        self.assertEqual(liedablage.ordnername(""), "Ohne Titel")
        self.assertEqual(liedablage.ordnername("."), "Ohne Titel")
        self.assertEqual(liedablage.ordnername(".."), "Ohne Titel")

    def test_freier_name_in(self):
        from intern import liedablage

        self.assertEqual(liedablage.freier_name_in(set(), "Titel"), "Titel")
        self.assertEqual(liedablage.freier_name_in({"Titel"}, "Titel"), "Titel-1")
        self.assertEqual(
            liedablage.freier_name_in({"Titel", "Titel-1"}, "Titel"), "Titel-2"
        )

    def test_dateiname(self):
        from intern import liedablage

        self.assertEqual(
            liedablage.dateiname("Titel", "notenblatt", ".pdf"), "Titel – Notenblatt.pdf"
        )
        self.assertEqual(
            liedablage.dateiname("Titel", "text", ".odt"), "Titel – Liedtext.odt"
        )

    def test_endung_von(self):
        from intern import liedablage

        f = SimpleNamespace(original_filename="A.PDF", name="x")
        self.assertEqual(liedablage.endung_von(f), ".pdf")
        self.assertEqual(
            liedablage.endung_von(SimpleNamespace(original_filename="", name="x.m4a")),
            ".m4a",
        )


class LiedordnerSchutzTest(SimpleTestCase):
    """Der Ordner eines Liedes wird nur über das Lied umbenannt, verschoben
    oder gelöscht — die Guards stehen in allen drei Wegen."""

    def test_guards_stehen_in_den_drei_views(self):
        import inspect

        from intern.views import folders

        for name in ("folder_move", "folder_delete", "folder_rename"):
            self.assertIn(
                "_enthaelt_liedordner(folder.pk)",
                inspect.getsource(getattr(folders, name)),
                name,
            )

    def test_auswahllisten_koennen_liedordner_auslassen(self):
        import inspect

        from intern.views import folders

        self.assertIn("ohne_liedordner", inspect.signature(folders._build_folder_flat).parameters)
        self.assertIn("ohne_liedordner=True", inspect.getsource(__import__(
            "intern.views.files", fromlist=["datei_aktionen"]
        ).datei_aktionen))


class RollenzeileVerschmelzenTest(SimpleTestCase):
    """Das Verschmelzen zweier Dateien hängt die Rollenzeile um; ohne den
    Eintrag in DATEI_PK_VERWEISE nähme das Queryset-Delete die Zeile per
    CASCADE mit. Ohne Datenbank bleibt das ein Pin am Mechanismus."""

    def test_verweise_umhaengen_liest_das_register(self):
        import inspect

        from intern import dateiablage
        from intern.models import LiedDatei
        from intern.verwendung import DATEI_PK_VERWEISE, verweise_umhaengen

        self.assertIn((LiedDatei, "datei"), DATEI_PK_VERWEISE)
        self.assertIn("verweise_umhaengen", inspect.getsource(dateiablage.zusammenfuehren))
        self.assertIn("DATEI_PK_VERWEISE", inspect.getsource(verweise_umhaengen))


class OrdnerZyklusTest(SimpleTestCase):
    """Ein Ordner darf nicht in sich selbst oder einen eigenen Unterordner —
    der Zweig hinge sonst an sich selbst und fiele aus dem Baum."""

    # 1 ─ 2 ─ 3, daneben 4
    ELTERN = {1: None, 2: 1, 3: 2, 4: None}

    def _pruefen(self, kandidat, vorfahr):
        from intern.views import folders

        class Abfrage:
            def get(_self, pk):
                if pk not in self.ELTERN:
                    raise folders.Folder.DoesNotExist
                return self.ELTERN[pk]

        with mock.patch.object(folders.Folder, "objects") as objects:
            objects.values_list.return_value = Abfrage()
            return folders._is_descendant_or_self(kandidat, vorfahr)

    def test_eigener_zweig(self):
        self.assertTrue(self._pruefen(1, 1))
        self.assertTrue(self._pruefen(3, 1))
        self.assertTrue(self._pruefen(2, 2))

    def test_fremder_zweig_und_wurzel(self):
        self.assertFalse(self._pruefen(4, 1))
        self.assertFalse(self._pruefen(1, 3))
        self.assertFalse(self._pruefen(None, 1))

    def test_verschieben_und_vorabpruefung_fragen_danach(self):
        import inspect

        from intern.views import folders
        for view in (folders.folder_move, folders.ablage_konflikte):
            self.assertIn("_is_descendant_or_self(target_id", inspect.getsource(view), view.__name__)



class BackstageZielTest(SimpleTestCase):
    """Backstage und alles darunter ist kein Ziel von Verschieben, Referenz und
    Kopieren — weder in der Auswahl noch auf dem Server. Ausgenommen ist, wer
    Backstage sieht (Webmaster)."""

    # 1 Backstage ─ 2 Repertoire, daneben 3 Verein
    ORDNER = [
        {"id": 1, "name": "Backstage", "parent_id": None},
        {"id": 2, "name": "Repertoire", "parent_id": 1},
        {"id": 3, "name": "Verein", "parent_id": None},
    ]

    def _ids(self, **kwargs):
        from intern.views import folders

        with mock.patch.object(folders.Folder, "objects") as objects, \
                mock.patch.object(folders, "_backstage_zweig", return_value={1, 2}):
            objects.order_by.return_value.values.return_value = list(self.ORDNER)
            return [e["id"] for e in folders._build_folder_flat(**kwargs)]

    def test_auswahl_ohne_backstage(self):
        self.assertEqual(self._ids(ohne_backstage=True), [3])

    def test_pfade_der_suche_behalten_backstage(self):
        self.assertEqual(self._ids(), [1, 2, 3])

    def test_ziel_views_lehnen_ab(self):
        import inspect

        from intern.views import files, folders
        for view in (folders.folder_move, folders._copy_action):
            self.assertIn(
                "target_id in _gesperrte_ziele(request.user)", inspect.getsource(view), view.__name__
            )
        for view in (folders.folder_view, files.datei_aktionen):
            self.assertIn(
                "ohne_backstage=not _sieht_backstage(request.user)",
                inspect.getsource(view), view.__name__,
            )

    def test_webmaster_darf_nach_backstage(self):
        from intern.views import folders

        webmaster, mitglied = mock.Mock(), mock.Mock()
        webmaster.has_perm.side_effect = lambda p: p == "intern.manage_folder_permissions"
        mitglied.has_perm.return_value = False
        with mock.patch.object(folders, "_backstage_zweig", return_value={1, 2}):
            self.assertEqual(folders._gesperrte_ziele(webmaster), set())
            self.assertEqual(folders._gesperrte_ziele(mitglied), {1, 2})


class StandardordnerSchutzTest(SimpleTestCase):
    """Die Ordner aus PFADE — und wer einen von ihnen enthält — lassen sich im
    Portal weder umbenennen noch verschieben noch löschen, auch nicht als
    Superuser; sonst fände das Portal etwa die Profilbilder nicht mehr."""

    def test_enthaelt_standardordner(self):
        from intern.views import folders

        # 1 Verein ─ 2 Vorstand (Standard), 1 ─ 3 Chorverband (frei)
        unterordner = {1: {1, 2, 3}, 2: {2}, 3: {3}}
        with mock.patch.object(folders, "_descendant_folder_ids", side_effect=unterordner.get), \
                mock.patch.object(folders.folders, "standard_ids", return_value={1, 2}):
            self.assertTrue(folders._enthaelt_standardordner(1))
            self.assertTrue(folders._enthaelt_standardordner(2))
            self.assertFalse(folders._enthaelt_standardordner(3))

    def test_views_fragen_danach(self):
        import inspect

        from intern.views import folders
        for view in (folders.folder_move, folders.folder_delete):
            self.assertIn("_enthaelt_standardordner(folder.pk)", inspect.getsource(view), view.__name__)
        self.assertIn("folder.pk in folders.standard_ids()", inspect.getsource(folders.folder_rename))

    def test_profilbilder_entstehen_neu(self):
        """Fehlt Backstage/Profilbilder, legt `avatare()` den Pfad an — ein
        Profilbild landet nie im Wurzelordner."""
        from filer.models import Folder

        from intern import folders

        neu = iter([mock.Mock(pk=11), mock.Mock(pk=12)])
        with mock.patch.object(Folder, "objects") as objects, mock.patch.dict(folders._cache, clear=True):
            objects.filter.return_value.first.return_value = None
            objects.create.side_effect = lambda **kw: next(neu)
            self.assertEqual(folders.avatare(), 12)
            objects.create.assert_any_call(name=folders.BACKSTAGE, parent_id=None)
            objects.create.assert_any_call(name=folders.PROFILBILDER, parent_id=11)
            objects.filter.return_value.first.return_value = None
            folders._cache.clear()
            objects.create.reset_mock()
            self.assertIsNone(folders.mitgliedsantraege())
            objects.create.assert_not_called()


class WarteschlangenTest(SimpleTestCase):
    """Die Wiedergabelisten lesen die Rollenzeilen: welche Titel in welcher
    Liste landen, wie der Typ heißt und woher die URL kommt."""

    @staticmethod
    def _lied(pk, titel="Lied A", komponist="Komponist"):
        return SimpleNamespace(pk=pk, titel=titel, komponist=komponist)

    @staticmethod
    def _datei(pfad):
        return SimpleNamespace(file=SimpleNamespace(name=pfad))

    def _bauen(self, lieder, rollen, bezeichnung="Chor Aufnahme"):
        from intern.views.titel import _warteschlangen

        with mock.patch(
            "intern.views.titel.liedablage.rollen_fuer", return_value=rollen
        ), mock.patch(
            "intern.views.titel.get_aufnahme_bezeichnung", return_value=bezeichnung
        ):
            return _warteschlangen(lieder)

    def test_original_und_aufnahme(self):
        lied = self._lied(1)
        listen = self._bauen(
            [lied],
            {1: {"original": self._datei("filer_public/a.mp3"),
                 "aufnahme": self._datei("filer_public/b.mp3")}},
        )
        self.assertEqual([e["title"] for e in listen["originals"]], ["Lied A"])
        self.assertEqual([e["title"] for e in listen["aufnahmen"]], ["Lied A"])
        self.assertEqual(len(listen["all"]), 1)
        self.assertEqual(listen["originals"][0]["type"], "Original")
        self.assertEqual(listen["aufnahmen"][0]["type"], "Chor Aufnahme")
        self.assertEqual(listen["all"][0]["type"], "Original")

    def test_all_nimmt_original_vor_aufnahme(self):
        listen = self._bauen(
            [self._lied(1, komponist="")],
            {1: {"original": self._datei("filer_public/a.mp3"),
                 "aufnahme": self._datei("filer_public/b.mp3")}},
        )
        self.assertTrue(listen["all"][0]["url"].endswith("a.mp3"))

    def test_nur_aufnahme(self):
        listen = self._bauen(
            [self._lied(2, "Lied B", "")],
            {2: {"aufnahme": self._datei("filer_public/b.mp3")}},
        )
        self.assertEqual(listen["originals"], [])
        self.assertEqual(len(listen["aufnahmen"]), 1)
        self.assertEqual(listen["all"][0]["type"], "Chor Aufnahme")

    def test_ohne_datei_kein_eintrag(self):
        listen = self._bauen([self._lied(3, "Lied C", "")], {3: {}})
        self.assertEqual(listen, {"originals": [], "aufnahmen": [], "all": []})

    def test_komponist_fehlt_wird_leer(self):
        listen = self._bauen(
            [self._lied(4, "Lied D", None)], {4: {"original": self._datei("filer_public/d.mp3")}}
        )
        self.assertEqual(listen["originals"][0]["composer"], "")

    def test_url_kommt_aus_dem_speicherpfad(self):
        listen = self._bauen(
            [self._lied(5, "Lied E", "")], {5: {"original": self._datei("filer_public/e.mp3")}}
        )
        self.assertTrue(listen["originals"][0]["url"].endswith("filer_public/e.mp3"))

    def test_zaehlen(self):
        from intern.views.titel import _warteschlangen_zaehlen

        lieder = [self._lied(1), self._lied(2), self._lied(3)]
        rollen = {
            1: {"original": self._datei("a"), "aufnahme": self._datei("b")},
            2: {"aufnahme": self._datei("c")},
            3: {},
        }
        with mock.patch("intern.views.titel.liedablage.rollen_fuer", return_value=rollen):
            zaehler = _warteschlangen_zaehlen(lieder)
        self.assertEqual(zaehler, {"originals": 1, "aufnahmen": 2, "all": 2})


class RepertoireTabelleRollenTest(SimpleTestCase):
    """Die drei Datei-Renderer der Liederliste lesen die Rollen der Zeile."""

    @staticmethod
    def _datei(pfad):
        return SimpleNamespace(file=SimpleNamespace(name=pfad))

    def _tabelle(self):
        from intern.tables import RepertoireTabelle

        return RepertoireTabelle([])

    def test_pdf_ohne_rolle_leer(self):
        record = SimpleNamespace(rollen={}, titel="A")
        self.assertEqual(self._tabelle().render_pdf(record), "")

    def test_pdf_verlinkt(self):
        record = SimpleNamespace(rollen={"notenblatt": self._datei("filer_public/n.pdf")}, titel="A")
        html = str(self._tabelle().render_pdf(record))
        self.assertIn("file-icon-btn--pdf", html)
        self.assertIn("filer_public/n.pdf", html)
        self.assertIn("Notenblatt: A", html)

    def test_noten_verlinkt(self):
        record = SimpleNamespace(rollen={"notensatz": self._datei("filer_public/n.mscz")}, titel="A")
        html = str(self._tabelle().render_noten(record))
        self.assertIn("file-icon-btn--notes", html)
        self.assertIn("filer_public/n.mscz", html)
        self.assertIn("Notensatz: A", html)

    def test_text_verlinkt(self):
        record = SimpleNamespace(rollen={"text": self._datei("filer_public/t.odt")}, titel="A")
        html = str(self._tabelle().render_text(record))
        self.assertIn("filer_public/t.odt", html)
        self.assertIn("Liedtext: A", html)

    def test_original_und_aufnahme(self):
        record = SimpleNamespace(
            id=7,
            titel="A",
            komponist="K",
            rollen={
                "original": self._datei("filer_public/a.mp3"),
                "aufnahme": self._datei("filer_public/b.mp3"),
            },
        )
        with mock.patch("intern.tables.get_vereinsname_kurz", return_value="Chor"), \
                mock.patch("intern.tables.startseite_datei", return_value="/logo.svg"):
            html = str(self._tabelle().render_original(record))
        self.assertIn("audio-btn--original", html)
        self.assertIn("audio-btn--jg", html)
        self.assertIn('data-song-id="7"', html)
        self.assertIn('data-song-id="r7"', html)
        self.assertIn("filer_public/a.mp3", html)
        self.assertIn("filer_public/b.mp3", html)

    def test_original_ohne_rollen_leer(self):
        record = SimpleNamespace(id=7, titel="A", komponist="", rollen={})
        self.assertEqual(self._tabelle().render_original(record), "")

    def test_row_attrs_liefern_die_vier_urls(self):
        from intern.tables import RepertoireTabelle

        record = SimpleNamespace(
            id=7, titel="A", komponist="",
            rollen={
                "original": self._datei("filer_public/a.mp3"),
                "notenblatt": self._datei("filer_public/n.pdf"),
            },
        )
        attrs = RepertoireTabelle.Meta.row_attrs
        self.assertTrue(attrs["data-original-url"](record).endswith("filer_public/a.mp3"))
        self.assertEqual(attrs["data-aufnahme-url"](record), "")
        self.assertTrue(attrs["data-pdf-url"](record).endswith("filer_public/n.pdf"))
        self.assertEqual(attrs["data-noten-url"](record), "")


class KonzertExportTest(SimpleTestCase):
    """Charakterisierung der ZIP-Namen der beiden Konzert-Downloads."""

    class _Konzerte:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, **kwargs):
            return self

        def select_related(self, *args):
            return self

        def order_by(self, *args):
            return self

        def __iter__(self):
            return iter(self._rows)

    def _request(self):
        from django.test import RequestFactory

        request = RequestFactory().get("/x")
        request.user = mock.Mock(is_authenticated=True)
        return request

    def _antwort_lesen(self, antwort):
        import io
        import zipfile

        inhalt = b"".join(antwort.streaming_content)
        return zipfile.ZipFile(io.BytesIO(inhalt))

    def test_pdf_zip_namen(self):
        import tempfile

        from intern.views import termine

        with tempfile.TemporaryDirectory() as d:
            pfad = os.path.join(d, "x.pdf")
            with open(pfad, "wb") as f:
                f.write(b"%PDF")
            k = SimpleNamespace(position=1, lied=SimpleNamespace(titel="Titel"))
            with mock.patch(
                "intern.views.termine.get_object_or_404",
                return_value=SimpleNamespace(kurz="Konzert"),
            ), mock.patch("intern.views.termine.Konzert.objects", self._Konzerte([k])), \
                    mock.patch(
                        "intern.views.termine.liedablage.datei_fuer",
                        return_value=SimpleNamespace(file=SimpleNamespace(path=pfad)),
                    ):
                antwort = termine.konzert_pdf_zip(self._request(), 1)
            with self._antwort_lesen(antwort) as zf:
                self.assertEqual(zf.namelist(), ["01 Titel.pdf"])

    def test_noten_zip_namen(self):
        import tempfile

        from intern.views import termine

        with tempfile.TemporaryDirectory() as d:
            pfad = os.path.join(d, "x.mscz")
            with open(pfad, "wb") as f:
                f.write(b"x")
            k = SimpleNamespace(position=2, lied=SimpleNamespace(titel="Zweites"))
            with mock.patch(
                "intern.views.termine.get_object_or_404",
                return_value=SimpleNamespace(kurz="Konzert"),
            ), mock.patch("intern.views.termine.Konzert.objects", self._Konzerte([k])), \
                    mock.patch(
                        "intern.views.termine.liedablage.datei_fuer",
                        return_value=SimpleNamespace(file=SimpleNamespace(path=pfad)),
                    ):
                antwort = termine.konzert_noten_zip(self._request(), 1)
            with self._antwort_lesen(antwort) as zf:
                self.assertEqual(zf.namelist(), ["02 Zweites.mscz"])

    def test_ohne_datei_leeres_zip(self):
        from intern.views import termine

        k = SimpleNamespace(position=1, lied=SimpleNamespace(titel="Titel"))
        with mock.patch(
            "intern.views.termine.get_object_or_404",
            return_value=SimpleNamespace(kurz="Konzert"),
        ), mock.patch("intern.views.termine.Konzert.objects", self._Konzerte([k])), \
                mock.patch(
                    "intern.views.termine.liedablage.datei_fuer", return_value=None
                ):
            antwort = termine.konzert_pdf_zip(self._request(), 1)
        with self._antwort_lesen(antwort) as zf:
            self.assertEqual(zf.namelist(), [])


class TitelSchreibpfadTest(SimpleTestCase):
    """Charakterisierung der Titel-Schreibpfade: wann das Lied gespeichert bzw.
    gelöscht wird. Die Dateien hängen an der Rollenzeile, nicht mehr am Lied —
    abgelegt wird über ``liedablage`` (siehe dort)."""

    def _post(self, view, daten):
        from django.test import RequestFactory

        request = RequestFactory().post("/intern/titel/", daten)
        request.user = mock.Mock(is_authenticated=True)
        return request

    def test_titel_delete_loescht_wenn_frei(self):
        from intern.views import titel

        lied = mock.Mock(ordner_id=None)
        lied.konzert_set.exists.return_value = False
        lied.solist.exists.return_value = False
        lied.dirigent.exists.return_value = False
        with mock.patch.object(titel, "get_object_or_404", return_value=lied), \
                mock.patch.object(titel, "redirect") as weiter:
            titel.titel_delete(self._post(titel.titel_delete, {}), 1)
        lied.delete.assert_called_once()
        self.assertEqual(weiter.call_args.args[0], "titel_list")

    def test_titel_delete_verweigert_bei_verwendung(self):
        from intern.views import titel

        lied = mock.Mock()
        lied.konzert_set.exists.return_value = True
        with mock.patch.object(titel, "get_object_or_404", return_value=lied), \
                mock.patch.object(titel, "redirect") as weiter:
            titel.titel_delete(self._post(titel.titel_delete, {}), 1)
        lied.delete.assert_not_called()
        self.assertEqual(weiter.call_args.args[0], "titel_edit")


class MedienTest(SimpleTestCase):
    """Die Medien-Karte zeigt die Rollen zuerst, dann die rollenlosen Dateien."""

    def test_rollen_zuerst_ohne_doppelte(self):
        from intern.views import titel as titel_mod

        lied = SimpleNamespace(pk=1, id=1, ordner_id=5)
        rollen = {
            "original": SimpleNamespace(pk=10, url="/media/a.mp3"),
            "text": SimpleNamespace(pk=11, url="/media/t.odt"),
        }
        dateien = [
            SimpleNamespace(pk=12, url="/media/x.pdf", original_filename="x.pdf", name="x.pdf"),
            SimpleNamespace(pk=10, url="/media/a.mp3", original_filename="a.mp3", name="a.mp3"),
        ]
        with mock.patch.object(titel_mod.liedablage, "rollen_von", return_value=rollen), \
                mock.patch.object(titel_mod.liedablage, "dateien_im_ordner", return_value=dateien), \
                mock.patch.object(titel_mod, "get_aufnahme_bezeichnung", return_value="Chor-Aufnahme"):
            medien = titel_mod._medien(lied)
        self.assertEqual([m["rolle"] for m in medien], ["original", "text", ""])
        self.assertEqual(medien[-1]["label"], "x.pdf")
        self.assertTrue(medien[-1]["ohne_rolle"])


class TitelRolleTest(SimpleTestCase):
    """Die Medien-Karte der Bearbeiten-Seite vergibt die Rolle je Lied einmal."""

    def _post(self, daten):
        from django.test import RequestFactory

        request = RequestFactory().post("/intern/titel/1/rolle/", daten)
        request.user = mock.Mock(is_authenticated=True)
        return request

    def _aufruf(self, daten, datei=None):
        from intern.views import titel

        lied = SimpleNamespace(pk=1, ordner_id=5)
        datei = datei if datei is not None else SimpleNamespace(pk=3, folder_id=5)
        with mock.patch.object(titel, "get_object_or_404", return_value=lied), \
                mock.patch.object(titel.File, "objects") as objekte, \
                mock.patch.object(titel.liedablage, "rolle_setzen") as setzen, \
                mock.patch.object(titel.liedablage, "rolle_entfernen") as entfernen:
            objekte.filter.return_value.first.return_value = datei
            antwort = titel.titel_rolle(self._post(daten), 1)
        return antwort, setzen, entfernen

    def test_rolle_setzen(self):
        antwort, setzen, entfernen = self._aufruf({"datei": "3", "rolle": "notenblatt"})
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(setzen.call_args.args[1], "notenblatt")
        self.assertFalse(entfernen.called)

    def test_rolle_loesen(self):
        antwort, setzen, entfernen = self._aufruf({"datei": "3", "rolle": ""})
        self.assertEqual(antwort.status_code, 200)
        self.assertTrue(entfernen.called)

    def test_unbekannte_rolle_abgelehnt(self):
        antwort, setzen, _ = self._aufruf({"datei": "3", "rolle": "quatsch"})
        self.assertEqual(antwort.status_code, 400)
        self.assertFalse(setzen.called)

    def test_rolle_einer_datei_ausserhalb_des_ordners_loesbar(self):
        from intern.views import titel

        fremd = SimpleNamespace(pk=3, folder_id=99)
        with mock.patch.object(titel, "LiedDatei") as modell:
            modell.objects.filter.return_value.select_related.return_value.first.return_value = (
                SimpleNamespace(datei=fremd)
            )
            antwort, setzen, entfernen = self._aufruf({"datei": "3", "rolle": ""}, datei=fremd)
        self.assertEqual(antwort.status_code, 200)
        self.assertIs(entfernen.call_args.args[1], fremd)

    def test_datei_aus_fremdem_ordner_abgelehnt(self):
        antwort, setzen, _ = self._aufruf(
            {"datei": "3", "rolle": "text"},
            datei=SimpleNamespace(pk=3, folder_id=99),
        )
        self.assertEqual(antwort.status_code, 400)
        self.assertFalse(setzen.called)


class MedienDateienTest(SimpleTestCase):
    """Die Bearbeiten-Karte zeigt je Datei eine Zeile mit ihrem Dateinamen."""

    def test_je_datei_eine_zeile_mit_dateiname(self):
        from intern.views import titel as titel_mod

        a = SimpleNamespace(pk=10, url="/a", original_filename="Lied – Original.mp3", name="", folder_id=99)
        x = SimpleNamespace(pk=12, url="/x", original_filename="x.pdf", name="", folder_id=5)
        # Altbestand: eine Datei mit zwei Rollen bleibt eine Zeile.
        rollen = {"original": a, "aufnahme": a}
        with mock.patch.object(titel_mod.liedablage, "rollen_von", return_value=rollen), \
                mock.patch.object(titel_mod.liedablage, "dateien_im_ordner", return_value=[x, a]):
            zeilen = titel_mod._medien_dateien(SimpleNamespace(pk=1, ordner_id=5))
        self.assertEqual([z["datei_id"] for z in zeilen], [10, 12])
        self.assertEqual(zeilen[0]["dateiname"], "Lied – Original.mp3")
        self.assertEqual([r["key"] for r in zeilen[0]["rollen"]], ["original", "aufnahme"])
        self.assertEqual(zeilen[1]["rollen"], [])
        self.assertEqual([z["im_ordner"] for z in zeilen], [False, True])


class EineRolleJeDateiTest(SimpleTestCase):
    """Eine Datei trägt höchstens eine Rolle: setzen löst ihre andere."""

    def test_andere_rolle_der_datei_wird_frei(self):
        from intern import liedablage

        alte = mock.Mock()
        with mock.patch.object(liedablage, "LiedDatei") as modell, \
                mock.patch("intern.signals._log_change") as protokoll:
            modell.objects.filter.return_value.exclude.return_value = [alte]
            modell.objects.filter.return_value.first.return_value = None
            liedablage.rolle_setzen("lied", "text", SimpleNamespace(pk=3), nutzer="u")
        alte.delete.assert_called_once_with()
        protokoll.assert_called_once_with(alte, "u", "delete")
        modell.return_value.save.assert_called_once_with()


class TitelDateiTest(SimpleTestCase):
    """Umbenennen und Löschen in der Medien-Karte — nur im Lied-Ordner."""

    def _aufruf(self, daten, datei=None, umbenennen=("ok", []), avatar_ok=True):
        from django.test import RequestFactory

        from intern.views import titel

        request = RequestFactory().post("/intern/titel/1/datei/", daten)
        request.user = mock.Mock(is_authenticated=True)
        lied = SimpleNamespace(pk=1, ordner_id=5)
        datei = datei if datei is not None else SimpleNamespace(pk=3, folder_id=5)
        with mock.patch.object(titel, "get_object_or_404", return_value=lied), \
                mock.patch.object(titel.File, "objects") as objekte, \
                mock.patch.object(titel.liedablage, "rolle_entfernen") as entfernen, \
                mock.patch.object(titel.dateiablage, "datei_loeschen") as loeschen, \
                mock.patch.object(titel.dateiablage, "umbenennen", return_value=umbenennen) as umb, \
                mock.patch.object(titel.folders, "invalidate"), \
                mock.patch.object(titel, "darf_avatar_aendern", return_value=avatar_ok):
            objekte.filter.return_value.first.return_value = datei
            antwort = titel.titel_datei(request, 1)
        return antwort, entfernen, loeschen, umb

    def test_loeschen_loest_erst_die_rolle(self):
        antwort, entfernen, loeschen, _ = self._aufruf({"datei": "3", "aktion": "loeschen"})
        self.assertEqual(antwort.status_code, 200)
        self.assertTrue(entfernen.called)
        self.assertTrue(loeschen.called)

    def test_fremde_datei_abgelehnt(self):
        antwort, _, loeschen, _ = self._aufruf(
            {"datei": "3", "aktion": "loeschen"}, datei=SimpleNamespace(pk=3, folder_id=99)
        )
        self.assertEqual(antwort.status_code, 400)
        self.assertFalse(loeschen.called)

    def test_umbenennen(self):
        antwort, _, _, umb = self._aufruf({"datei": "3", "aktion": "umbenennen", "name": "neu.pdf"})
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(umb.call_args.args[1], "neu.pdf")

    def test_vergebener_name_wird_nicht_verschmolzen(self):
        antwort, _, _, umb = self._aufruf(
            {"datei": "3", "aktion": "umbenennen", "name": "x.pdf"}, umbenennen=("offen", ["k"])
        )
        self.assertEqual(antwort.status_code, 409)
        self.assertEqual(umb.call_args.args[3], {})

    def test_fremdes_profilbild_bleibt(self):
        from django.core.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            self._aufruf({"datei": "3", "aktion": "loeschen"}, avatar_ok=False)

    def test_ungueltiger_name(self):
        antwort, _, _, umb = self._aufruf({"datei": "3", "aktion": "umbenennen", "name": "a/b"})
        self.assertEqual(antwort.status_code, 400)
        self.assertFalse(umb.called)


class LiedUploadRechtTest(SimpleTestCase):
    """Ablegen auf einem Lied nur mit `change_lied` — Seite wie Server."""

    def test_liedseite_ohne_recht_ohne_ablage(self):
        from django.test import RequestFactory

        from intern.views import titel

        request = RequestFactory().get("/intern/titel/1/")
        request.user = mock.Mock(is_authenticated=True)
        request.user.has_perm.return_value = False
        with mock.patch.object(titel, "get_object_or_404", return_value=SimpleNamespace(titel="L", ordner_id=5)), \
                mock.patch.object(titel, "_medien", return_value=[]), \
                mock.patch.object(titel, "visible_folder_ids", return_value=set()), \
                mock.patch.object(titel, "render") as render:
            titel.titel_view(request, 1)
        kontext = render.call_args.args[2]
        self.assertNotIn("upload_content", kontext)
        self.assertNotIn("upload_lied_id", kontext)

    def test_liedseite_mit_recht_mit_ablage(self):
        from django.test import RequestFactory

        from intern.views import titel

        request = RequestFactory().get("/intern/titel/1/")
        request.user = mock.Mock(is_authenticated=True)
        request.user.has_perm.return_value = True
        with mock.patch.object(titel, "get_object_or_404", return_value=SimpleNamespace(titel="L", ordner_id=5)), \
                mock.patch.object(titel, "_medien", return_value=[]), \
                mock.patch.object(titel, "visible_folder_ids", return_value=set()), \
                mock.patch.object(titel, "render") as render:
            titel.titel_view(request, 1)
        kontext = render.call_args.args[2]
        self.assertTrue(kontext["upload_content"])
        self.assertEqual(kontext["upload_lied_id"], 1)

    def test_upload_mit_lied_ohne_recht_abgelehnt(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import RequestFactory

        from intern.views import files

        request = RequestFactory().post("/intern/upload/", {
            "file": SimpleUploadedFile("a.pdf", b"x", content_type="application/pdf"),
            "lied_id": "5",
        })
        request.user = mock.Mock(is_authenticated=True)
        request.user.has_perm.return_value = False
        with mock.patch("intern.app_settings.get_config_int", return_value=50), \
                mock.patch.object(files, "Lied") as lied_modell, \
                mock.patch.object(files.dateiablage, "hochladen") as hochladen:
            lied_modell.objects.filter.return_value.first.return_value = SimpleNamespace(pk=5)
            antwort = files.upload(request)
        self.assertEqual(antwort.status_code, 403)
        self.assertFalse(hochladen.called)


class ArtikelEditorAblageTest(SimpleTestCase):
    """Der Artikel-Editor hat eine kleine Ablage, aber keine Seiten-Dropzone."""

    def test_ziel_ohne_seitenzone(self):
        from django.test import RequestFactory

        from intern.views import artikel

        request = RequestFactory().get("/intern/artikel/X/edit/")
        request.user = mock.Mock(is_authenticated=True)
        with mock.patch.object(artikel, "Artikel") as modell, \
                mock.patch.object(artikel.folders, "artikel", return_value=7), \
                mock.patch.object(artikel, "render") as render:
            modell.objects.filter.return_value.order_by.return_value.first.return_value = None
            artikel.article_edit(request, "X")
        kontext = render.call_args.args[2]
        self.assertEqual(kontext["upload_folder_id"], 7)
        self.assertNotIn("upload_content", kontext)


class ProfilbildUploadTest(SimpleTestCase):
    """Ein Bild auf der eigenen Profilseite wird das Profilbild — nur ein Bild."""

    def _hochladen(self, content_type="image/png"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import RequestFactory

        from intern.views import files

        datei = mock.Mock(id=42, url="/media/a.png", original_filename="ich.png", file=mock.Mock())
        request = RequestFactory().post("/intern/upload/", {
            "file": SimpleUploadedFile("ich.png", b"x", content_type=content_type),
            "avatar": "1",
        })
        request.user = mock.Mock(is_authenticated=True, pk=7, avatar=None)
        with mock.patch("intern.app_settings.get_config_int", return_value=50), \
                mock.patch.object(files.folders, "avatare", return_value=9), \
                mock.patch.object(files, "Folder") as ordner, \
                mock.patch.object(files, "File") as datei_klasse, \
                mock.patch("intern.folder_access.folder_access", return_value=(True, True, False)), \
                mock.patch.object(files.dateiablage, "gleichnamige", return_value=None), \
                mock.patch.object(files.dateiablage, "freier_name", return_value="ich.png"), \
                mock.patch.object(files, "get_thumbnailer", side_effect=Exception), \
                mock.patch.object(
                    files.dateiablage, "hochladen", return_value=(datei, "neu", None)
                ) as hochladen, \
                mock.patch.object(files.dateiablage, "systemablage") as systemablage:
            systemablage.return_value = datei
            ordner.objects.filter.return_value.first.return_value = mock.Mock()
            datei_klasse.objects.filter.return_value.values_list.return_value = []
            antwort = files.upload(request)
        self.systemablage = systemablage
        return antwort, request.user, hochladen

    def test_bild_wird_profilbild(self):
        antwort, nutzer, hochladen = self._hochladen()
        self.assertEqual(antwort.status_code, 200)
        self.assertTrue(hochladen.called)
        self.assertIs(nutzer.avatar, self.systemablage.return_value)
        nutzer.save.assert_called_once_with(update_fields=["avatar"])

    def test_wird_fassung_des_bisherigen_bilds(self):
        # Unter <id><ext> wie in mitglied_edit — sonst bliebe das alte Bild verwaist.
        self._hochladen()
        self.assertEqual(self.systemablage.call_args.args[1:], (9, "7.png"))

    def test_kein_bild_abgelehnt(self):
        antwort, nutzer, hochladen = self._hochladen(content_type="application/pdf")
        self.assertEqual(antwort.status_code, 400)
        self.assertFalse(hochladen.called)
        nutzer.save.assert_not_called()


class WurzelUploadTest(SimpleTestCase):
    """Ohne Zielordner läge ein Upload auf oberster Ebene — das darf nur, wer
    Backstage sieht (Webmaster); alle anderen werden abgelehnt, bevor etwas
    abgelegt ist."""

    def _hochladen(self, webmaster):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import RequestFactory

        from intern.views import files

        request = RequestFactory().post("/intern/upload/", {"file": SimpleUploadedFile("x.txt", b"x")})
        request.user = mock.Mock(is_authenticated=True, is_superuser=False, pk=1)
        request.user.has_perm.side_effect = lambda p: webmaster and p == "intern.manage_folder_permissions"
        with mock.patch("intern.app_settings.get_config_int", return_value=50), \
                mock.patch("intern.folder_access.folder_access", return_value=(True, True, False)), \
                mock.patch.object(files.folders, "avatare", return_value=None), \
                mock.patch.object(files.dateiablage, "gleichnamige", return_value=None), \
                mock.patch.object(files.dateiablage, "hochladen", side_effect=RuntimeError) as hochladen:
            try:
                antwort = files.upload(request)
            except RuntimeError:
                antwort = None
        return antwort, hochladen.called

    def test_mitglied_abgelehnt(self):
        antwort, abgelegt = self._hochladen(webmaster=False)
        self.assertEqual(antwort.status_code, 403)
        self.assertFalse(abgelegt)

    def test_webmaster_darf(self):
        _, abgelegt = self._hochladen(webmaster=True)
        self.assertTrue(abgelegt)


class UploadZielTest(SimpleTestCase):
    """Eine Seiten-Dropzone gibt es nur auf den fünf Seiten, die ein Ziel nennen.

    Das ist die Invariante hinter „kein Upload ohne Ziel": Wer `upload_content`
    setzt, bekommt Fläche und Symbol; alle anderen Seiten keins. Ein neuer
    View, der es nebenbei setzt, fiele sonst niemandem auf."""

    ERLAUBT = {
        "intern.views.artikel.article_view",
        "intern.views.folders.folder_view",
        "intern.views.forums.forum_view",
        "intern.views.mitglieder.mitglied_view",
        "intern.views.titel.titel_view",
    }

    def test_nur_die_erlaubten_seiten_setzen_upload_content(self):
        import inspect

        from intern.views import artikel, folders, forums, mitglieder, termine, titel

        treffer = set()
        for modul in (artikel, folders, forums, mitglieder, termine, titel):
            for name, objekt in inspect.getmembers(modul, inspect.isfunction):
                if objekt.__module__ != modul.__name__:
                    continue
                if "upload_content" in inspect.getsource(objekt):
                    treffer.add(f"{modul.__name__}.{name}")
        self.assertEqual(treffer, self.ERLAUBT)


class FreierNameTest(SimpleTestCase):
    """Eine Feld-Dropzone legt im Zielordner ab, ohne eine gleichnamige Datei
    zu ihrer Fassung zu machen: sie nimmt den ersten freien Namen."""

    def test_frei_bleibt(self):
        from intern.dateiablage import freier_name
        self.assertEqual(freier_name(["a.pdf"], "b.pdf"), "b.pdf")

    def test_vergeben_zaehlt_hoch(self):
        from intern.dateiablage import freier_name
        self.assertEqual(freier_name(["Score.pdf"], "Score.pdf"), "Score (2).pdf")
        self.assertEqual(freier_name(["score.PDF", "Score (2).pdf"], "Score.pdf"), "Score (3).pdf")


# --- Ordnerrechte (folder_access.py) ---------------------------------------
#
# Ein Baum mit drei Ebenen unter „Organisation Chor“ und einem zweiten Ordner der
# obersten Ebene. Geprüft wird der reine Kern ``rechte()`` über die Kette, die
# auch ``folder_access()`` baut — ohne Datenbank.

_MITGLIED, _VORSTAND, _BAND = 1, 2, 3
_CHOR, _MITSCHNITTE, _JAHR, _VEREIN = 10, 11, 12, 20
_ELTERN = {_CHOR: None, _MITSCHNITTE: _CHOR, _JAHR: _MITSCHNITTE, _VEREIN: None}


def _regel(lesen=(), schreiben=(), loeschen=()):
    """Die Zeilen, die der Rechte-Editor für eine Einschränkung je Achse speichert."""
    return [
        (gid, gid in lesen, gid in schreiben, gid in loeschen)
        for gid in sorted(set(lesen) | set(schreiben) | set(loeschen))
    ]


class _OrdnerrechteBasis(SimpleTestCase):
    def rechte(self, ordner, gruppen, regeln=None, global_loeschen=False):
        from intern.folder_access import _kette, rechte

        kette = _kette(ordner, _ELTERN, regeln or {})
        return rechte(kette, gruppen, global_loeschen=global_loeschen)


class OrdnerrechteStandardTest(_OrdnerrechteBasis):
    """Ohne Regel: lesen und schreiben für jeden, löschen nur mit Recht."""

    def test_ohne_regel_lesen_und_schreiben(self):
        self.assertEqual(self.rechte(_MITSCHNITTE, {_MITGLIED}), (True, True, False))

    def test_ohne_gruppe_ebenso(self):
        self.assertEqual(self.rechte(_MITSCHNITTE, set()), (True, True, False))

    def test_globales_loeschrecht(self):
        self.assertEqual(
            self.rechte(_MITSCHNITTE, {_MITGLIED}, global_loeschen=True), (True, True, True)
        )

    def test_loeschregel_nennt_die_gruppe(self):
        regeln = {_MITSCHNITTE: _regel(loeschen={_MITGLIED})}
        self.assertEqual(self.rechte(_MITSCHNITTE, {_MITGLIED}, regeln), (True, True, True))


class OrdnerrechteLesenTest(_OrdnerrechteBasis):
    """„Lesen: Gruppen x, y“ — wer in keiner ist, sieht den Ordner nicht."""

    REGELN = {_MITSCHNITTE: _regel(lesen={_VORSTAND, _BAND})}

    def test_ausgeschlossen_sieht_nichts(self):
        self.assertEqual(
            self.rechte(_MITSCHNITTE, {_MITGLIED}, self.REGELN), (False, False, False)
        )

    def test_ausgeschlossen_loescht_auch_mit_globalem_recht_nicht(self):
        self.assertEqual(
            self.rechte(_MITSCHNITTE, {_MITGLIED}, self.REGELN, global_loeschen=True),
            (False, False, False),
        )

    def test_jede_genannte_gruppe_genuegt(self):
        self.assertEqual(self.rechte(_MITSCHNITTE, {_VORSTAND}, self.REGELN), (True, True, False))
        self.assertEqual(self.rechte(_MITSCHNITTE, {_BAND}, self.REGELN), (True, True, False))

    def test_eine_genannte_unter_mehreren_gruppen(self):
        self.assertTrue(self.rechte(_MITSCHNITTE, {_MITGLIED, _BAND}, self.REGELN)[0])

    def test_nachbarordner_unberuehrt(self):
        self.assertEqual(self.rechte(_VEREIN, {_MITGLIED}, self.REGELN), (True, True, False))
        self.assertEqual(self.rechte(_CHOR, {_MITGLIED}, self.REGELN), (True, True, False))


class OrdnerrechteSchreibenTest(_OrdnerrechteBasis):
    """„Schreiben: Gruppen x, y“ — Ausgeschlossene lesen weiter, schreiben nicht."""

    REGELN = {_MITSCHNITTE: _regel(schreiben={_VORSTAND})}

    def test_ausgeschlossen_liest_schreibt_nicht(self):
        self.assertEqual(
            self.rechte(_MITSCHNITTE, {_MITGLIED}, self.REGELN), (True, False, False)
        )

    def test_loeschen_unberuehrt(self):
        self.assertEqual(
            self.rechte(_MITSCHNITTE, {_MITGLIED}, self.REGELN, global_loeschen=True),
            (True, False, True),
        )

    def test_genannte_gruppe_schreibt(self):
        self.assertEqual(self.rechte(_MITSCHNITTE, {_VORSTAND}, self.REGELN), (True, True, False))


class OrdnerrechteLoeschenTest(_OrdnerrechteBasis):
    """„Löschen: Gruppen x, y“ — wie Schreiben, nur ist der Standard zu."""

    REGELN = {_MITSCHNITTE: _regel(loeschen={_VORSTAND})}

    def test_ausgeschlossen_merkt_nichts(self):
        self.assertEqual(self.rechte(_MITSCHNITTE, {_MITGLIED}, self.REGELN), (True, True, False))

    def test_ausgeschlossen_mit_globalem_recht(self):
        self.assertEqual(
            self.rechte(_MITSCHNITTE, {_MITGLIED}, self.REGELN, global_loeschen=True),
            (True, True, True),
        )

    def test_genannte_gruppe_loescht(self):
        self.assertEqual(self.rechte(_MITSCHNITTE, {_VORSTAND}, self.REGELN), (True, True, True))


class OrdnerrechteWurzelTest(_OrdnerrechteBasis):
    """Die oberste Ebene ist für alle lesbar und beschreibbar, nicht löschbar."""

    def test_wurzel(self):
        self.assertEqual(self.rechte(None, set()), (True, True, False))
        self.assertEqual(self.rechte(None, set(), global_loeschen=True), (True, True, True))

    def test_ordner_der_obersten_ebene_kann_verborgen_sein(self):
        regeln = {_VEREIN: _regel(lesen={_VORSTAND})}
        self.assertFalse(self.rechte(_VEREIN, {_MITGLIED}, regeln)[0])
        self.assertEqual(self.rechte(None, {_MITGLIED}, regeln), (True, True, False))


class OrdnerVererbungTest(_OrdnerrechteBasis):
    """Je Achse gilt die Regel des nächsten Ordners, der eine trägt."""

    def test_leseregel_verbirgt_den_zweig(self):
        regeln = {_CHOR: _regel(lesen={_VORSTAND})}
        for ordner in (_CHOR, _MITSCHNITTE, _JAHR):
            self.assertEqual(self.rechte(ordner, {_MITGLIED}, regeln), (False, False, False))
            self.assertTrue(self.rechte(ordner, {_VORSTAND}, regeln)[0])

    def test_schreibregel_erbt(self):
        regeln = {_CHOR: _regel(schreiben={_VORSTAND})}
        for ordner in (_MITSCHNITTE, _JAHR):
            self.assertEqual(self.rechte(ordner, {_MITGLIED}, regeln), (True, False, False))
            self.assertEqual(self.rechte(ordner, {_VORSTAND}, regeln), (True, True, False))

    def test_loeschregel_erbt(self):
        regeln = {_CHOR: _regel(loeschen={_BAND})}
        self.assertEqual(self.rechte(_JAHR, {_BAND}, regeln), (True, True, True))
        self.assertEqual(self.rechte(_JAHR, {_MITGLIED}, regeln), (True, True, False))

    def test_eigene_regel_ersetzt_die_geerbte(self):
        regeln = {
            _CHOR: _regel(schreiben={_VORSTAND}),
            _MITSCHNITTE: _regel(schreiben={_MITGLIED}),
        }
        self.assertFalse(self.rechte(_CHOR, {_MITGLIED}, regeln)[1])
        self.assertTrue(self.rechte(_MITSCHNITTE, {_MITGLIED}, regeln)[1])
        self.assertFalse(self.rechte(_MITSCHNITTE, {_VORSTAND}, regeln)[1])
        # Der Enkel erbt vom nächsten Vorfahren mit Regel, dem Kind.
        self.assertTrue(self.rechte(_JAHR, {_MITGLIED}, regeln)[1])

    def test_leseregel_erweitert_die_sichtbarkeit_nicht(self):
        regeln = {
            _CHOR: _regel(lesen={_VORSTAND}),
            _MITSCHNITTE: _regel(lesen={_MITGLIED, _VORSTAND}),
        }
        self.assertFalse(self.rechte(_MITSCHNITTE, {_MITGLIED}, regeln)[0])
        self.assertTrue(self.rechte(_MITSCHNITTE, {_VORSTAND}, regeln)[0])

    def test_leseregel_im_zweig_verengt(self):
        regeln = {_MITSCHNITTE: _regel(lesen={_BAND})}
        self.assertTrue(self.rechte(_CHOR, {_MITGLIED}, regeln)[0])
        self.assertFalse(self.rechte(_JAHR, {_MITGLIED}, regeln)[0])

    def test_regel_einer_achse_unterbricht_die_anderen_nicht(self):
        regeln = {
            _CHOR: _regel(schreiben={_VORSTAND}),
            _MITSCHNITTE: _regel(loeschen={_BAND}),
        }
        self.assertEqual(self.rechte(_JAHR, {_BAND}, regeln), (True, False, True))
        self.assertEqual(self.rechte(_JAHR, {_VORSTAND}, regeln), (True, True, False))

    def test_zeilen_ohne_flag_regeln_die_achse_nicht(self):
        # Eine Lese-Einschränkung speichert Zeilen mit can_write=False — Schreiben
        # bleibt trotzdem geerbt.
        regeln = {
            _CHOR: _regel(schreiben={_VORSTAND}),
            _MITSCHNITTE: _regel(lesen={_MITGLIED, _VORSTAND}),
        }
        self.assertEqual(self.rechte(_MITSCHNITTE, {_MITGLIED}, regeln), (True, False, False))
        self.assertEqual(self.rechte(_MITSCHNITTE, {_VORSTAND}, regeln), (True, True, False))

    def test_verschobener_ordner_erbt_am_neuen_platz(self):
        from intern.folder_access import _kette, rechte

        regeln = {_CHOR: _regel(schreiben={_VORSTAND})}
        eltern = {**_ELTERN, _MITSCHNITTE: _VEREIN}
        self.assertTrue(rechte(_kette(_MITSCHNITTE, eltern, regeln), {_MITGLIED})[1])
        self.assertTrue(rechte(_kette(_JAHR, eltern, regeln), {_MITGLIED})[1])


class SichtbareOrdnerTest(_OrdnerrechteBasis):
    def test_stimmt_mit_rechte_ueberein(self):
        from intern.folder_access import sichtbare_ordner

        regeln = {
            _CHOR: _regel(schreiben={_VORSTAND}),
            _MITSCHNITTE: _regel(lesen={_VORSTAND}),
            _VEREIN: _regel(loeschen={_BAND}),
        }
        for gruppen in ({_MITGLIED}, {_VORSTAND}, {_BAND}, set()):
            erwartet = {o for o in _ELTERN if self.rechte(o, gruppen, regeln)[0]}
            self.assertEqual(sichtbare_ordner(_ELTERN, regeln, gruppen), erwartet)
        self.assertEqual(sichtbare_ordner(_ELTERN, regeln, {_MITGLIED}), {_CHOR, _VEREIN})

    def test_zyklus_bricht_ab(self):
        from intern.folder_access import sichtbare_ordner

        self.assertEqual(sichtbare_ordner({1: 2, 2: 1}, {}, set()), {1, 2})


class FolderAccessTest(SimpleTestCase):
    """Die DB-Hälfte: Benutzerarten und das globale Löschrecht."""

    def _access(self, user, ordner_id, regeln=None):
        from intern import folder_access

        ordner = None if ordner_id is None else SimpleNamespace(pk=ordner_id)
        with mock.patch.object(
            folder_access, "_ordnerdaten", return_value=(_ELTERN, regeln or {})
        ), mock.patch.object(folder_access, "_gruppen", return_value={_MITGLIED}):
            return folder_access.folder_access(user, ordner)

    def _user(self, superuser=False, loeschrecht=False, angemeldet=True):
        return SimpleNamespace(
            is_authenticated=angemeldet,
            is_superuser=superuser,
            has_perm=lambda perm: loeschrecht and perm == "intern.delete_folder",
        )

    def test_nicht_angemeldet(self):
        self.assertEqual(self._access(self._user(angemeldet=False), None), (False, False, False))
        self.assertEqual(self._access(None, _CHOR), (False, False, False))

    def test_superuser_trotz_leseregel(self):
        regeln = {_CHOR: _regel(lesen={_VORSTAND})}
        self.assertEqual(self._access(self._user(superuser=True), _JAHR, regeln), (True, True, True))

    def test_globales_loeschrecht_wird_geprueft(self):
        self.assertEqual(self._access(self._user(), _CHOR), (True, True, False))
        self.assertEqual(self._access(self._user(loeschrecht=True), _CHOR), (True, True, True))
        self.assertEqual(self._access(self._user(loeschrecht=True), None), (True, True, True))
        self.assertEqual(self._access(self._user(), None), (True, True, False))

    def test_neue_ordner_bekommen_keine_kopierten_zeilen(self):
        import inspect

        from intern.views import folders
        self.assertNotIn("_apply_perm_specs", inspect.getsource(folders.folder_create))


class MigrationenVollstaendigTest(SimpleTestCase):
    """Jede Änderung an models.py braucht ihre eingecheckte Migration —
    start.sh wendet beim Start nur an, was unter intern/migrations/ liegt.

    Ohne Datenbank: der Graph kommt aus den Dateien (MigrationLoader mit
    connection=None), der Vergleich ist derselbe wie in makemigrations."""

    def test_keine_ausstehende_modellaenderung(self):
        from django.apps import apps
        from django.db.migrations.autodetector import MigrationAutodetector
        from django.db.migrations.loader import MigrationLoader
        from django.db.migrations.state import ProjectState
        from django.utils import translation

        # Wie makemigrations (@no_translations): sonst vergliche der Lauf die
        # deutschen verbose_names der Django-Apps mit den englischen der Dateien.
        with translation.override(None):
            loader = MigrationLoader(None, ignore_no_migrations=True)
            changes = MigrationAutodetector(
                loader.project_state(), ProjectState.from_apps(apps)
            ).changes(graph=loader.graph)
        self.assertNotIn(
            "intern", changes,
            "models.py weicht von den Migrationen ab — "
            "python manage.py makemigrations intern --name <name>",
        )


class EinrichtungTest(SimpleTestCase):
    """Die reinen Entscheidungen der Ersteinrichtung (``intern/einrichtung.py``)."""

    def test_nur_einrichtung_und_static_sind_frei(self):
        from intern.einrichtung import pfad_frei

        self.assertTrue(pfad_frei("/einrichtung/"))
        self.assertTrue(pfad_frei("/static/intern/css/intern.css"))
        for pfad in ("/", "/intern/", "/admin/", "/carddav/", "/intern/media-auth/"):
            with self.subTest(pfad=pfad):
                self.assertFalse(pfad_frei(pfad))

    def test_hosts_bis_zur_einrichtung_offen(self):
        from django.test import override_settings

        from intern.einrichtung import hosts_offen, hosts_oeffnen

        with override_settings(ALLOWED_HOSTS=["localhost"]):
            self.assertFalse(hosts_offen())
            hosts_oeffnen()
            self.assertTrue(hosts_offen())

    def test_hosts_festlegen_aus_der_portaladresse(self):
        from django.conf import settings
        from django.test import override_settings

        from intern.einrichtung import hosts_festlegen, hosts_offen

        with override_settings(ALLOWED_HOSTS=["*"], CSRF_TRUSTED_ORIGINS=[]):
            hosts_festlegen("https://chor.example.de")
            self.assertFalse(hosts_offen())
            self.assertIn("chor.example.de", settings.ALLOWED_HOSTS)
            self.assertIn("https://chor.example.de", settings.CSRF_TRUSTED_ORIGINS)

    def test_middleware_legt_hosts_nach_der_einrichtung_fest(self):
        from django.test import RequestFactory, override_settings

        from intern import middleware

        mw = middleware.Ersteinrichtung(lambda request: "weiter")
        anfrage = RequestFactory().get("/")
        with override_settings(ALLOWED_HOSTS=["*"]), \
                mock.patch.object(middleware, "ist_eingerichtet", return_value=True), \
                mock.patch.object(middleware, "hosts_festlegen") as festlegen:
            self.assertEqual(mw(anfrage), "weiter")
            festlegen.assert_called_once_with()

    def test_middleware_leitet_vor_der_einrichtung_um(self):
        from django.test import RequestFactory

        from intern import middleware

        mw = middleware.Ersteinrichtung(lambda request: "weiter")
        with mock.patch.object(middleware, "ist_eingerichtet", return_value=False):
            antwort = mw(RequestFactory().get("/intern/"))
            self.assertEqual(antwort.status_code, 302)
            self.assertEqual(antwort["Location"], "/einrichtung/")
            self.assertEqual(mw(RequestFactory().get("/einrichtung/")), "weiter")

    def test_smtp_ohne_host_schreibt_nichts(self):
        from intern.einrichtung import smtp_konfiguration

        self.assertEqual(smtp_konfiguration("", 25, "u", "p", "ssl"), {})

    def test_smtp_verschluesselung(self):
        from intern.einrichtung import smtp_konfiguration

        for wahl, tls, ssl in (("starttls", "1", "0"), ("ssl", "0", "1"), ("", "0", "0")):
            with self.subTest(wahl=wahl):
                werte = smtp_konfiguration("mail.example.de", None, "", "", wahl)
                self.assertEqual(werte["EMAIL_USE_TLS"], tls)
                self.assertEqual(werte["EMAIL_USE_SSL"], ssl)
                self.assertEqual(werte["EMAIL_PORT"], "587")

    def test_smtp_schluessel_stehen_im_katalog(self):
        from intern.apps import _CONFIG_DEFAULTS
        from intern.einrichtung import smtp_konfiguration

        katalog = {key for key, _, _ in _CONFIG_DEFAULTS}
        werte = smtp_konfiguration("h", 25, "", "", "")
        self.assertLessEqual(set(werte) | {"VEREINS_URL", "DEFAULT_FROM_EMAIL"}, katalog)

    def test_platzhalter_0003_ist_leer(self):
        import importlib

        modul = importlib.import_module("intern.migrations.0003_import")
        self.assertEqual(modul.Migration.operations, [])

    def test_aktuell_schreibgruppen_gibt_es(self):
        """Fehlt eine Gruppe, bekaeme sie still kein Schreibrecht auf „Aktuell"."""
        from intern.einrichtung import AKTUELL_SCHREIBGRUPPEN, GRUPPEN

        for name in AKTUELL_SCHREIBGRUPPEN:
            self.assertIn(name, GRUPPEN)

    def test_beispieltermine_liegen_in_der_zukunft(self):
        from intern.einrichtung import PROBEN_ANZAHL, beispieltermine

        # Ein Dienstag nach Probenbeginn: die erste Probe ist die der Folgewoche.
        jetzt = datetime(2026, 10, 13, 20, 0)
        termine = beispieltermine(jetzt)
        proben = [t for t in termine if not t["repertoire"]]
        konzerte = [t for t in termine if t["repertoire"]]

        self.assertEqual(len(proben), PROBEN_ANZAHL)
        self.assertEqual(len(konzerte), 1)
        self.assertEqual(proben[0]["datum"], datetime(2026, 10, 20, 19, 30))
        for termin in termine:
            self.assertGreater(termin["datum"], jetzt)
            self.assertGreater(termin["datum_bis"], termin["datum"])
        self.assertTrue(all(p["datum"].weekday() == 1 for p in proben))
        self.assertEqual(konzerte[0]["datum"].weekday(), 5)
        self.assertGreater(konzerte[0]["datum"], proben[-1]["datum"])

    def test_konzert_kommt_auf_die_startseite(self):
        # Die Startseite listet Termine mit nicht leerem Ankündigungstext.
        from intern.einrichtung import beispieltermine

        konzert = [t for t in beispieltermine(datetime(2026, 10, 13)) if t["repertoire"]][0]
        self.assertTrue(konzert["extern"].strip())

    def test_beispiellieder_passen_ins_modell(self):
        from intern.einrichtung import BEISPIEL_LIEDER, BEISPIEL_ORT, KONZERT_ABLAUF
        from intern.models import Lied, Ort

        tonarten = {k for k, _ in Lied.TONART_CHOICES}
        tempi = {k for k, _ in Lied.CHOICES}
        laenge = Lied._meta.get_field("titel").max_length
        for titel, _, _, tonart, tempo, _ in BEISPIEL_LIEDER:
            with self.subTest(titel=titel):
                self.assertLessEqual(len(titel), laenge)
                self.assertIn(tonart, tonarten)
                self.assertIn(tempo, tempi)
        self.assertEqual(len(set(KONZERT_ABLAUF)), len(KONZERT_ABLAUF))
        self.assertTrue(all(0 <= i < len(BEISPIEL_LIEDER) for i in KONZERT_ABLAUF))
        for feld, wert in BEISPIEL_ORT.items():
            maximal = Ort._meta.get_field(feld).max_length
            if maximal:
                self.assertLessEqual(len(wert), maximal, feld)


class RelayCursorTest(SimpleTestCase):
    """Der Relay-Stand des Bots überdauert einen Neustart; eine fehlende oder
    kaputte Datei heißt „kein Stand“ und führt zum Basiswert statt zum Absturz."""

    def test_schreiben_und_lesen(self):
        import tempfile
        from intern.management.commands.ejabberd_bot import (
            lese_relay_cursor, schreibe_relay_cursor,
        )

        with tempfile.TemporaryDirectory() as verz:
            pfad = Path(verz) / "xmpp_relay_cursor"
            self.assertIsNone(lese_relay_cursor(pfad))
            schreibe_relay_cursor(pfad, 4711)
            self.assertEqual(lese_relay_cursor(pfad), 4711)
            schreibe_relay_cursor(pfad, 4712)
            self.assertEqual(lese_relay_cursor(pfad), 4712)
            self.assertEqual(sorted(p.name for p in Path(verz).iterdir()), ["xmpp_relay_cursor"])

    def test_muell_ist_kein_stand(self):
        import tempfile
        from intern.management.commands.ejabberd_bot import lese_relay_cursor

        with tempfile.TemporaryDirectory() as verz:
            pfad = Path(verz) / "xmpp_relay_cursor"
            pfad.write_text("kaputt", encoding="ascii")
            self.assertIsNone(lese_relay_cursor(pfad))


class BotDbVerbindungTest(SimpleTestCase):
    """Jeder DB-Zugriff des Bots verwirft vorher eine tote Verbindung seines
    Threads; sonst bleibt die Brücke nach einem Datenbank-Neustart dauerhaft
    bei „Server has gone away“ hängen."""

    def test_alle_db_funktionen_umhuellt(self):
        from intern.management.commands import ejabberd_bot

        db_funktionen = [
            wert for name, wert in vars(ejabberd_bot).items() if name.startswith("_db_")
        ]
        db_funktionen.append(ejabberd_bot.CantorBot._configure_room)
        self.assertGreater(len(db_funktionen), 5)
        for funktion in db_funktionen:
            with self.subTest(funktion.__name__):
                self.assertTrue(hasattr(funktion, "__wrapped__"))

    def test_schliesst_vor_der_abfrage(self):
        from unittest.mock import patch
        from intern.management.commands.ejabberd_bot import _frische_verbindung

        reihenfolge = []

        def abfrage(x):
            reihenfolge.append("abfrage")
            return x

        with patch("django.db.close_old_connections",
                   side_effect=lambda: reihenfolge.append("schliessen")):
            self.assertEqual(_frische_verbindung(abfrage)(7), 7)
        self.assertEqual(reihenfolge, ["schliessen", "abfrage"])


class XmppReaktionEingangTest(SimpleTestCase):
    """Reaktionen (XEP-0444) tragen kein <body>; slixmpp meldet sie nur über das
    ``reactions``-Event von xep_0444, nie über groupchat_message. Der Bot muss sie
    dort abholen, sonst erreicht keine XMPP-Reaktion das Forum."""

    def _bot(self):
        from unittest.mock import AsyncMock
        from intern.management.commands.ejabberd_bot import CantorBot

        bot = CantorBot.__new__(CantorBot)
        bot._handle_reaction = AsyncMock()
        return bot

    def _nachricht(self, von, typ="groupchat"):
        from slixmpp import JID

        return {"type": typ, "from": JID(von)}

    def test_raumreaktion_wird_verarbeitet(self):
        import asyncio

        bot = self._bot()
        msg = self._nachricht("forum-1@muc.example/Anna")
        asyncio.run(bot._on_reactions(msg))
        bot._handle_reaction.assert_awaited_once_with(msg, "forum-1@muc.example", "Anna")

    def test_eigenes_echo_und_direktnachricht_nicht(self):
        import asyncio

        bot = self._bot()
        asyncio.run(bot._on_reactions(self._nachricht("forum-1@muc.example/CantorBot")))
        asyncio.run(bot._on_reactions(self._nachricht("anna@example/handy", typ="chat")))
        bot._handle_reaction.assert_not_awaited()

    def test_handler_registriert(self):
        quelle = (Path(__file__).parent / "management/commands/ejabberd_bot.py").read_text()
        self.assertIn('add_event_handler("reactions", self._on_reactions)', quelle)


class XmppEchoIdTest(SimpleTestCase):
    """Ein weitergeleiteter Forenbeitrag bekommt die Raum-Stanza-ID seines Echos;
    vergibt der Raum keine (ohne MAM), die id des Echos — darauf reagieren die
    Clients dann, und die Reaktion findet ihren Beitrag."""

    def _erfasse(self, stanza_id, nachricht_id, origin_id="cantorhub-42"):
        import asyncio
        from unittest import mock
        from intern.management.commands import ejabberd_bot

        msg = {
            "origin_id": {"id": origin_id},
            "stanza_id": {"id": stanza_id},
            "id": nachricht_id,
        }
        bot = ejabberd_bot.CantorBot.__new__(ejabberd_bot.CantorBot)
        with mock.patch.object(ejabberd_bot, "_db_capture_stanza_id") as speichern:
            asyncio.run(bot._capture_forum_stanza_id(msg))
        return speichern

    def test_stanza_id_hat_vorrang(self):
        self._erfasse("raum-sid", "msg-id").assert_called_once_with(42, "raum-sid")

    def test_ohne_stanza_id_die_nachrichten_id(self):
        self._erfasse("", "msg-id").assert_called_once_with(42, "msg-id")

    def test_fremdes_echo_nicht(self):
        self._erfasse("raum-sid", "msg-id", origin_id="abc").assert_not_called()


class StartseiteUeberlagerungTest(SimpleTestCase):
    """Die Startseite kommt Datei für Datei zuerst aus ``DATEN/startseite``, dann
    aus der mitgelieferten unter ``intern/startseite`` (``STARTSEITE_WURZELN``).

    Eine eigene Engine, damit eine Vorlage aus dem Volume weder eine
    Portalvorlage überschreiben noch eine einbinden kann, und ohne
    ``cached.Loader``, damit eine geänderte Seite ohne Neustart wirkt.
    """

    def _mit_wurzeln(self, volume, demo):
        from django.conf import settings
        from django.test import override_settings

        vorlagen = [dict(e) for e in settings.TEMPLATES]
        vorlagen[1] = dict(vorlagen[1], DIRS=[volume, demo])
        return override_settings(TEMPLATES=vorlagen, STARTSEITE_WURZELN=[volume, demo])

    def _baue(self, wurzel, dateien):
        for name, inhalt in dateien.items():
            pfad = wurzel / name
            pfad.parent.mkdir(parents=True, exist_ok=True)
            pfad.write_text(inhalt, encoding="utf-8")

    def test_volume_schlaegt_demo_und_luecken_fallen_zurueck(self):
        import tempfile
        from django.template import engines

        with tempfile.TemporaryDirectory() as tmp:
            volume, demo = Path(tmp) / "volume", Path(tmp) / "demo"
            self._baue(demo, {"index.html": "demo {% include '_fuss.html' %}",
                              "_fuss.html": "demo-fuss"})
            self._baue(volume, {"index.html": "eigen {% include '_fuss.html' %}"})
            with self._mit_wurzeln(volume, demo):
                text = engines["startseite"].get_template("index.html").render({})
        self.assertEqual(text, "eigen demo-fuss")

    def test_ohne_volume_die_demo(self):
        import tempfile
        from django.template import engines

        with tempfile.TemporaryDirectory() as tmp:
            demo = Path(tmp) / "demo"
            self._baue(demo, {"index.html": "demo"})
            with self._mit_wurzeln(Path(tmp) / "gibtsnicht", demo):
                text = engines["startseite"].get_template("index.html").render({})
        self.assertEqual(text, "demo")

    def test_keine_portalvorlage_erreichbar(self):
        from django.template import TemplateDoesNotExist, engines

        with self.assertRaises(TemplateDoesNotExist):
            engines["startseite"].get_template("base.html")

    def test_engine_ohne_cache_und_volume_zuerst(self):
        from django.conf import settings

        engine = next(e for e in settings.TEMPLATES if e.get("NAME") == "startseite")
        self.assertFalse(engine["APP_DIRS"])
        self.assertEqual(engine["OPTIONS"]["loaders"],
                         ["django.template.loaders.filesystem.Loader"])
        self.assertEqual(engine["DIRS"], settings.STARTSEITE_WURZELN)
        self.assertEqual(settings.STARTSEITE_WURZELN[0], settings.DATEN / "startseite")

    def test_statische_datei_volume_zuerst_und_nicht_hinaus(self):
        import tempfile
        from django.test import override_settings
        from intern.templatetags.startseite_tags import finde_statisch, startseite_datei

        with tempfile.TemporaryDirectory() as tmp:
            volume, demo = Path(tmp) / "volume", Path(tmp) / "demo"
            self._baue(demo, {"statisch/a.css": "demo", "statisch/b.css": "demo",
                              "index.html": "geheim"})
            self._baue(volume, {"statisch/a.css": "eigen"})
            with override_settings(STARTSEITE_WURZELN=[volume, demo]):
                self.assertEqual(finde_statisch("a.css"), volume / "statisch" / "a.css")
                self.assertEqual(finde_statisch("b.css"), demo / "statisch" / "b.css")
                self.assertIsNone(finde_statisch("c.css"))
                self.assertIsNone(finde_statisch("../index.html"))
                self.assertRegex(startseite_datei("a.css"), r"^/startseite/a\.css\?v=\d+$")
                self.assertEqual(startseite_datei("c.css"), "/startseite/c.css")

    def test_mitgelieferte_seite_uebersetzt_und_findet_ihre_dateien(self):
        # Jede startseite_datei-Referenz der mitgelieferten Seite muss es geben;
        # get_template übersetzt die Vorlage samt aller {% load %}.
        from django.conf import settings
        from django.template import engines
        from django.test import override_settings
        from intern.templatetags.startseite_tags import finde_statisch

        demo = settings.STARTSEITE_WURZELN[-1]
        with override_settings(STARTSEITE_WURZELN=[demo]):
            engines["startseite"].get_template("index.html")
            text = (demo / "index.html").read_text(encoding="utf-8")
            fehlend = [p for p in re.findall(r"startseite_datei '([^']+)'", text)
                       if finde_statisch(p) is None]
        self.assertEqual(fehlend, [])

    def test_portal_findet_sein_logo_in_der_mitgelieferten_seite(self):
        # Das Portal-Logo kommt über startseite_datei, damit DATEN/startseite es
        # überlagern kann. Jede Referenz in Portalvorlagen und Python muss die
        # mitgelieferte Seite auch ohne eigene Seite erfüllen — und keine darf
        # mehr auf das alte Logo unter intern/brand/ zeigen.
        from django.conf import settings
        from django.test import override_settings
        from intern.templatetags.startseite_tags import finde_statisch

        wurzel = Path(__file__).resolve().parent
        dateien = sorted((wurzel / "templates").rglob("*.html")) + [
            wurzel / "tables.py", wurzel / "replacements.py"]
        verweise, alt = set(), []
        for pfad in dateien:
            text = pfad.read_text(encoding="utf-8")
            verweise |= set(re.findall(r"""startseite_datei[ (]['"]([^'"]+)['"]""", text))
            if "intern/brand/logo.svg" in text:
                alt.append(pfad.name)
        self.assertIn("logo.svg", verweise)
        self.assertEqual(alt, [])
        with override_settings(STARTSEITE_WURZELN=[settings.STARTSEITE_WURZELN[-1]]):
            self.assertEqual([p for p in sorted(verweise) if finde_statisch(p) is None], [])


class NeutraleDemoTest(SimpleTestCase):
    """Die mitgelieferte Startseite nennt keinen bestimmten Chor.

    Sie ist die Vorlage, die eine neue Installation ohne eigene Seite zeigt;
    chorspezifisches gehört nach ``DATEN/startseite/`` (``docs/startseite.md``).
    """

    VERBOTEN = ("just gospel", "jg-frankfurt", "jg frankfurt", "frankfurt")

    # Die einzigen Binärdateien: aus logo.svg gerendert (Mail, PDF, PWA).
    NEUTRALE_BINAERDATEIEN = {
        "statisch/brand/icon-192.png",
        "statisch/brand/icon-512.png",
        "statisch/brand/briefkopf.png",
    }

    def test_keine_chornamen_in_der_mitgelieferten_seite(self):
        wurzel = Path(__file__).resolve().parent / "startseite"
        gefunden = []
        for pfad in sorted(wurzel.rglob("*")):
            if not pfad.is_file():
                continue
            if pfad.suffix not in (".html", ".css", ".svg", ".js", ".txt", ".md"):
                if str(pfad.relative_to(wurzel)) not in self.NEUTRALE_BINAERDATEIEN:
                    gefunden.append(f"{pfad.relative_to(wurzel)} (Binärdatei — Foto/Logo?)")
                continue
            text = pfad.read_text(encoding="utf-8").lower()
            gefunden += [f"{pfad.relative_to(wurzel)}: {wort}"
                         for wort in self.VERBOTEN if wort in text]
        self.assertEqual(gefunden, [], "Chorspezifisches gehört in DATEN/startseite/")


class KeineChorliteraleTest(SimpleTestCase):
    """Kein Code nennt den Chor, für den CantorHub entstanden ist.

    Name, Domain, Farbe und Logos einer Installation kommen aus ``Konfiguration``
    und ``DATEN/startseite/`` (``docs/branding.md``); der Code liefert neutrale
    Vorgaben. Ausgenommen sind diese Testdatei und die Migrationen.
    """

    VERBOTEN = ("just gospel", "jg-frankfurt", "jg frankfurt", "frankfurt",
                "join us singing", "c14468", "jg aufnahme", "hetzner", "hessisch")
    # Ein Passwort-Wörterbuch: „frankfurt“ ist dort ein Wort, kein Name.
    AUSNAHMEN = {"intern/static/intern/js/zxcvbn.js", "intern/tests.py"}
    ENDUNGEN = (".py", ".html", ".js", ".css", ".json", ".svg", ".txt")

    def test_kein_chorname_im_code(self):
        basis = Path(__file__).resolve().parent.parent
        gefunden = []
        for wurzel in ("intern", "config"):
            for pfad in sorted((basis / wurzel).rglob("*")):
                rel = str(pfad.relative_to(basis))
                if (not pfad.is_file() or pfad.suffix not in self.ENDUNGEN
                        or rel in self.AUSNAHMEN or "/migrations/" in rel
                        or "__pycache__" in rel):
                    continue
                text = pfad.read_text(encoding="utf-8", errors="replace").lower()
                gefunden += [f"{rel}: {wort}" for wort in self.VERBOTEN if wort in text]
        self.assertEqual(gefunden, [])


class AufnahmeBezeichnungTest(SimpleTestCase):
    """Die eigene Aufnahme heißt nach dem Datei-Präfix (``FILE_PREFIX``)."""

    def test_aus_dem_praefix(self):
        with mock.patch.dict("os.environ", {"FILE_PREFIX": "JG"}):
            self.assertEqual(app_settings.get_aufnahme_bezeichnung(), "JG Aufnahme")

    def test_ohne_praefix(self):
        with mock.patch.dict("os.environ", {"FILE_PREFIX": " "}):
            self.assertEqual(app_settings.get_aufnahme_bezeichnung(), "Eigene Aufnahme")


class WikiPlatzhalterTest(SimpleTestCase):
    """``{NAME}`` in Artikeln — nur die bekannten Namen, Werte escapet."""

    def _werte(self, **werte):
        aufrufe = []

        def liefern():
            aufrufe.append(1)
            return werte

        return liefern, aufrufe

    def test_bekannter_name_wird_ersetzt(self):
        from intern.wiki_platzhalter import ersetzen
        werte, _ = self._werte(BENUTZERNAME="anna")
        self.assertEqual(ersetzen("Hallo {BENUTZERNAME}!", werte), "Hallo anna!")

    def test_unbekannt_und_konfiguration_bleiben(self):
        from intern.wiki_platzhalter import ersetzen
        werte, _ = self._werte(EMAIL_HOST_PASSWORD="geheim")
        text = "{EMAIL_HOST_PASSWORD} {abstimmung:x} {Klein}"
        self.assertEqual(ersetzen(text, werte), text)

    def test_ohne_platzhalter_keine_werte(self):
        from intern.wiki_platzhalter import ersetzen
        werte, aufrufe = self._werte()
        ersetzen("Nur Text {und Klammern}", werte)
        self.assertEqual(aufrufe, [])

    def test_wert_wird_escapet_und_fehlender_markiert(self):
        from intern.wiki_platzhalter import FEHLT, ersetzen
        werte, _ = self._werte(VEREINSNAME="<b>Chor</b>")
        self.assertEqual(ersetzen("{VEREINSNAME}", werte), "&lt;b&gt;Chor&lt;/b&gt;")
        self.assertEqual(ersetzen("{XMPP_DOMAIN}", werte), FEHLT)

    def test_werte_berechnen(self):
        from intern.wiki_platzhalter import AUS, EIN, werte_berechnen
        w = werte_berechnen(
            basis="https://portal.example.org:8443", ical_pfad="/intern/calendar/abc.ics",
            xmpp_domain="", xmpp_adresse="", benutzername="anna",
            caldav_aktiv=True, carddav_aktiv=False, namen={"VEREINSNAME": "Chor"},
        )
        self.assertEqual(w["SERVER"], "portal.example.org:8443")
        self.assertEqual(w["CALDAV_URL"], "https://portal.example.org:8443/caldav/")
        self.assertEqual(w["CARDDAV_URL"], "https://portal.example.org:8443/carddav/")
        self.assertEqual(w["ICAL_URL"], "https://portal.example.org:8443/intern/calendar/abc.ics")
        self.assertEqual(w["WEBCAL_URL"], "webcal://portal.example.org:8443/intern/calendar/abc.ics")
        self.assertEqual((w["CALDAV_STATUS"], w["CARDDAV_STATUS"], w["XMPP_STATUS"]), (EIN, AUS, AUS))
        self.assertEqual(w["VEREINSNAME"], "Chor")

    def test_jeder_name_wird_berechnet(self):
        from intern.wiki_platzhalter import BESCHREIBUNG, werte_berechnen
        namen = {"KALENDER_NAME": "", "GEBURTSTAGE_NAME": "", "ADRESSBUCH_NAME": "",
                 "VEREINSNAME": "", "VEREINSNAME_LANG": "", "VEREINSNAME_KURZ": ""}
        w = werte_berechnen(basis="", ical_pfad="", xmpp_domain="", xmpp_adresse="",
                            benutzername="", caldav_aktiv=False, carddav_aktiv=False,
                            namen=namen)
        self.assertEqual(set(w), set(BESCHREIBUNG))


class WikiMarkupTest(SimpleTestCase):
    """``apply_replacements``: Hervorhebung, Blöcke und Platzhalter."""

    def _rendern(self, text, werte=None, request=True):
        from intern import replacements, wiki_platzhalter
        req = SimpleNamespace(user=None) if request else None
        with mock.patch.object(replacements, "get_vereinsname_kurz", return_value="Chor"), \
                mock.patch.object(wiki_platzhalter, "werte_fuer",
                                  return_value=lambda: werte or {}):
            return replacements.apply_replacements(text, req)

    def test_zwei_hervorhebungen_in_einer_zeile(self):
        out = self._rendern("Ein '''fettes''' und ein '''zweites''' und ''schräg''")
        self.assertIn("<strong>fettes</strong> und ein <strong>zweites</strong>", out)
        self.assertIn("<em>schräg</em>", out)

    def test_hervorhebung_im_kasten(self):
        out = self._rendern("@ '''Wichtig:''' Text")
        self.assertIn('<div class="boxed"><strong>Wichtig:</strong> Text</div>', out)

    def test_bloecke_in_ihrer_reihenfolge(self):
        out = self._rendern("@ Kasten\n% Hinweis\n Code")
        self.assertLess(out.index('class="boxed"'), out.index('class="citation"'))
        self.assertLess(out.index('class="citation"'), out.index("<pre><code>"))

    def test_platzhalter_nur_ausserhalb_von_code(self):
        out = self._rendern("Adresse: {VEREINS_URL}\n {VEREINS_URL}",
                            {"VEREINS_URL": "https://portal.example.org"})
        self.assertIn('<a href="https://portal.example.org">', out)
        self.assertIn("<pre><code> {VEREINS_URL}", out)

    def test_im_forum_keine_platzhalter(self):
        out = self._rendern("{BENUTZERNAME}", {"BENUTZERNAME": "anna"}, request=False)
        self.assertIn("{BENUTZERNAME}", out)

    def test_webcal_link(self):
        out = self._rendern("[webcal://portal.example.org/k.ics Abonnieren]")
        self.assertIn('<a href="webcal://portal.example.org/k.ics">Abonnieren</a>', out)


class HilfeArtikelTest(SimpleTestCase):
    """Die mitgelieferten Hilfe-Artikel sind in sich stimmig."""

    def _texte(self):
        from intern import hilfe
        return {name: hilfe.text(name) for name in hilfe.ARTIKEL}

    def test_bilder_vorhanden_und_genutzt(self):
        from intern import hilfe
        vorhanden = {p.name for p in hilfe.bilder()}
        genutzt = set()
        for text in self._texte().values():
            for zeile in text.splitlines():
                if not zeile.startswith(" "):  # Codezeilen sind nur Beispiele
                    genutzt |= set(re.findall(r"\[\[Datei:([^\]|]+)", zeile))
        self.assertEqual(genutzt - vorhanden, set(), "Bild fehlt unter intern/hilfe/bilder/")
        self.assertEqual(vorhanden - genutzt, set(), "Bild wird von keinem Artikel genutzt")

    def test_platzhalter_bekannt(self):
        from intern.wiki_platzhalter import BESCHREIBUNG, MUSTER
        for name, text in self._texte().items():
            for zeile in text.splitlines():
                if zeile.startswith(" "):
                    continue  # Codezeile: zeigt den Platzhalter absichtlich roh
                unbekannt = set(MUSTER.findall(zeile)) - set(BESCHREIBUNG)
                self.assertEqual(unbekannt, set(), name)

    def test_hilfe_links_fuehren_zu_hilfe_artikeln(self):
        from intern import hilfe
        for name, text in self._texte().items():
            for ziel in re.findall(r"\[\[(Hilfe[^\]|]*)", text):
                self.assertIn(ziel, hilfe.ARTIKEL, f"{name} → {ziel}")

    def test_platzhalterliste_eingesetzt(self):
        from intern import hilfe
        text = hilfe.text("Hilfe:Wiki")
        self.assertNotIn(hilfe.PLATZHALTER_MARKE, text)
        self.assertIn(" {XMPP_ADRESSE} — ", text)

    def test_navigation_oben_und_unten(self):
        from intern import hilfe
        seiten = [n for n in hilfe.ARTIKEL if n.startswith("Hilfe:")]
        for i, name in enumerate(seiten):
            zeilen = hilfe.text(name).strip().splitlines()
            self.assertEqual(zeilen[0], zeilen[-1], name)
            nav = zeilen[0]
            self.assertIn("[[Hilfe|Übersicht]]", nav)
            vorher = f"← [[{seiten[i - 1]}|" if i > 0 else "←"
            nachher = f"[[{seiten[i + 1]}|" if i + 1 < len(seiten) else "→"
            self.assertEqual(vorher in nav, i > 0, name)
            self.assertEqual(nachher in nav, i + 1 < len(seiten), name)
        self.assertNotIn("←", hilfe.text("Hilfe"))

    def test_uebersicht_nennt_jeden_artikel(self):
        from intern import hilfe
        uebersicht = hilfe.text("Hilfe")
        for name in hilfe.ARTIKEL:
            if name != "Hilfe":
                self.assertIn(f"[[{name}", uebersicht)


class ManifestTest(SimpleTestCase):
    """Das Web-App-Manifest folgt der Konfiguration."""

    def test_daten(self):
        from intern.views.auth import manifest_daten
        m = manifest_daten("Unser Chor", "#123456", "/startseite/a.png", "/startseite/b.png")
        self.assertEqual(m["name"], "Unser Chor")
        self.assertEqual(m["theme_color"], "#123456")
        self.assertEqual([i["src"] for i in m["icons"]], ["/startseite/a.png", "/startseite/b.png"])


class WikiListenTest(SimpleTestCase):
    """Die Ebene einer Liste zählt nur die führenden * bzw. #."""

    def _rendern(self, text):
        from intern import replacements
        with mock.patch.object(replacements, "get_vereinsname_kurz", return_value="Chor"):
            return replacements.apply_replacements(text)

    def test_hervorhebung_in_nummerierter_liste(self):
        out = self._rendern("# Bei '''XMPP-Adresse''' eintragen\n# zweiter Schritt")
        self.assertIn("<ol><li>Bei <strong>XMPP-Adresse</strong> eintragen</li>", out)
        self.assertEqual(out.count("<ol>"), 1)

    def test_stern_im_text_aendert_die_ebene_nicht(self):
        out = self._rendern("* Note 5* gibt es nicht\n* zweiter")
        self.assertEqual(out.count("<ul>"), 1)


class BotPasswortTest(SimpleTestCase):
    """Wann die Konfigurationsseite ein neues Bot-Passwort in ejabberd setzt."""

    ALT = {
        "EJABBERD_HOST": "chat.example.org",
        "EJABBERD_BOT_JID": "bot@chat.example.org",
        "EJABBERD_BOT_PASSWORD": "alt",
        "EJABBERD_API_URL": "http://127.0.0.1:5280",
    }

    def _weg(self, neu, alt=None, nur_speichern=False):
        from intern.bot_passwort import bot_passwort_weg
        return bot_passwort_weg(self.ALT if alt is None else alt, neu, nur_speichern)

    def test_neues_passwort_geht_an_ejabberd(self):
        from intern.bot_passwort import EJABBERD
        self.assertEqual(self._weg({"EJABBERD_BOT_PASSWORD": "neu"}), EJABBERD)

    def test_ohne_aenderung_nichts(self):
        self.assertIsNone(self._weg({"EJABBERD_HOST": "chat.example.org"}))
        self.assertIsNone(self._weg({"EJABBERD_BOT_PASSWORD": "alt"}))

    def test_angekreuzt_nur_speichern(self):
        from intern.bot_passwort import NUR_SPEICHERN
        self.assertEqual(
            self._weg({"EJABBERD_BOT_PASSWORD": "neu"}, nur_speichern=True), NUR_SPEICHERN
        )

    def test_erstbelegung_nur_speichern(self):
        from intern.bot_passwort import NUR_SPEICHERN
        for leer in ("EJABBERD_BOT_PASSWORD", "EJABBERD_HOST", "EJABBERD_BOT_JID"):
            with self.subTest(leer=leer):
                alt = dict(self.ALT, **{leer: ""})
                self.assertEqual(self._weg({"EJABBERD_BOT_PASSWORD": "neu"}, alt), NUR_SPEICHERN)

    def test_anderes_konto_im_selben_speichern_nur_speichern(self):
        from intern.bot_passwort import NUR_SPEICHERN
        for key, wert in (("EJABBERD_BOT_JID", "neu@chat.example.org"),
                          ("EJABBERD_HOST", "anders.example.org"),
                          ("EJABBERD_API_URL", "https://anders.example.org")):
            with self.subTest(key=key):
                neu = {"EJABBERD_BOT_PASSWORD": "neu", key: wert}
                self.assertEqual(self._weg(neu), NUR_SPEICHERN)

    def test_unveraenderter_host_im_payload_stoert_nicht(self):
        from intern.bot_passwort import EJABBERD
        neu = {"EJABBERD_BOT_PASSWORD": "neu", "EJABBERD_HOST": "chat.example.org"}
        self.assertEqual(self._weg(neu), EJABBERD)

    def test_lokalteil(self):
        from intern.bot_passwort import lokalteil
        self.assertEqual(lokalteil("bot@chat.example.org"), "bot")
        self.assertEqual(lokalteil(""), "")


class BotZugangTest(SimpleTestCase):
    """Der Bot startet neu, wenn die Konfiguration andere Zugangsdaten nennt."""

    def _pruefen(self, aktuell):
        import asyncio
        from intern.management.commands import ejabberd_bot as modul

        bot = object.__new__(modul.CantorBot)
        bot._zugang = ("chat.example.org", 5222, "bot@chat.example.org", "alt")
        bot._neustart = False

        async def lauf():
            loop = asyncio.get_running_loop()
            with mock.patch.object(modul, "_lese_zugang", return_value=aktuell), \
                    mock.patch.object(loop, "stop") as stop, \
                    mock.patch.object(loop, "call_later") as call_later:
                await bot._zugang_pruefen()
                return stop.called, call_later.called

        gestoppt, neu_geplant = asyncio.run(lauf())
        return bot, gestoppt, neu_geplant

    def test_geaendertes_passwort_stoppt_fuer_neustart(self):
        bot, gestoppt, neu_geplant = self._pruefen(
            ("chat.example.org", 5222, "bot@chat.example.org", "neu")
        )
        self.assertTrue(bot._neustart)
        self.assertTrue(gestoppt)
        self.assertFalse(neu_geplant)

    def test_gleiche_zugangsdaten_pruefen_weiter(self):
        bot, gestoppt, neu_geplant = self._pruefen(
            ("chat.example.org", 5222, "bot@chat.example.org", "alt")
        )
        self.assertFalse(bot._neustart)
        self.assertFalse(gestoppt)
        self.assertTrue(neu_geplant)

    def test_neustart_ist_kein_regulaeres_ende(self):
        # neustart_bei_absturz in start.sh startet nur bei Code ungleich 0 neu.
        from intern.management.commands.ejabberd_bot import NEUSTART
        self.assertNotEqual(NEUSTART, 0)


class SmtpZugangTest(SimpleTestCase):
    """Wann die Konfigurationsseite einen neuen SMTP-Zugang vor dem Speichern prüft."""

    ALT = {
        "EMAIL_HOST": "smtp.example.org",
        "EMAIL_PORT": "587",
        "EMAIL_HOST_USER": "portal",
        "EMAIL_HOST_PASSWORD": "alt",
        "EMAIL_USE_TLS": "1",
        "EMAIL_USE_SSL": "0",
    }

    def _pruefung(self, neu, nur_speichern=False):
        from intern.smtp_zugang import smtp_pruefung
        return smtp_pruefung(self.ALT, neu, nur_speichern)

    def test_ohne_aenderung_nichts(self):
        self.assertIsNone(self._pruefung({"EMAIL_HOST": "smtp.example.org", "VEREINSNAME": "x"}))

    def test_neues_passwort_wird_geprueft(self):
        from intern.smtp_zugang import PRUEFEN
        self.assertEqual(self._pruefung({"EMAIL_HOST_PASSWORD": "neu"}), PRUEFEN)

    def test_tls_und_ssl_immer_abgelehnt(self):
        from intern.smtp_zugang import FEHLER_TLS_SSL
        self.assertEqual(self._pruefung({"EMAIL_USE_SSL": "1"}), FEHLER_TLS_SSL)
        self.assertEqual(self._pruefung({"EMAIL_USE_SSL": "true"}, nur_speichern=True),
                         FEHLER_TLS_SSL)

    def test_leerer_host_schaltet_ab_ohne_pruefung(self):
        from intern.smtp_zugang import NUR_SPEICHERN
        self.assertEqual(self._pruefung({"EMAIL_HOST": " "}), NUR_SPEICHERN)

    def test_angekreuzt_nur_speichern(self):
        from intern.smtp_zugang import NUR_SPEICHERN
        self.assertEqual(self._pruefung({"EMAIL_HOST_PASSWORD": "neu"}, nur_speichern=True),
                         NUR_SPEICHERN)

    def test_zusammengefuehrt_mischt_alt_und_neu(self):
        from intern.smtp_zugang import zusammengefuehrt
        werte = zusammengefuehrt(self.ALT, {"EMAIL_PORT": "465", "VEREINSNAME": "x"})
        self.assertEqual(werte["EMAIL_PORT"], "465")
        self.assertEqual(werte["EMAIL_HOST_PASSWORD"], "alt")
        self.assertNotIn("VEREINSNAME", werte)

    def test_fehlertext_unterscheidet_anmeldung_und_verbindung(self):
        import smtplib

        from intern.smtp_zugang import fehlertext
        self.assertIn("Anmeldung abgelehnt",
                      fehlertext(smtplib.SMTPAuthenticationError(535, b"no")))
        self.assertIn("nicht erreichbar", fehlertext(ConnectionRefusedError()))

    def test_unerreichbarer_server_liefert_text(self):
        from intern.smtp_zugang import anmeldung_pruefen, zusammengefuehrt
        werte = zusammengefuehrt(self.ALT, {"EMAIL_HOST": "127.0.0.1", "EMAIL_PORT": "1"})
        self.assertIn("nicht erreichbar", anmeldung_pruefen(werte))


class SicherungTest(SimpleTestCase):
    """Die Datenbank-Sicherung nach sicherung/ (intern/sicherung.py)."""

    def test_faellig(self):
        from datetime import datetime, timedelta

        from intern.sicherung import faellig
        jetzt = datetime(2026, 10, 18, 12, 0)
        self.assertTrue(faellig(None, jetzt, 24))
        self.assertFalse(faellig(jetzt - timedelta(hours=23), jetzt, 24))
        self.assertTrue(faellig(jetzt - timedelta(hours=24), jetzt, 24))
        self.assertFalse(faellig(None, jetzt, 0), msg="0 schaltet ab")

    def test_stand_lesen(self):
        from datetime import datetime

        from intern.sicherung import lese_stand
        self.assertEqual(lese_stand('{"zeitpunkt": "2026-10-18T03:00:00"}'),
                         datetime(2026, 10, 18, 3, 0))
        self.assertIsNone(lese_stand("kaputt"))
        self.assertIsNone(lese_stand("{}"))

    def test_modellauswahl(self):
        # Jede Tabelle genau einmal, M2M- und filer-Erbtabellen dabei,
        # Sitzungen nicht.
        from django.apps import apps

        from intern.sicherung import zu_sichernde_modelle
        tabellen = [m._meta.db_table
                    for m in zu_sichernde_modelle(apps.get_models(include_auto_created=True))]
        self.assertEqual(len(tabellen), len(set(tabellen)))
        self.assertNotIn("django_session", tabellen)
        for tabelle in ("intern_user", "intern_user_groups", "filer_file", "filer_image",
                        "intern_konfiguration", "django_content_type"):
            self.assertIn(tabelle, tabellen)

    def test_ziel_alias_im_datenverzeichnis(self):
        from django.conf import settings

        from intern.sicherung import ALIAS, verzeichnis
        ziel = settings.DATABASES[ALIAS]
        self.assertEqual(ziel["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(str(ziel["NAME"]), str(verzeichnis() / "cantorhub.sqlite3.tmp"))

    def test_seed_nur_in_der_portal_datenbank(self):
        # SimpleTestCase verbietet DB-Zugriff: liefe _seed_config für den
        # Sicherungs-Alias weiter, schlüge der Test fehl.
        from intern.apps import _seed_config
        _seed_config(sender=None, using="sicherung")

    def test_stignore_laesst_schluessel_und_live_db_aus(self):
        # Der Geräteschlüssel des Servers gehört nicht auf ein Speichergerät,
        # eine laufende SQLite-Datei nicht in eine Spiegelung.
        from django.conf import settings
        start = (Path(settings.BASE_DIR) / "start.sh").read_text()
        block = start.split("/.stignore\" <<'EOF'", 1)[1].split("\nEOF", 1)[0]
        zeilen = block.splitlines()
        for muster in ("/syncthing", "/db.sqlite3", "/db.sqlite3-*", "/sicherung/*.tmp*",
                       "/wiederherstellung", "/wiederherstellung.*"):
            self.assertIn(muster, zeilen)


class SyncthingTest(SimpleTestCase):
    """Das mitlaufende Syncthing hinter /intern/sicherung/ (intern/syncthing.py)."""

    ID = "4GTKHTA-NWIV7MD-H5R6NM2-KUNYIZO-UV44DQV-RRGCYYI-KSPOP6R-PV4YBAD"

    def test_geraete_id_normalisiert(self):
        from intern.syncthing import geraete_id
        self.assertEqual(geraete_id(self.ID), self.ID)
        self.assertEqual(geraete_id(self.ID.lower().replace("-", " ")), self.ID)
        self.assertEqual(geraete_id(self.ID.replace("-", "")), self.ID)
        self.assertIsNone(geraete_id("UNSINN"))
        self.assertIsNone(geraete_id(self.ID[:-1] + "1"), msg="1 ist kein Base32-Zeichen")
        self.assertIsNone(geraete_id(None))

    def test_zugang_aus_config(self):
        from intern.syncthing import zugang_aus_config
        xml = ('<configuration><gui enabled="true" tls="false"><address>0.0.0.0:8384</address>'
               '<apikey>abc</apikey></gui></configuration>')
        self.assertEqual(zugang_aus_config(xml), ("http://127.0.0.1:8384", "abc"))
        xml_lokal = xml.replace("0.0.0.0", "127.0.0.1").replace('tls="false"', 'tls="true"')
        self.assertEqual(zugang_aus_config(xml_lokal), ("https://127.0.0.1:8384", "abc"))
        self.assertIsNone(zugang_aus_config("<configuration/>"))
        self.assertIsNone(zugang_aus_config("kaputt"))

    def test_stignore_schuetzt(self):
        from intern.syncthing import stignore_schuetzt
        self.assertTrue(stignore_schuetzt("// Kommentar\n/syncthing\n/tiles\n"))
        self.assertFalse(stignore_schuetzt("/tiles\n"))
        self.assertFalse(stignore_schuetzt("/syncthing-alt\n"))
        self.assertFalse(stignore_schuetzt(None))

    def test_ortszeit(self):
        from datetime import datetime, timezone

        from intern.syncthing import ortszeit
        erwartet = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc).astimezone()
        self.assertEqual(ortszeit("2026-10-18T14:00:00Z"), erwartet.strftime("%d.%m.%Y %H:%M"))
        self.assertEqual(ortszeit("2026-10-18T14:00:00"), "18.10.2026 14:00")
        self.assertEqual(ortszeit("1970-01-01T00:00:00Z"), "", msg="Syncthings „nie“")
        self.assertEqual(ortszeit(""), "")
        self.assertEqual(ortszeit("unsinn"), "")

    def test_geraete_aufbereiten(self):
        from intern.syncthing import geraete_aufbereiten
        eigen = "EIGENE1-" + "A" * 7
        anderes = self.ID.replace("4GTKHTA", "ZJFYPCB")
        ordner = {"devices": [
            {"deviceID": eigen, "encryptionPassword": ""},
            {"deviceID": self.ID, "encryptionPassword": ""},
            {"deviceID": anderes, "encryptionPassword": "geheim"},
        ]}
        verbindungen = {"connections": {
            self.ID: {"connected": True, "type": "tcp-client", "address": "127.0.0.1:22001"},
            anderes: {"connected": True, "type": "relay-client", "address": "1.2.3.4:22067"},
        }}
        geraete = geraete_aufbereiten(ordner, verbindungen, {}, {self.ID: {"completion": 100}}, eigen)
        self.assertEqual([g["kurz"] for g in geraete], ["4GTKHTA", "ZJFYPCB"],
                         msg="das eigene Gerät gehört nicht in die Liste")
        self.assertFalse(geraete[0]["verschluesselt"])
        self.assertTrue(geraete[1]["verschluesselt"])
        self.assertFalse(geraete[0]["ueber_relay"])
        self.assertTrue(geraete[1]["ueber_relay"])
        self.assertEqual(geraete[0]["fortschritt"], 100)
        self.assertIsNone(geraete[1]["fortschritt"])

    def test_seite_nur_fuer_superuser(self):
        from types import SimpleNamespace

        from django.test import RequestFactory

        from intern.views.sicherung import sicherung, sicherung_entfernen
        for view, methode, args in ((sicherung, "get", ()), (sicherung_entfernen, "post", (self.ID,))):
            anfrage = getattr(RequestFactory(), methode)("/intern/sicherung/")
            anfrage.user = SimpleNamespace(is_authenticated=True, is_superuser=False)
            antwort = view(anfrage, *args)
            self.assertEqual(antwort.status_code, 302)
            self.assertIn("/Aktuell/", antwort["Location"])

    def test_ordner_umstellen_xml(self):
        import xml.etree.ElementTree as ET

        from intern.syncthing import ordner_umstellen_xml
        xml = ('<configuration version="37">'
               '<folder id="cantorhub" label="CantorHub" path="/data/wiederherstellung" '
               'type="receiveonly"><device id="X"></device></folder>'
               '<folder id="anderer" path="/x" type="sendreceive"></folder></configuration>')
        wurzel = ET.fromstring(ordner_umstellen_xml(xml, "/data"))
        ordner = {f.get("id"): f for f in wurzel.findall("folder")}
        self.assertEqual(ordner["cantorhub"].get("path"), "/data")
        self.assertEqual(ordner["cantorhub"].get("type"), "sendonly")
        self.assertIsNotNone(ordner["cantorhub"].find("device"), msg="Freigabe bleibt")
        self.assertEqual(ordner["anderer"].get("type"), "sendreceive")
        self.assertIsNone(ordner_umstellen_xml("<configuration/>", "/data"))
        self.assertIsNone(ordner_umstellen_xml("kaputt", "/data"))


class WiederherstellungTest(SimpleTestCase):
    """Wiederherstellen aus einer Sicherung (intern/wiederherstellung.py)."""

    def _sicherung(self, wurzel, migrationen=(("intern", "0001_initial"),), schluessel=True):
        import sqlite3

        (wurzel / "sicherung").mkdir(parents=True)
        db = sqlite3.connect(wurzel / "sicherung" / "cantorhub.sqlite3")
        db.execute("CREATE TABLE django_migrations (id INTEGER PRIMARY KEY, app TEXT, name TEXT)")
        db.executemany("INSERT INTO django_migrations (app, name) VALUES (?, ?)", migrationen)
        db.commit()
        db.close()
        (wurzel / "sicherung" / "stand.json").write_text('{"zeitpunkt": "2026-10-18T03:00:00"}')
        if schluessel:
            (wurzel / "secret_key").write_text("alt")

    def test_pruefen(self):
        import tempfile

        from intern.wiederherstellung import pruefen
        bekannt = {("intern", "0001_initial")}
        with tempfile.TemporaryDirectory() as tmp:
            wurzel = Path(tmp) / "gut"
            self._sicherung(wurzel)
            self.assertIsNone(pruefen(wurzel, bekannt))
        with tempfile.TemporaryDirectory() as tmp:
            wurzel = Path(tmp) / "ohne-schluessel"
            self._sicherung(wurzel, schluessel=False)
            self.assertIn("Schlüssel", pruefen(wurzel, bekannt))
        with tempfile.TemporaryDirectory() as tmp:
            wurzel = Path(tmp) / "neuer"
            self._sicherung(wurzel, migrationen=(("intern", "0001_initial"),
                                                 ("intern", "9999_zukunft")))
            self.assertIn("neueren Version", pruefen(wurzel, bekannt))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("Datenbank-Kopie", pruefen(Path(tmp), bekannt))

    def test_bekannte_migrationen_ohne_datenbank(self):
        from intern.wiederherstellung import bekannte_migrationen
        bekannt = bekannte_migrationen()
        self.assertIn(("intern", "0001_initial"), bekannt)
        self.assertIn(("auth", "0001_initial"), bekannt)

    def test_dateien_uebernehmen(self):
        import tempfile

        from intern.wiederherstellung import _dateien_uebernehmen
        with tempfile.TemporaryDirectory() as tmp:
            daten = Path(tmp)
            ordner = daten / "wiederherstellung"
            for pfad, inhalt in (("media/a/bild.jpg", "bild"), ("startseite/index.html", "alt"),
                                 ("secret_key", "alter-schluessel"), ("syncthing/key.pem", "fremd"),
                                 ("db.sqlite3", "x")):
                (ordner / pfad).parent.mkdir(parents=True, exist_ok=True)
                (ordner / pfad).write_text(inhalt)
            for pfad, inhalt in (("startseite/index.html", "demo"), ("startseite/demo.css", "d"),
                                 ("secret_key", "neu"), ("syncthing/key.pem", "eigen")):
                (daten / pfad).parent.mkdir(parents=True, exist_ok=True)
                (daten / pfad).write_text(inhalt)
            (daten / "media").mkdir()

            _dateien_uebernehmen(ordner, daten)

            self.assertEqual((daten / "media/a/bild.jpg").read_text(), "bild")
            self.assertEqual((daten / "startseite/index.html").read_text(), "alt")
            self.assertFalse((daten / "startseite/demo.css").exists(), msg="Demo weicht ganz")
            self.assertEqual((daten / "secret_key").read_text(), "alter-schluessel")
            self.assertEqual((daten / "secret_key").stat().st_mode & 0o777, 0o600)
            self.assertEqual((daten / "syncthing/key.pem").read_text(), "eigen",
                             msg="der Schlüssel dieses Syncthing bleibt")
            self.assertFalse((daten / "db.sqlite3").exists(), msg="keine laufende SQLite-Datei")

    def test_seite_nach_einrichtung_404(self):
        from unittest import mock

        from django.http import Http404
        from django.test import RequestFactory

        from intern.views.einrichtung import wiederherstellen
        with mock.patch("intern.views.einrichtung.ist_eingerichtet", return_value=True):
            with self.assertRaises(Http404):
                wiederherstellen(RequestFactory().get("/einrichtung/wiederherstellen/"))

    def test_kein_neustart_ausserhalb_des_containers(self):
        # Unter DEBUG (Entwicklung, Tests) wäre PID 1 das init des Rechners.
        from intern.views.einrichtung import _neu_starten
        self.assertFalse(_neu_starten())

    def test_klon_konfiguration(self):
        from intern.wiederherstellung import klon_konfiguration
        neu = klon_konfiguration(
            {"VEREINSNAME_KURZ": "Chor", "EMAIL_HOST": "smtp.example.org"}, "http://localhost:8001",
        )
        for key in ("EMAIL_HOST", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD",
                    "EJABBERD_HOST", "EJABBERD_BOT_JID", "EJABBERD_BOT_PASSWORD"):
            self.assertEqual(neu[key], "", key)
        self.assertEqual(neu["VEREINS_URL"], "http://localhost:8001")
        self.assertEqual(neu["VEREINSNAME_KURZ"], "Klon Chor")
        # Ein Klon vom Klon bekommt das Präfix nicht zweimal.
        self.assertNotIn("VEREINSNAME_KURZ", klon_konfiguration({"VEREINSNAME_KURZ": "Klon Chor"}, ""))
        self.assertEqual(klon_konfiguration({}, "")["VEREINSNAME_KURZ"], "Klon")

    def test_klon_umgebung(self):
        from intern.wiederherstellung import klon_umgebung
        self.assertEqual(klon_umgebung({"EMAIL_HOST": "smtp", "VEREINS_URL": "https://x",
                                        "EJABBERD_HOST": "", "PATH": "/bin"}),
                         ["EMAIL_HOST", "VEREINS_URL"])

    def test_klon_einrichten(self):
        import tempfile
        from unittest import mock

        from intern import wiederherstellung
        with tempfile.TemporaryDirectory() as tmp:
            daten = Path(tmp)
            (daten / "syncthing").mkdir()
            (daten / "syncthing" / "config.xml").write_text("<configuration/>")
            with mock.patch("intern.models.Konfiguration.objects") as objekte, \
                    mock.patch.dict("os.environ", {"EMAIL_HOST": "smtp"}), \
                    self.assertLogs("intern.wiederherstellung", "WARNING") as protokoll:
                objekte.values_list.return_value = [("VEREINSNAME_KURZ", "Chor")]
                wiederherstellung._klon_einrichten(daten, "http://localhost:8001")
            gesetzt = {c.kwargs["key"]: c.kwargs["defaults"]["value"]
                       for c in objekte.update_or_create.call_args_list}
            self.assertEqual(gesetzt["VEREINS_URL"], "http://localhost:8001")
            self.assertEqual(gesetzt["EMAIL_HOST"], "")
            self.assertEqual(gesetzt["VEREINSNAME_KURZ"], "Klon Chor")
            self.assertFalse((daten / "syncthing").exists(), msg="neue Identität ohne Freigaben")
            self.assertIn("EMAIL_HOST", protokoll.output[0])

    def _seite(self, anfrage, zustand):
        """Die Seite mit gemocktem Syncthing; zurück kommen Kontext und geschriebene Zustände."""
        import importlib
        from unittest import mock

        # Das Modul, nicht die gleichnamige View, die views/__init__.py exportiert.
        einrichtung = importlib.import_module("intern.views.einrichtung")
        geschrieben = []
        with mock.patch.object(einrichtung, "ist_eingerichtet", return_value=False), \
                mock.patch.object(einrichtung.wh, "lese_zustand", return_value=zustand), \
                mock.patch.object(einrichtung.wh, "schreibe_zustand",
                                  side_effect=lambda **w: geschrieben.append(w)), \
                mock.patch.object(einrichtung.wh, "pruefen", return_value=None), \
                mock.patch.object(einrichtung.wh, "zusammenfassung", return_value={}), \
                mock.patch.object(einrichtung, "syncthing") as st, \
                mock.patch.object(einrichtung, "_neu_starten", return_value=False), \
                mock.patch.object(einrichtung, "render") as render:
            st.SyncthingFehler = Exception
            st.eigene_id.return_value = "NEUE-ID"
            st.status.return_value = {"wartend": []}
            st.empfang_stand.return_value = {"fertig": True}
            einrichtung.wiederherstellen(anfrage)
        return render.call_args.args[2], geschrieben

    def test_seite_klon_aus_der_adresse(self):
        from django.test import RequestFactory
        kontext, _ = self._seite(RequestFactory().get("/einrichtung/wiederherstellen/?klon=1"), None)
        self.assertTrue(kontext["klon"])
        kontext, _ = self._seite(RequestFactory().get("/einrichtung/wiederherstellen/"), None)
        self.assertFalse(kontext["klon"])

    def test_klon_merkt_sich_seine_adresse(self):
        from django.test import RequestFactory
        anfrage = RequestFactory().post("/einrichtung/wiederherstellen/", {"aktion": "einspielen"},
                                        HTTP_HOST="localhost:8001")
        zustand = {"phase": "empfangen", "geraet": "ALT", "klon": True}
        kontext, geschrieben = self._seite(anfrage, zustand)
        self.assertEqual(geschrieben[-1]["phase"], "bereit")
        self.assertEqual(geschrieben[-1]["klon_url"], "http://localhost:8001")
        self.assertTrue(kontext["klon"])
        self.assertEqual(kontext["eigene_id"], "NEUE-ID")
        # Ohne Klon bleibt die Adresse leer — VEREINS_URL kommt dann aus der Sicherung.
        _, geschrieben = self._seite(anfrage, {**zustand, "klon": False})
        self.assertEqual(geschrieben[-1]["klon_url"], "")

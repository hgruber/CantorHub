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
from intern.aufstellung import aufstellung
from intern.blob_aufraeumen import verwaiste_pfade, zugeordnetes_verzeichnis
from intern.forms import SchnellSelect, SchnellSelectMultiple
from intern.middleware import muss_auffrischen
from intern.tables2_beschleunigung import (
    _original as tables2_original, attrs_gepuffert, signature_gepuffert,
)
from intern.mailingliste import faelligkeit, faellige_erinnerungen, parse_wochen
from intern.templatetags.termin_tags import zeitraum_bis
from intern.terminzeit import countdown_text, ist_ganztaegig, kommende_q
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
        # Ohne DB und ohne env bleibt es beim Frankfurt-Fallback.
        from intern.app_settings import get_map_center
        with mock.patch.dict("os.environ", {}, clear=False):
            self.assertEqual(get_map_center(), (50.1109, 8.6821))

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

    def test_audio_leiste(self):
        markup = self._leiste("Song.mp3")
        self.assertIn('class="wiki-player wiki-player--audio"', markup)
        self.assertIn('data-typ="audio"', markup)
        self.assertIn('data-url="/media/Song.mp3"', markup)
        self.assertIn("mp-progress-bar", markup)
        self.assertIn('class="mp-title">Song<', markup)
        self.assertIn('class="mp-type">MP3<', markup)
        self.assertNotIn("<video", markup)

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
        markup = self._leiste("Song.mp3")
        self.assertNotIn("<div", markup)
        self.assertNotIn("<figure", markup)
        self.assertNotIn("\n", markup)

    def test_ueberlebt_die_nachfolgenden_regeln(self):
        """''kursiv'', ""zitat"" und $roh$ laufen nach dieser Ersetzung."""
        markup = self._leiste("Song.mp3")
        self.assertNotIn("'", markup)
        self.assertNotIn('""', markup)
        self.assertNotIn("$", markup)

    def test_anfuehrungszeichen_im_dateinamen(self):
        markup = self._leiste('a"b.mp3')
        self.assertIn("&quot;", markup)
        # Das Attribut bleibt heil: nach data-url folgt genau ein schließendes ".
        self.assertIn('data-url="/media/a&quot;b.mp3"', markup)

    def test_label_ueberschreibt_den_titel(self):
        from intern.replacements import insert_file_object
        markup = insert_file_object(_datei("Song.mp3"), "Mein Titel", spieler=True)
        self.assertIn('class="mp-title">Mein Titel<', markup)

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
        out = self._rendern("Hier: [[Datei:Song.mp3]] und Ende", _datei("Song.mp3"))
        self.assertIn('<p>Hier: <span class="wiki-player', out)
        self.assertIn("und Ende</p>", out)

    def test_label_wird_ausgewertet(self):
        out = self._rendern("[[Datei:Song.mp3|Mein Titel]]", _datei("Song.mp3"))
        self.assertIn('class="mp-title">Mein Titel<', out)

    def test_fehlende_datei_unveraendert(self):
        out = self._rendern("[[Datei:fehlt.mp3]]", None)
        self.assertIn('class="not_found"', out)
        self.assertNotIn("wiki-player", out)

    def test_forum_ohne_player(self):
        out = self._rendern(
            "[[Datei:Song.mp3]]", _datei("Song.mp3"), request=False
        )
        self.assertNotIn("wiki-player", out)
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


class StartseitenExternTest(SimpleTestCase):
    """Das Kriterium der Startseite ist ein nicht-leerer Ankündigungstext.

    Die beiden Leerformen sehen redundant aus und sind es nicht: Django setzt
    bei der Negation auf einer nullable-Spalte ein ``IS NOT NULL`` in die
    Bedingung (``NOT (extern = '' AND extern IS NOT NULL)``), ein
    ``NULL``-Datensatz überlebt ``exclude(extern="")`` also. Der Test pinnt
    genau diese Regel, damit sie nicht wegoptimiert wird.
    """

    def test_beide_leerformen_zaehlen(self):
        from intern.views.auth import _OHNE_ANKUENDIGUNG

        self.assertEqual(_OHNE_ANKUENDIGUNG, Q(extern__isnull=True) | Q(extern=""))


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
            mitglieder._rundmail_versenden("user", "Betreff", "Text", empfaenger, [], "", [])
        conn.open.assert_called()
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


class StandardOrdnerTest(SimpleTestCase):
    """intern.folders: die Standard-Ordner liegen unter Backstage und werden
    ab der Wurzel über ihren ganzen Pfad gesucht."""

    def setUp(self):
        from intern import folders
        folders.invalidate()
        self.addCleanup(folders.invalidate)

    def test_alles_unter_backstage_ausser_eingang_und_mitglieder_verwaltung(self):
        from intern import folders
        an_der_wurzel = {
            "backstage": (folders.BACKSTAGE,),
            "unsortiert": (folders.EINGANG,),
            "mitglieder_verwaltung": (folders.MITGLIEDER_VERWALTUNG,),
        }
        for schluessel, pfad in folders.PFADE.items():
            if schluessel in an_der_wurzel:
                self.assertEqual(pfad, an_der_wurzel[schluessel])
            else:
                self.assertEqual(pfad[0], folders.BACKSTAGE, schluessel)
                self.assertGreater(len(pfad), 1, schluessel)

    def test_pfade_eindeutig_und_eltern_zuerst(self):
        """0003_import legt die Ordner in dieser Reihenfolge an."""
        from intern import folders
        pfade = list(folders.PFADE.values())
        self.assertEqual(len(pfade), len(set(pfade)))
        for i, pfad in enumerate(pfade):
            if len(pfad) > 1:
                self.assertIn(pfad[:-1], pfade[:i], pfad)

    def test_jede_zugriffsfunktion_hat_einen_pfad(self):
        from intern import folders
        for schluessel in folders.PFADE:
            self.assertTrue(callable(getattr(folders, schluessel)), schluessel)

    def test_sucht_jede_ebene_mit_ihrem_elternordner(self):
        from intern import folders
        ids = {
            (folders.BACKSTAGE, None): 1,
            (folders.REPERTOIRE, 1): 2,
            (folders.NOTENBLAETTER, 2): 3,
        }

        def filter_(name, parent_id):
            pk = ids.get((name, parent_id))
            return mock.Mock(first=lambda: SimpleNamespace(pk=pk) if pk else None)

        with mock.patch("filer.models.Folder.objects") as objects:
            objects.filter.side_effect = filter_
            self.assertEqual(folders.pdf(), 3)
            self.assertEqual(objects.filter.call_count, 3)
            # Zweiter Aufruf kommt aus dem Cache.
            self.assertEqual(folders.pdf(), 3)
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

    def test_filter_bietet_die_antworten_plus_sentinel(self):
        """Der Statusfilter zeigt genau die Antworten (ohne „keine Angabe", denn
        eine leere Auswahl filtert nicht) plus ``"0"`` = „nicht geantwortet"."""
        from intern import zusage
        from intern.tables import MitgliederFilter

        choices = MitgliederFilter.base_filters["status"].extra["choices"]
        self.assertEqual([wert for wert, _ in choices], ["1", "2", "3", "0"])
        erwartet = {wert: label for wert, label in zusage.OPTION_LABELS.items() if wert}
        erwartet["0"] = "keine Auswahl"
        self.assertEqual(dict(choices), erwartet)


class RepertoireSucheTest(SimpleTestCase):
    """Die Suche der Titelliste greift über Titel, Komponist und Bearbeiter.

    Das QuerySet wird nie ausgewertet — der ``method=``-Filter liefert ein
    faules QuerySet, geprüft wird das kompilierte SQL.
    """

    def _query(self, wert):
        from intern.models import Lied
        from intern.tables import RepertoireFilter

        return RepertoireFilter().filter_suche(Lied.objects.all(), "titel", wert)

    def test_suche_umfasst_komponist_und_bearbeiter(self):
        sql = str(self._query("bach").query)
        for spalte in ("titel", "komponist", "bearbeiter"):
            self.assertIn(f'"{spalte}" LIKE', sql)

    def test_leere_suche_filtert_nicht(self):
        from intern.models import Lied

        self.assertEqual(
            str(self._query("").query), str(Lied.objects.all().query)
        )

    def test_filter_bleibt_benannt_und_beschriftet(self):
        """Parameter und Label bleiben wie bisher, damit alte Links und die
        gemerkten Filter je Seite weiter greifen."""
        from intern.tables import RepertoireFilter

        feld = RepertoireFilter.base_filters["titel"]
        self.assertEqual(feld.label, "Suche")
        self.assertEqual(feld.method, "filter_suche")


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
    ``_LIED_FELDER``, ``_FILE_ID_FIELDS``). Ein Feldname darin ist eine
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

    def test_lied_felder_gibt_es_am_modell(self):
        from intern.models import Lied
        from intern.verwendung import _LIED_FELDER

        vorhanden = self._feldnamen(Lied)
        self.assertEqual([f for f in _LIED_FELDER if f not in vorhanden], [])

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
        from intern import tables, verwendung
        from intern.views import aenderungen

        karten = [
            (aenderungen, "FIELD_LABELS"),
            (aenderungen, "MODEL_LABELS"),
            (aenderungen, "_MODELL_FELD_LABELS"),
            (tables, "_CHANGELOG_FIELD_LABELS"),
            (tables, "_CHANGELOG_MODEL_LABELS"),
            (verwendung, "_LIED_FELDER"),
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
        for verzeichnis in (wurzel / "intern" / "templates", wurzel / "templates"):
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
    """``CHANGELOG.md`` in genau der Form, auf die der ``update``-Hook parst.

    Das Bare-Repo nimmt ein Versions-Tag nur an, wenn der getaggte Commit einen
    gefüllten Abschnitt für diese Version trägt (``update.sh``). Der Hook
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


class FarbTokenTest(SimpleTestCase):
    """Jede Farbe ist ein Custom Property mit einem ``[data-theme="dark"]``-Wert.

    Die Regel steht in ``CLAUDE.md``, war aber bisher von keinem Test gedeckt —
    ein im Dark-Block vergessenes Token fällt sonst erst dem Mitglied auf, das
    nachts ins Portal schaut, und auch dann nur als „sieht komisch aus".
    Geprüft werden die Stimmpalette, die Kategorienpalette und die
    Ampel-Familie; der Aufbau trägt jede weitere Familie, die dazukommt.

    Absichtlich *nicht* geprüft: dass der Dark-Wert ein anderer ist. ``--brand``
    ist in beiden Themes derselbe und ``--aufst-eventuell`` ebenfalls — beides
    ist so gewollt.
    """

    PRAEFIXE = ("--stimme-", "--kat-", "--status-")
    DEKLARATION = re.compile(r"^\s*(--[a-z0-9-]+)\s*:", re.MULTILINE)

    #: Absichtlich themenunabhängig. Der Ampel-Vollton ist die kräftige Füllung
    #: für Hover- und Aktiv-Zustände und trägt dort weißen Text; er bleibt in
    #: beiden Themes derselbe, während bg/text/border im Dark-Block weicher
    #: werden. Steht so in docs/frontend.md, Abschnitt „Status (Ampel) colours".
    #: Wer hier etwas einträgt, nimmt es aus der Prüfung — also nur mit Grund.
    OHNE_DARK_WERT = {
        "--status-success-solid",
        "--status-warning-solid",
        "--status-danger-solid",
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

"""Tests der Auftritts-Mailingliste und kleiner reiner Helfer.

Bewusst ohne Datenbank: die Zeitlogik ist rein, ``jetzt`` wird übergeben.
Für Termine reicht ein winziges Stellvertreter-Objekt — ``faelligkeit`` und
``faellige_erinnerungen`` lesen nur ``datum``.
"""

import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from unittest import mock

from django.core.signals import request_finished, request_started
from django.db.models import Q
from django.template import Context, Template
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils.html import escape
from django.utils.timesince import timeuntil

from intern import app_settings
from intern.aufstellung import aufstellung
from intern.middleware import muss_auffrischen
from intern.tables2_beschleunigung import _original as tables2_original, signature_gepuffert
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

    FELDER = ("anwesenheit", "repertoire")

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
        from intern.models import PRIVACY_FIELDS

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

    def test_select_optionen_sind_gueltig_und_vollstaendig(self):
        # Jeder select-Typ braucht eine nicht-leere Optionliste in SELECT_OPTIONEN,
        # und jeder Optionwert muss eine gültige IANA-Zone sein — sonst rendert das
        # Template ein leeres Dropdown oder daten.zeitzone() schlägt fehl.
        from zoneinfo import available_timezones
        from intern.konfig_gruppen import FELDTYPEN, SELECT_OPTIONEN
        zonen = available_timezones()
        for key, typ in FELDTYPEN.items():
            if typ != "select":
                continue
            self.assertIn(
                key, SELECT_OPTIONEN,
                msg=f"select-Schlüssel {key!r} fehlt in SELECT_OPTIONEN",
            )
            optionen = SELECT_OPTIONEN[key]
            self.assertGreater(len(optionen), 0, msg=f"{key!r} hat keine Optionen")
            for wert, _label in optionen:
                self.assertIn(wert, zonen, msg=f"{key!r}: {wert!r} ist keine IANA-Zone")

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

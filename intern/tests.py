"""Tests der Auftritts-Mailingliste und kleiner reiner Helfer.

Bewusst ohne Datenbank: die Zeitlogik ist rein, ``jetzt`` wird übergeben.
Für Termine reicht ein winziges Stellvertreter-Objekt — ``faelligkeit`` und
``faellige_erinnerungen`` lesen nur ``datum``.
"""

from datetime import datetime, time, timedelta
from types import SimpleNamespace

from django.template import Context, Template
from django.test import SimpleTestCase
from django.utils.html import escape

from intern.mailingliste import faelligkeit, faellige_erinnerungen, parse_wochen
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

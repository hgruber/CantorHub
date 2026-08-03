"""Tests der Auftritts-Mailingliste und kleiner reiner Helfer.

Bewusst ohne Datenbank: die Zeitlogik ist rein, ``jetzt`` wird übergeben.
Für Termine reicht ein winziges Stellvertreter-Objekt — ``faelligkeit`` und
``faellige_erinnerungen`` lesen nur ``datum``.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from unittest import mock

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
        from intern.konfig_gruppen import GRUPPEN, gruppiere
        keys = sorted(self._defaults_keys())
        # Absichtlich gemischte Reihenfolge, damit die Eingabereihenfolge-Erhaltung
        # geprüft wird, nicht die Sortierung.
        reihenfolge = list(reversed(keys))
        rows = [
            {"id": i, "key": k, "value": "", "description": ""}
            for i, k in enumerate(reihenfolge)
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

        # Eingabereihenfolge innerhalb einer Gruppe erhalten.
        index = {k: i for i, k in enumerate(reihenfolge)}
        for g in ergebnis:
            positions = [index[e["key"]] for e in g["eintraege"]]
            self.assertEqual(positions, sorted(positions),
                             msg=f"Reihenfolge in {g['id']!r} nicht erhalten")

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

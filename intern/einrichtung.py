"""Die Ersteinrichtung einer neuen Installation.

Jede Installation läuft durch dieselbe Migrationskette. Eine neue erreicht den
Schemastand per ``migrate`` (``0003_import`` ist dort leer) — die Grunddaten, die
die erste Installation aus dem Altimport hat, legt diese Ersteinrichtung an:
Gruppen mit ihren Rechten, die Standardordner, das Vorstand-Recht auf dem
Vorstand-Ordner, das erste Konto und die ersten Kenngrößen.

Solange es keinen Superuser gibt, leitet ``middleware.Ersteinrichtung`` jede
Anfrage auf ``/einrichtung/``. Wer sie zuerst abschließt, wird Administrator —
gewollt: eine neue Installation soll ohne weiteren Schritt erreichbar sein.

Oben die reinen Entscheidungen (``SimpleTestCase``), darunter der DB-Teil.
"""

import logging

logger = logging.getLogger(__name__)

# Die Gruppen einer neuen Installation, mit ihren Rechten. Der Stand des
# Altimports, damit jede Installation dieselben Gruppen hat; danach werden sie
# nur noch unter /intern/gruppen/ gepflegt.
GRUPPEN = {
    "Vorstand": [
        ("intern", "add_user"),
        ("intern", "change_user"),
        ("intern", "add_termin"),
        ("intern", "change_termin"),
        ("intern", "delete_termin"),
    ],
    "Kassenprüfer": [],
    "Webmaster": [
        ("intern", "delete_user"),
        ("intern", "delete_folder"),
        ("intern", "manage_folder_permissions"),
        ("intern", "add_artikel"),
        ("intern", "change_artikel"),
        ("intern", "delete_artikel"),
        ("intern", "manage_artikel_permissions"),
        ("intern", "add_forum"),
        ("intern", "change_forum"),
        ("intern", "delete_forum"),
        ("intern", "manage_forum_permissions"),
    ],
    "Termine": [
        ("intern", "add_termin"),
        ("intern", "change_termin"),
        ("intern", "delete_termin"),
    ],
    "KonzertOrga": [
        ("intern", "add_termin"),
        ("intern", "change_termin"),
        ("intern", "delete_termin"),
        ("intern", "add_lied"),
        ("intern", "change_lied"),
        ("intern", "delete_lied"),
        ("intern", "add_ort"),
        ("intern", "change_ort"),
        ("intern", "delete_ort"),
    ],
    "Anwesenheit": [
        ("intern", "change_zusage"),
    ],
    # Die Vereinsmitgliedschaft (siehe ``intern/mitgliedschaft.py``), das Etikett
    # neben ``is_active`` — und Träger der Rechte, die jedes Mitglied hat.
    "Mitglied": [
        ("intern", "notify_user"),
        ("intern", "add_ort"),
        ("intern", "change_ort"),
        ("intern", "delete_ort"),
    ],
    # Nur Etiketten.
    "Gründer": [],
    "Fördermitglied": [],
    "kein Bild": [],
    "DSGVO": [],
}

GRUPPE_VORSTAND = "Vorstand"

# Die Spalten, die eine Tabelle zeigt, solange ein Mitglied keine eigene Auswahl
# getroffen hat (``TabellenPreferenzen`` ohne Person). Ohne Vorgabe zeigten
# Mitgliederliste und Repertoire keine einzige Spalte.
TABELLEN_VORGABEN = {
    "MitgliederTabelle": ["first_name", "last_name", "stimme"],
    "RepertoireTabelle": ["titel", "eigenschaften", "pdf", "noten"],
}

# Was vor dem Abschluss erreichbar bleibt: die Seite selbst und ihr CSS.
EINRICHTUNG_FREI = ("/einrichtung/", "/static/")

# Verschlüsselung des SMTP-Zugangs → (EMAIL_USE_TLS, EMAIL_USE_SSL).
SMTP_VERSCHLUESSELUNG = {
    "": ("0", "0"),
    "starttls": ("1", "0"),
    "ssl": ("0", "1"),
}


def pfad_frei(pfad):
    """Darf eine Anfrage auf ``pfad`` vor dem Abschluss durch?"""
    return pfad.startswith(EINRICHTUNG_FREI)


def smtp_konfiguration(host, port, benutzer, passwort, verschluesselung):
    """Die ``Konfiguration``-Werte des SMTP-Zugangs; ohne Host keine."""
    if not host:
        return {}
    tls, ssl = SMTP_VERSCHLUESSELUNG[verschluesselung]
    return {
        "EMAIL_HOST": host,
        "EMAIL_PORT": str(port or 587),
        "EMAIL_HOST_USER": benutzer,
        "EMAIL_HOST_PASSWORD": passwort,
        "EMAIL_USE_TLS": tls,
        "EMAIL_USE_SSL": ssl,
    }


# ── „Aktuell" und Beispieldaten ──────────────────────────────────────────────

# Die Seite nach dem Login. Ohne sie landete jedes Mitglied im Editor; anlegen
# darf sie deshalb jede Einrichtung, bearbeiten nur diese Gruppen.
ARTIKEL_AKTUELL = "Aktuell"
AKTUELL_SCHREIBGRUPPEN = ("Webmaster", GRUPPE_VORSTAND, "KonzertOrga")

AKTUELL_TEXT = (
    "== Willkommen im Mitgliederportal ==\n\n"
    "Diese Seite sehen alle Mitglieder nach der Anmeldung. Hier steht, was gerade "
    "wichtig ist: die nächste Probe, ein Konzert, eine Bitte an alle.\n\n"
    "Bearbeiten dürfen sie Webmaster, Vorstand und KonzertOrga.\n\n"
    "@ '''Neu hier?''' Unter [[Hilfe]] steht Schritt für Schritt, wie das Portal "
    "funktioniert — und wie Termine, Kontakte und der Chat aufs Telefon kommen.\n"
)

AKTUELL_TEXT_BEISPIELE = AKTUELL_TEXT + (
    "\n=== Zum Ausprobieren ===\n\n"
    "Bei der Einrichtung sind Beispieldaten entstanden:\n"
    "* einige Volkslieder im Repertoire,\n"
    "* wöchentliche Proben und ein Konzert mit Ablauf unter „Termine“,\n"
    "* das Forum „Allgemeines“ mit einem ersten Beitrag.\n\n"
    "Sie lassen sich wie alle anderen Einträge ändern oder löschen.\n"
)

BEISPIEL_ORT = {
    "name": "Probenraum",
    "beschreibung": "Beispielort der Ersteinrichtung — bitte anpassen.",
    "strasse": "Musterstraße 1",
    "plz": "12345",
    "ort": "Musterstadt",
}

# Gemeinfreie deutsche Volkslieder: (titel, komponist, bearbeiter, tonart, tempo, weihnacht)
BEISPIEL_LIEDER = (
    ("Kein schöner Land", "volkstümlich; Text: Anton Wilhelm von Zuccalmaglio",
     "", "G", "l", False),
    ("Der Mond ist aufgegangen", "Johann Abraham Peter Schulz; Text: Matthias Claudius",
     "", "F", "l", False),
    ("Die Gedanken sind frei", "volkstümlich", "", "F", "m", False),
    ("Am Brunnen vor dem Tore", "Franz Schubert; Text: Wilhelm Müller",
     "Friedrich Silcher", "E", "l", False),
    ("Ännchen von Tharau", "Friedrich Silcher; Text: Simon Dach", "", "F", "m", False),
    ("Das Wandern ist des Müllers Lust", "Carl Friedrich Zöllner; Text: Wilhelm Müller",
     "", "C", "s", False),
    ("Stille Nacht, heilige Nacht", "Franz Xaver Gruber; Text: Joseph Mohr",
     "", "Bb", "l", True),
)

# Der Ablauf des Beispielkonzerts: Positionen in BEISPIEL_LIEDER.
KONZERT_ABLAUF = (0, 2, 4, 3, 5, 1)

PROBEN_ANZAHL = 6
PROBEN_WOCHENTAG = 1        # Dienstag
PROBEN_BEGINN = (19, 30)
PROBEN_DAUER_MIN = 120
KONZERT_IN_WOCHEN = 8
KONZERT_WOCHENTAG = 5       # Samstag
KONZERT_BEGINN = (18, 0)
KONZERT_DAUER_MIN = 120


def _naechster(tag, wochentag):
    """Der nächste ``wochentag`` nach ``tag`` (ein Datum, nie ``tag`` selbst)."""
    from datetime import timedelta

    return tag + timedelta(days=(wochentag - tag.weekday() - 1) % 7 + 1)


def beispieltermine(jetzt):
    """Die Beispieltermine ab ``jetzt``: Proben und ein Konzert, als Felder je Termin."""
    from datetime import datetime, timedelta

    def zeit(tag, beginn, dauer):
        anfang = datetime.combine(tag, datetime.min.time()).replace(
            hour=beginn[0], minute=beginn[1]
        )
        return anfang, anfang + timedelta(minutes=dauer)

    termine = []
    erste_probe = _naechster(jetzt.date(), PROBEN_WOCHENTAG)
    for woche in range(PROBEN_ANZAHL):
        datum, bis = zeit(
            erste_probe + timedelta(weeks=woche), PROBEN_BEGINN, PROBEN_DAUER_MIN
        )
        termine.append({
            "datum": datum, "datum_bis": bis, "kurz": "Chorprobe",
            "lang": "Wöchentliche Probe.", "anwesenheit": True,
            "repertoire": False, "extern": "",
        })

    konzerttag = _naechster(
        jetzt.date() + timedelta(weeks=KONZERT_IN_WOCHEN - 1), KONZERT_WOCHENTAG
    )
    datum, bis = zeit(konzerttag, KONZERT_BEGINN, KONZERT_DAUER_MIN)
    termine.append({
        "datum": datum, "datum_bis": bis, "kurz": "Konzert",
        "lang": "Unser Beispielkonzert mit Volksliedern.",
        "anwesenheit": True, "repertoire": True,
        "extern": "Wir singen deutsche Volkslieder — vom Abendlied bis zum "
        "Wanderlied. Der Eintritt ist frei.",
    })
    return termine


# ── Erlaubte Hostnamen ────────────────────────────────────────────────────────
# Ohne konfigurierte Portaladresse kennt Django den Namen nicht, unter dem das
# Portal aufgerufen wird, und beantwortete jede Anfrage mit 400. Bis zur
# Einrichtung ist deshalb jeder Name zugelassen; die Adresse ergibt sich aus dem
# ersten Aufruf und wird dort vorbelegt.

OFFENE_HOSTS = ["*"]


def hosts_offen():
    from django.conf import settings

    return settings.ALLOWED_HOSTS == OFFENE_HOSTS


def hosts_oeffnen():
    from django.conf import settings

    settings.ALLOWED_HOSTS = list(OFFENE_HOSTS)


def hosts_festlegen(url=None):
    """``ALLOWED_HOSTS``/``CSRF_TRUSTED_ORIGINS`` aus der Portaladresse.

    Ohne ``url`` gilt die konfigurierte. Ist auch die leer, bleiben nur die
    lokalen Namen — wie vor der Ersteinrichtung üblich, jetzt aber mit Hinweis.
    """
    from django.conf import settings

    from config.datenbank import hosts_aus_url

    from .app_settings import get_base_url

    if url is None:
        url = get_base_url()
    settings.ALLOWED_HOSTS, settings.CSRF_TRUSTED_ORIGINS = hosts_aus_url(url)
    if not url:
        logger.warning(
            "VEREINS_URL ist nicht konfiguriert: es gelten nur localhost und "
            "127.0.0.1, Zugriffe unter dem echten Hostnamen beantwortet Django "
            "mit 400. Die Adresse unter /intern/konfiguration/ eintragen."
        )


# ── Datenbank ─────────────────────────────────────────────────────────────────

_eingerichtet = False


def ist_eingerichtet():
    """Gibt es einen Superuser? Ein einmal ``True`` bleibt im Prozess gemerkt."""
    global _eingerichtet
    if not _eingerichtet:
        from .models import User

        _eingerichtet = User.objects.filter(is_superuser=True).exists()
    return _eingerichtet


class BereitsEingerichtet(Exception):
    """Ein zweiter Abschluss — etwa zwei gleichzeitige Absendungen."""


def einrichten(*, konto, passwort, konfiguration, jetzt, beispieldaten=False):
    """Grunddaten anlegen und das erste Konto zurückgeben.

    ``konto``: Felder des Benutzers (username, first_name, last_name, email);
    ``konfiguration``: ``{key: value}`` für die ``Konfiguration``-Tabelle;
    ``beispieldaten``: Ort, Lieder, Termine und ein Forum zum Ausprobieren.
    Die Hilfe-Artikel (``intern/hilfe/``) kommen immer dazu.
    """
    global _eingerichtet
    from django.apps import apps
    from django.contrib.auth.management import create_permissions
    from django.contrib.auth.models import Group, Permission
    from django.contrib.contenttypes.management import create_contenttypes
    from django.db import transaction

    from . import folders, hilfe
    from .mitgliedschaft import GRUPPE_MITGLIED
    from .models import FolderPermission, Konfiguration, TabellenPreferenzen, User

    with transaction.atomic():
        if User.objects.select_for_update().filter(is_superuser=True).exists():
            raise BereitsEingerichtet

        # Die Permission-Zeilen legt sonst erst post_migrate an; hier sicherstellen.
        for app_config in apps.get_app_configs():
            create_contenttypes(app_config, verbosity=0)
            create_permissions(app_config, verbosity=0)

        gruppen = {}
        for name, rechte in GRUPPEN.items():
            gruppe, _ = Group.objects.get_or_create(name=name)
            for app_label, codename in rechte:
                recht = Permission.objects.filter(
                    codename=codename, content_type__app_label=app_label
                ).first()
                if recht:
                    gruppe.permissions.add(recht)
            gruppen[name] = gruppe

        folders.invalidate()
        folders.anlegen_alle()
        # Ohne diese Zeile wären die Mitgliedsanträge für alle lesbar.
        FolderPermission.objects.get_or_create(
            folder_id=folders.vorstand(),
            group=gruppen[GRUPPE_VORSTAND],
            defaults={"can_read": True, "can_write": True, "can_delete": True},
        )

        for tabelle, spalten in TABELLEN_VORGABEN.items():
            if not TabellenPreferenzen.objects.filter(person=None, tabelle=tabelle).exists():
                TabellenPreferenzen.objects.create(
                    person=None, tabelle=tabelle, sichtbare_spalten=spalten
                )

        nutzer = User(
            **konto,
            is_active=True,
            is_staff=True,
            is_superuser=True,
            date_joined=jetzt,
        )
        nutzer.set_password(passwort)
        nutzer.save()
        nutzer.groups.add(gruppen[GRUPPE_MITGLIED], gruppen[GRUPPE_VORSTAND])

        for key, value in konfiguration.items():
            Konfiguration.objects.update_or_create(key=key, defaults={"value": value})

        _aktuell_anlegen(
            nutzer, jetzt, AKTUELL_TEXT_BEISPIELE if beispieldaten else AKTUELL_TEXT,
            [gruppen[name] for name in AKTUELL_SCHREIBGRUPPEN],
        )
        _ersatzavatare_anlegen(nutzer)
        hilfe.anlegen(nutzer, jetzt)
        if beispieldaten:
            _beispieldaten_anlegen(nutzer, jetzt)

    _eingerichtet = True
    return nutzer


def _aktuell_anlegen(nutzer, jetzt, text, schreibgruppen):
    from .models import Artikel, ArtikelPermission

    Artikel.objects.create(
        name=ARTIKEL_AKTUELL, version=1, datum=jetzt, autor=nutzer,
        kommentar="Ersteinrichtung", text=text,
    )
    # Nur Schreibzeilen: lesen bleibt für alle offen.
    for gruppe in schreibgruppen:
        ArtikelPermission.objects.create(
            artikel_name=ARTIKEL_AKTUELL, group=gruppe, can_edit=True
        )


# Die Bilder, die das Portal zeigt, wo ein Profilbild fehlt
# (``avatare.fallback_avatar_datei``): ein Mitglied ohne Foto und der XMPP-Bot.
ERSATZAVATARE = ("kein_photo.png", "bot.png")


def _ersatzavatare_anlegen(nutzer):
    from pathlib import Path

    from django.core.files.base import ContentFile

    from . import dateiablage, folders

    ordner = folders.avatare()
    quelle = Path(__file__).resolve().parent / "avatare_ersatz"
    for name in ERSATZAVATARE:
        if dateiablage.gleichnamige(ordner, name) is None:
            dateiablage.systemablage_inhalt(
                ContentFile((quelle / name).read_bytes(), name=name), ordner, name,
                nutzer, mime="image/png",
            )


def _beispieldaten_anlegen(nutzer, jetzt):
    from .models import Forum, Konzert, Lied, Mitteilung, Ort, Termin

    ort = Ort.objects.create(**BEISPIEL_ORT)
    lieder = [
        Lied.objects.create(
            titel=titel, komponist=komponist, bearbeiter=bearbeiter or None,
            tonart=tonart, tempo=tempo, weihnacht=weihnacht, aktiv=True,
        )
        for titel, komponist, bearbeiter, tonart, tempo, weihnacht in BEISPIEL_LIEDER
    ]
    for felder in beispieltermine(jetzt):
        termin = Termin.objects.create(ort=ort, **felder)
        if termin.repertoire:
            for position, index in enumerate(KONZERT_ABLAUF, start=1):
                Konzert.objects.create(
                    termin=termin, lied=lieder[index], position=position
                )

    forum = Forum.objects.create(thema="Allgemeines")
    Mitteilung.objects.create(
        forum=forum, sender=nutzer, datum=jetzt,
        mitteilung="Willkommen im Forum! Hier ist Platz für alles, was den ganzen "
        "Chor angeht.",
    )

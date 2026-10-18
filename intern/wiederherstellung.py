"""Eine neue Installation aus einer Syncthing-Sicherung wiederherstellen.

Gegenstück zu ``intern/sicherung.py``, eingestiegen wird über die
Ersteinrichtung (``/einrichtung/wiederherstellen/``, solange es keinen
Superuser gibt). Der Ablauf:

1. **empfangen** — der Syncthing-Ordner nimmt im Empfangsordner
   ``DATEN/wiederherstellung/`` an, was ein Speichergerät hat
   (``syncthing.empfang_beginnen``). Diese Installation hat eine neue
   Geräte-ID; die alte steckt bewusst nicht in der Sicherung.
2. **bereit** — der Admin hat „Wiederherstellen“ geklickt, der Container
   startet neu. Neu starten muss er, weil der ``secret_key`` zurückkommt:
   Medien-Links im XMPP-Verlauf und Abmelde-Links hängen daran.
3. ``einspielen()`` läuft in ``start.sh`` vor ``migrate`` und vor jedem
   Dienst: Arbeitskopie der Datenbank aufs aktuelle Schema heben, Zeile für
   Zeile in die Portal-Datenbank (dieselbe Routine wie die Sicherung), dann die
   Dateien an ihren Platz, dann den Syncthing-Ordner offline zum normalen
   Sendeordner umstellen. Das Speichergerät sichert danach ohne Zutun weiter.
   Zum Schluss ist nichts mehr übrig: kein Empfangsordner, keine Zustandsdatei.

Scheitert ein Schritt vor den Dateien, rollt die Datenbank zurück, der Zustand
wird **fehler** mit der Ursache, und der Start läuft normal weiter — die Seite
zeigt den Fehler, das Empfangene bleibt für einen zweiten Versuch.
"""

import json
import logging
import os
import shutil
import sqlite3
from pathlib import Path

from .sicherung import DATEINAME, STANDDATEI

logger = logging.getLogger(__name__)

ALIAS = "wiederherstellung"
ORDNER = "wiederherstellung"
ZUSTANDSDATEI = "wiederherstellung.json"
ARBEITSKOPIE = "wiederherstellung.sqlite3"

EMPFANGEN = "empfangen"
BEREIT = "bereit"
FEHLER = "fehler"

# Was im Empfangsordner liegt, aber nicht ins Datenverzeichnis gehört — oder dort
# nie ersetzt werden darf: Schlüssel und Index dieses Syncthing, der Kachelcache,
# eine laufende SQLite-Datenbank.
_NICHT_UEBERNEHMEN = frozenset({
    ".stfolder", ".stversions", ".stignore", "syncthing", "tiles",
    ORDNER, ZUSTANDSDATEI, ARBEITSKOPIE,
})


def datenverzeichnis():
    from django.conf import settings

    return Path(settings.DATEN).resolve()


def empfangsordner():
    return datenverzeichnis() / ORDNER


def lese_zustand():
    try:
        return json.loads((datenverzeichnis() / ZUSTANDSDATEI).read_text())
    except (OSError, ValueError):
        return None


def schreibe_zustand(**werte):
    pfad = datenverzeichnis() / ZUSTANDSDATEI
    tmp = pfad.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(werte, ensure_ascii=False))
    tmp.replace(pfad)


def zustand_loeschen():
    (datenverzeichnis() / ZUSTANDSDATEI).unlink(missing_ok=True)


def bekannte_migrationen():
    """Die Migrationen dieses Abbilds als ``{(app, name)}`` — von der Platte, ohne DB."""
    from django.db.migrations.loader import MigrationLoader

    return set(MigrationLoader(None, ignore_no_migrations=True).disk_migrations)


def pruefen(ordner, bekannt):
    """Taugt das Empfangene zum Einspielen? Fehlertext oder ``None``.

    Ohne Django-Datenbank: die Kopie wird mit ``sqlite3`` nur gelesen.
    """
    ordner = Path(ordner)
    db = ordner / "sicherung" / DATEINAME
    erwartet = (
        (db, "die Datenbank-Kopie"),
        (ordner / "sicherung" / STANDDATEI, "stand.json"),
        (ordner / "secret_key", "der Schlüssel"),
    )
    for pfad, was in erwartet:
        if not pfad.is_file():
            return f"In der Sicherung fehlt {was} ({pfad.relative_to(ordner)})."
    try:
        verbindung = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            if verbindung.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                return "Die Datenbank-Kopie ist beschädigt."
            angewendet = set(verbindung.execute("SELECT app, name FROM django_migrations"))
        finally:
            verbindung.close()
    except sqlite3.Error as fehler:
        return f"Die Datenbank-Kopie lässt sich nicht lesen ({fehler})."
    unbekannt = angewendet - bekannt
    if unbekannt:
        return (
            f"Die Sicherung stammt aus einer neueren Version ({len(unbekannt)} unbekannte "
            "Migrationen). Erst das Abbild auf den neuesten Stand bringen, dann erneut."
        )
    return None


def zusammenfassung(ordner):
    """Was eingespielt würde: Stand der Sicherung und Umfang der Dateien."""
    ordner = Path(ordner)
    try:
        stand = json.loads((ordner / "sicherung" / STANDDATEI).read_text())
    except (OSError, ValueError):
        stand = {}
    anzahl = groesse = 0
    for wurzel, _, dateien in os.walk(ordner / "media"):
        for name in dateien:
            anzahl += 1
            try:
                groesse += (Path(wurzel) / name).stat().st_size
            except OSError:
                pass
    return {
        "zeitpunkt": str(stand.get("zeitpunkt", "")).replace("T", " ")[:16],
        "version": stand.get("version", ""),
        "zeilen": sum((stand.get("zeilen") or {}).values()),
        "dateien": anzahl,
        "dateien_mb": round(groesse / 1e6, 1),
    }


def _dateien_uebernehmen(ordner, daten):
    """Alles aus dem Empfangsordner an seinen Platz im Datenverzeichnis.

    ``rename`` statt Kopie: gleiches Dateisystem, kein doppelter Platz. Was die
    leere Installation schon angelegt hatte (Demo-Startseite, leeres ``media/``,
    ihr Schlüssel), weicht.
    """
    for eintrag in sorted(ordner.iterdir()):
        name = eintrag.name
        if name in _NICHT_UEBERNEHMEN or name.startswith("db.sqlite3"):
            continue
        ziel = daten / name
        if ziel.is_dir() and not ziel.is_symlink():
            shutil.rmtree(ziel)
        elif ziel.exists() or ziel.is_symlink():
            ziel.unlink()
        eintrag.rename(ziel)
    schluessel = daten / "secret_key"
    if schluessel.is_file():
        schluessel.chmod(0o600)


def einspielen():
    """In start.sh vor ``migrate``: eine bereite Wiederherstellung ausführen.

    Liefert ``True`` nach Erfolg, ``False`` bei Fehler, ``None`` ohne Auftrag.
    """
    from django.core.management import call_command
    from django.db import connections

    from . import syncthing
    from .models import User
    from .sicherung import zeilen_kopieren

    zustand = lese_zustand()
    if not zustand or zustand.get("phase") != BEREIT:
        return None
    daten = datenverzeichnis()
    ordner = empfangsordner()

    def scheitern(text):
        logger.error("Wiederherstellung fehlgeschlagen: %s", text)
        schreibe_zustand(**{**zustand, "phase": FEHLER, "fehler": text})
        return False

    fehler = pruefen(ordner, bekannte_migrationen())
    if fehler:
        return scheitern(fehler)

    arbeitskopie = daten / ARBEITSKOPIE
    try:
        call_command("migrate", verbosity=0, interactive=False)
        # Nie über eine eingerichtete Installation: die Seite ist nur vor der
        # Einrichtung erreichbar, aber der Zustand liegt als Datei im Volume.
        if User.objects.filter(is_superuser=True).exists():
            return scheitern("Diese Installation ist bereits eingerichtet.")
        shutil.copy2(ordner / "sicherung" / DATEINAME, arbeitskopie)
        call_command("migrate", database=ALIAS, verbosity=0, interactive=False)
        zeilen = zeilen_kopieren(ALIAS, "default")
    except Exception as ausnahme:
        logger.exception("Wiederherstellung: Datenbank nicht übernommen")
        return scheitern(f"Die Datenbank ließ sich nicht übernehmen: {ausnahme}")
    finally:
        connections[ALIAS].close()
        arbeitskopie.unlink(missing_ok=True)

    # Ab hier steht die Datenbank; die Dateien folgen, dann Syncthing.
    _dateien_uebernehmen(ordner, daten)
    (daten / ".stfolder").mkdir(exist_ok=True)
    if not syncthing.ordner_umstellen(daten):
        logger.warning("Wiederherstellung: kein Syncthing-Ordner zum Umstellen gefunden")
    shutil.rmtree(ordner, ignore_errors=True)
    zustand_loeschen()
    logger.info(
        "Wiederherstellung abgeschlossen: %d Zeilen aus %d Tabellen; das Gerät %s "
        "sichert ab jetzt weiter", sum(zeilen.values()), len(zeilen),
        (zustand.get("geraet") or "").split("-", 1)[0],
    )
    return True

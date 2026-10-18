"""Der Datenbankstand als SQLite-Datei unter ``DATEN/sicherung/``.

Danach ist das Datenverzeichnis allein das ganze Backup: Uploads samt
Fassungen, Startseite, Schlüssel und diese Kopie. Gestartet mit
``DATABASE_URL=sqlite:////data/sicherung/cantorhub.sqlite3`` ist es ein
lauffähiges Portal; das mitlaufende Syncthing (``start.sh``) spiegelt es auf
ein anderes Gerät. Siehe „Backup" in ``INSTALL.md``.

Zwei Wege, beide konsistent ohne Sperre:

- **SQLite** (frische Installation): die Backup-API von ``sqlite3``.
- **MariaDB** (Produktion): Schema per ``migrate --database=sicherung``, dann
  jede Modelltabelle zeilengleich mit Original-Schlüsseln, gelesen in *einer*
  Transaktion unter ``REPEATABLE READ`` — InnoDB liefert damit einen Stand.
  Geschrieben wird roh per SQL statt über ``save()``/``bulk_create``: keine
  Signale (Änderungsprotokoll, Dateiindex), und filers Mehrtabellen-Erbe ist
  kein Sonderfall, weil jede Tabelle für sich kopiert wird.

Die Kopie entsteht als ``.tmp`` und rückt erst fertig an ihren Platz, damit
Syncthing nie eine halbe Datei verteilt. Dass ``media/`` dabei einen etwas
anderen Stand hat, ist gutartig: eine Datei liegt dort, bevor ihre Zeile
existiert, und wird nie überschrieben (``docs/files.md``).
"""

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

ALIAS = "sicherung"
DATEINAME = "cantorhub.sqlite3"
STANDDATEI = "stand.json"

# Flüchtiges bleibt draussen: Sitzungen wären in einer Kopie auf fremdem Gerät
# ein Risiko, der Cache trägt nur die IP-Drosseln. start.sh legt die
# Cache-Tabelle beim Start der Kopie selbst an.
AUSGELASSEN = frozenset({"django_session", "cache_table"})

_BLOCK = 1000


def faellig(letzter, jetzt, stunden):
    """Steht eine Sicherung an? ``stunden <= 0`` schaltet ab."""
    if stunden <= 0:
        return False
    if letzter is None:
        return True
    return jetzt - letzter >= timedelta(hours=stunden)


def zu_sichernde_modelle(modelle):
    """Die Modelle, deren Tabellen in die Kopie gehören — je Tabelle eines."""
    gesehen = set()
    ergebnis = []
    for model in modelle:
        meta = model._meta
        if not meta.managed or meta.proxy or meta.db_table in AUSGELASSEN:
            continue
        if meta.db_table in gesehen:
            continue
        gesehen.add(meta.db_table)
        ergebnis.append(model)
    return ergebnis


def verzeichnis():
    from django.conf import settings

    return Path(settings.DATEN).resolve() / "sicherung"


def lese_stand(roh):
    """Zeitpunkt der letzten Sicherung aus dem Inhalt von ``stand.json``."""
    try:
        return datetime.fromisoformat(json.loads(roh)["zeitpunkt"])
    except (ValueError, KeyError, TypeError):
        return None


def letzte_sicherung():
    try:
        return lese_stand((verzeichnis() / STANDDATEI).read_text())
    except OSError:
        return None


def _ist_eigene_quelle():
    """Läuft das Portal selbst auf der Kopie (eine wiederhergestellte Sicherung)?

    Dann ersetzte jede Sicherung die Datenbank unter dem laufenden Portal.
    """
    from django.db import connections

    quelle = connections["default"].settings_dict
    if quelle["ENGINE"] != "django.db.backends.sqlite3":
        return False
    return Path(quelle["NAME"]).resolve() == verzeichnis() / DATEINAME


def _sqlite_kopieren(tmp):
    from django.db import connections

    quelle = connections["default"]
    quelle.ensure_connection()
    ziel = sqlite3.connect(tmp)
    try:
        quelle.connection.backup(ziel)
        tabellen = [
            name for (name,) in ziel.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        ]
        zeilen = {}
        for name in tabellen:
            if name in AUSGELASSEN:
                ziel.execute(f'DELETE FROM "{name}"')
            else:
                zeilen[name] = ziel.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        ziel.commit()
        return zeilen
    finally:
        ziel.close()


def _tabelle_kopieren(model, quelle, ziel):
    felder = model._meta.local_concrete_fields
    tabelle = ziel.ops.quote_name(model._meta.db_table)
    spalten = ", ".join(ziel.ops.quote_name(f.column) for f in felder)
    platzhalter = ", ".join(["%s"] * len(felder))
    sql = f"INSERT INTO {tabelle} ({spalten}) VALUES ({platzhalter})"

    zeilen = (
        model._base_manager.using(quelle.alias)
        .order_by("pk")
        .values_list(*(f.attname for f in felder))
        .iterator(chunk_size=_BLOCK)
    )
    anzahl = 0
    block = []
    with ziel.cursor() as cursor:
        cursor.execute(f"DELETE FROM {tabelle}")
        for zeile in zeilen:
            block.append([
                feld.get_db_prep_save(wert, connection=ziel)
                for feld, wert in zip(felder, zeile)
            ])
            if len(block) >= _BLOCK:
                cursor.executemany(sql, block)
                anzahl += len(block)
                block = []
        if block:
            cursor.executemany(sql, block)
            anzahl += len(block)
    return anzahl


def zeilen_kopieren(quelle_alias, ziel_alias):
    """Jede Modelltabelle von ``quelle_alias`` zeilengleich nach ``ziel_alias``.

    Beide Schemata müssen übereinstimmen (vorher ``migrate``). Im Ziel wird
    jede Tabelle erst geleert. Die Sicherung kopiert so in die Kopie, die
    Wiederherstellung (``intern/wiederherstellung.py``) aus ihr zurück.
    """
    from django.apps import apps
    from django.db import connections, transaction

    quelle = connections[quelle_alias]
    ziel = connections[ziel_alias]
    modelle = zu_sichernde_modelle(apps.get_models(include_auto_created=True))

    if quelle.vendor == "mysql":
        # Django verbindet mit READ COMMITTED; nur REPEATABLE READ hält den
        # Stand der ersten Abfrage für die ganze Transaktion fest. Gilt bis zum
        # close() unten, also nur für diese Verbindung.
        with quelle.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")

    zeilen = {}
    try:
        # Fremdschlüssel erst am Ende prüfen: die Tabellen kommen in
        # Registrierungs-, nicht in Abhängigkeitsfolge.
        with ziel.constraint_checks_disabled():
            with transaction.atomic(using=quelle_alias), transaction.atomic(using=ziel_alias):
                for model in modelle:
                    zeilen[model._meta.db_table] = _tabelle_kopieren(model, quelle, ziel)
                # Noch in der Transaktion: ein Fehler rollt das Ziel zurück.
                ziel.check_constraints()
    finally:
        quelle.close()
    return zeilen


def _orm_kopieren():
    from django.core.management import call_command

    call_command("migrate", database=ALIAS, verbosity=0, interactive=False)
    return zeilen_kopieren("default", ALIAS)


def sichern(jetzt):
    """Eine Sicherung; liefert den Inhalt von ``stand.json`` oder ``None``."""
    from django.conf import settings
    from django.db import connections

    if _ist_eigene_quelle():
        logger.warning(
            "Sicherung übersprungen: das Portal läuft selbst auf %s.", DATEINAME
        )
        return None

    ordner = verzeichnis()
    ordner.mkdir(parents=True, exist_ok=True)
    tmp = Path(settings.DATABASES[ALIAS]["NAME"])
    tmp.unlink(missing_ok=True)

    beginn = time.monotonic()
    try:
        if connections["default"].vendor == "sqlite":
            zeilen = _sqlite_kopieren(tmp)
        else:
            zeilen = _orm_kopieren()
    except BaseException:
        connections[ALIAS].close()
        tmp.unlink(missing_ok=True)
        raise
    connections[ALIAS].close()
    os.replace(tmp, ordner / DATEINAME)

    stand = {
        "zeitpunkt": jetzt.isoformat(timespec="seconds"),
        "version": os.environ.get("CANTORHUB_VERSION", ""),
        "quelle": connections["default"].vendor,
        "dauer_s": round(time.monotonic() - beginn, 1),
        "zeilen": zeilen,
    }
    stand_tmp = ordner / (STANDDATEI + ".tmp")
    stand_tmp.write_text(json.dumps(stand, indent=1, ensure_ascii=False))
    os.replace(stand_tmp, ordner / STANDDATEI)

    groesse = (ordner / DATEINAME).stat().st_size / 1e6
    logger.info(
        "Sicherung: %d Zeilen aus %d Tabellen, %.1f MB, %.1f s",
        sum(zeilen.values()), len(zeilen), groesse, stand["dauer_s"],
    )
    return stand

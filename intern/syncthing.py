"""Das mitlaufende Syncthing (``start.sh``) über seine lokale REST-API.

Grundlage der Seite ``/intern/sicherung/``: eigene Geräte-ID, wartende und
angenommene Speichergeräte, Annehmen (wahlweise verschlüsselt), Ablehnen,
Entfernen. Dieselben Schritte wie ``sicherung-geraet.sh`` auf der Kommandozeile.

Die API hört nur auf localhost im Container; Adresse und Schlüssel stehen in
``DATEN/syncthing/config.xml``, die ``syncthing generate`` beim ersten Start
anlegt. ``urllib`` statt einer HTTP-Bibliothek — es sind eine Handvoll
JSON-Aufrufe.

Die Teile, die nur Antworten umformen (``zugang_aus_config``,
``geraete_aufbereiten``), sind frei von Netz und Datenbank und getestet.
"""

import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

# Ordner-ID, die start.sh anlegt und sicherung-speicherseite.sh erwartet.
ORDNER_ID = "cantorhub"

_GERAETE_ID = re.compile(r"^[A-Z2-7]{7}(-[A-Z2-7]{7}){7}$")
_TIMEOUT_S = 5


class SyncthingFehler(Exception):
    """Syncthing nicht erreichbar oder Aufruf abgelehnt; der Text ist für die Seite."""


def geraete_id(roh):
    """Eine eingegebene Geräte-ID in der Form, die Syncthing speichert, sonst ``None``.

    Kopiert aus einer GUI kommt sie gern klein, mit Leerzeichen oder ohne
    Bindestriche; Syncthing selbst akzeptiert das auch.
    """
    zeichen = re.sub(r"[\s-]", "", (roh or "").upper())
    if len(zeichen) != 56:
        return None
    kandidat = "-".join(zeichen[i:i + 7] for i in range(0, 56, 7))
    return kandidat if _GERAETE_ID.match(kandidat) else None


def zugang_aus_config(xml_text):
    """``(basis_url, api_schluessel)`` aus dem Inhalt einer ``config.xml``, sonst ``None``."""
    try:
        gui = ET.fromstring(xml_text).find("gui")
    except ET.ParseError:
        return None
    if gui is None:
        return None
    adresse = (gui.findtext("address") or "").strip()
    schluessel = (gui.findtext("apikey") or "").strip()
    if not adresse or not schluessel:
        return None
    # Eine Wildcard-Adresse ist zum Anwählen keine; localhost erreicht sie.
    host, _, port = adresse.rpartition(":")
    if host in ("0.0.0.0", "", "[::]"):
        adresse = f"127.0.0.1:{port}"
    schema = "https" if gui.get("tls") == "true" else "http"
    return f"{schema}://{adresse}", schluessel


def ortszeit(roh):
    """Eine Zeitangabe von Syncthing (ISO, meist UTC) als Wanduhrzeit des Portals.

    ``USE_TZ = False``: das Portal zeigt naive Ortszeit, und die Zeitzone des
    Prozesses ist die konfigurierte (``ZEITZONE``, siehe CLAUDE.md) — dorthin
    rechnet ``astimezone()`` ohne Argument. Leer für nichts und für Syncthings
    „nie" (den Unix-Nullpunkt).
    """
    if not roh or roh.startswith("1970"):
        return ""
    try:
        zeit = datetime.fromisoformat(roh)
    except ValueError:
        return ""
    if zeit.tzinfo is not None:
        zeit = zeit.astimezone().replace(tzinfo=None)
    return zeit.strftime("%d.%m.%Y %H:%M")


def stignore_schuetzt(text):
    """Hält diese ``.stignore`` den Geräteschlüssel aus der Spiegelung heraus?

    start.sh legt sie nur an, wenn sie fehlt; danach gehört sie dem Betreiber.
    Fehlt die Zeile, ginge der Schlüssel dieses Servers auf jedes Speichergerät.
    """
    return "/syncthing" in {zeile.strip() for zeile in (text or "").splitlines()}


def stignore_ok():
    from django.conf import settings

    try:
        return stignore_schuetzt((Path(settings.DATEN) / ".stignore").read_text())
    except OSError:
        return False


def _config_pfad():
    from django.conf import settings

    return Path(settings.DATEN) / "syncthing" / "config.xml"


def _anfrage(methode, pfad, daten=None):
    try:
        zugang = zugang_aus_config(_config_pfad().read_text())
    except OSError:
        zugang = None
    if zugang is None:
        raise SyncthingFehler("Syncthing ist in dieser Installation nicht eingerichtet.")
    basis, schluessel = zugang

    koerper = json.dumps(daten).encode() if daten is not None else None
    anfrage = urllib.request.Request(
        basis + pfad, data=koerper, method=methode,
        headers={"X-API-Key": schluessel, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=_TIMEOUT_S) as antwort:
            inhalt = antwort.read()
    except urllib.error.HTTPError as fehler:
        text = fehler.read().decode(errors="replace").strip()
        raise SyncthingFehler(f"Syncthing lehnt ab: {text or fehler.reason}") from fehler
    except (urllib.error.URLError, OSError) as fehler:
        raise SyncthingFehler("Syncthing antwortet nicht (läuft es, oder startet es noch?).") from fehler
    return json.loads(inhalt) if inhalt.strip() else None


def geraete_aufbereiten(ordner, verbindungen, statistik, fortschritt, eigene_id):
    """Die angenommenen Geräte für die Seite — eines je Freigabe des Ordners.

    ``ordner`` ist ``/rest/config/folders/<id>``, ``verbindungen``
    ``/rest/system/connections``, ``statistik`` ``/rest/stats/device``,
    ``fortschritt`` je Geräte-ID die Antwort von ``/rest/db/completion``.
    """
    geraete = []
    for freigabe in ordner.get("devices", []):
        gid = freigabe.get("deviceID", "")
        if not gid or gid == eigene_id:
            continue
        verbindung = verbindungen.get("connections", {}).get(gid, {})
        typ = verbindung.get("type", "") or ""
        geraete.append({
            "id": gid,
            "kurz": gid.split("-", 1)[0],
            "verschluesselt": bool(freigabe.get("encryptionPassword")),
            "verbunden": bool(verbindung.get("connected")),
            "ueber_relay": typ.startswith("relay"),
            "adresse": verbindung.get("address", ""),
            "zuletzt": ortszeit(statistik.get(gid, {}).get("lastSeen")),
            "fortschritt": fortschritt.get(gid, {}).get("completion"),
        })
    return geraete


def status():
    """Alles, was die Seite zeigt; wirft ``SyncthingFehler``."""
    eigene_id = _anfrage("GET", "/rest/system/status")["myID"]
    ordner = _anfrage("GET", f"/rest/config/folders/{ORDNER_ID}")
    namen = {g["deviceID"]: g.get("name", "") for g in _anfrage("GET", "/rest/config/devices")}
    verbindungen = _anfrage("GET", "/rest/system/connections")
    statistik = _anfrage("GET", "/rest/stats/device") or {}
    fortschritt = {}
    for freigabe in ordner.get("devices", []):
        gid = freigabe.get("deviceID")
        if gid and gid != eigene_id:
            fortschritt[gid] = _anfrage(
                "GET", f"/rest/db/completion?folder={ORDNER_ID}&device={quote(gid)}"
            ) or {}
    geraete = geraete_aufbereiten(ordner, verbindungen, statistik, fortschritt, eigene_id)
    for geraet in geraete:
        geraet["name"] = namen.get(geraet["id"], "")

    angenommen = {g["id"] for g in geraete}
    wartend = [
        {
            "id": gid,
            "kurz": gid.split("-", 1)[0],
            "name": info.get("name", ""),
            "adresse": info.get("address", ""),
            "zeit": ortszeit(info.get("time")),
        }
        for gid, info in (_anfrage("GET", "/rest/cluster/pending/devices") or {}).items()
        if gid not in angenommen
    ]
    return {"eigene_id": eigene_id, "geraete": geraete, "wartend": wartend}


def annehmen(gid, name="", passwort=""):
    """Gerät hinzufügen und den Ordner mit ihm teilen — mit Passwort verschlüsselt."""
    _anfrage("PUT", f"/rest/config/devices/{quote(gid)}", {
        "deviceID": gid,
        "name": name or "Sicherung",
        "addresses": ["dynamic"],
        "untrusted": bool(passwort),
    })
    ordner = _anfrage("GET", f"/rest/config/folders/{ORDNER_ID}")
    freigaben = [f for f in ordner.get("devices", []) if f.get("deviceID") != gid]
    freigaben.append({"deviceID": gid, "encryptionPassword": passwort})
    _anfrage("PATCH", f"/rest/config/folders/{ORDNER_ID}", {"devices": freigaben})


def ablehnen(gid):
    """Ein wartendes Gerät aus der Liste nehmen; meldet es sich wieder, steht es wieder da."""
    _anfrage("DELETE", f"/rest/cluster/pending/devices?device={quote(gid)}")


def entfernen(gid):
    """Gerät samt Freigabe entfernen; liefert seinen Namen.

    Seine Kopie bleibt dort liegen, bekommt aber nichts mehr.
    """
    name = (_anfrage("GET", f"/rest/config/devices/{quote(gid)}") or {}).get("name", "")
    _anfrage("DELETE", f"/rest/config/devices/{quote(gid)}")
    return name

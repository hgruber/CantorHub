"""Die Seite „Sicherung": Stand der Datenbank-Sicherung und die Speichergeräte.

Nur für Superuser, wie die Konfiguration — die Kopie enthält alle Daten aller
Mitglieder, und wer ein Gerät annimmt, gibt sie heraus. Die Sicherung selbst
schreibt ``manage.py sicherung --loop`` (``intern/sicherung.py``), die
Geräte verwaltet das mitlaufende Syncthing (``intern/syncthing.py``).
"""

import json
import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .. import syncthing
from ..app_settings import get_config_int
from ..models import ChangeLog
from ..sicherung import DATEINAME, STANDDATEI, verzeichnis

logger = logging.getLogger(__name__)

__all__ = ["sicherung", "sicherung_entfernen"]

# Ein Passwort, das die Daten aller Mitglieder auf einem fremden Gerät
# schützt, soll nicht zu erraten sein.
PASSWORT_MIN = 12


def _stand():
    """Die letzte Sicherung für die Seite, oder ``None``."""
    ordner = verzeichnis()
    try:
        stand = json.loads((ordner / STANDDATEI).read_text())
        groesse = (ordner / DATEINAME).stat().st_size
    except (OSError, ValueError):
        return None
    return {
        "zeitpunkt": str(stand.get("zeitpunkt", "")).replace("T", " ")[:16],
        "zeilen": sum((stand.get("zeilen") or {}).values()),
        "tabellen": len(stand.get("zeilen") or {}),
        "dauer": stand.get("dauer_s"),
        "groesse_mb": round(groesse / 1e6, 1),
        "version": stand.get("version", ""),
    }


def _protokoll(request, action, geraet_id, name, verschluesselt=None):
    changes = {"geraet": [None, geraet_id] if action == ChangeLog.ACTION_CREATE else [geraet_id, None]}
    if verschluesselt is not None:
        changes["verschluesselt"] = [None, "ja" if verschluesselt else "nein"]
    try:
        ChangeLog.objects.create(
            user=request.user,
            action=action,
            model_name="Sicherungsgeraet",
            object_id=0,
            object_repr=f"{name or 'Sicherung'} ({geraet_id.split('-', 1)[0]})",
            changes=changes,
        )
    except Exception:
        logger.exception("Sicherung: Änderungsprotokoll nicht geschrieben")


def _annehmen(request):
    """Die Felder des Formulars „Annehmen"; liefert einen Fehlertext oder ``None``."""
    gid = syncthing.geraete_id(request.POST.get("geraet"))
    if not gid:
        return "Das ist keine gültige Geräte-ID."
    name = request.POST.get("name", "").strip()[:60]
    passwort = ""
    if request.POST.get("modus") == "verschluesselt":
        passwort = request.POST.get("passwort", "")
        if len(passwort) < PASSWORT_MIN:
            return f"Das Passwort braucht mindestens {PASSWORT_MIN} Zeichen."
    syncthing.annehmen(gid, name, passwort)
    _protokoll(request, ChangeLog.ACTION_CREATE, gid, name, bool(passwort))
    return None


@login_required
def sicherung(request):
    if not request.user.is_superuser:
        return redirect("article_view", name="Aktuell")

    fehler = None
    if request.method == "POST":
        try:
            if request.POST.get("aktion") == "ablehnen":
                gid = syncthing.geraete_id(request.POST.get("geraet"))
                if gid:
                    syncthing.ablehnen(gid)
            else:
                fehler = _annehmen(request)
        except syncthing.SyncthingFehler as ausnahme:
            fehler = str(ausnahme)
        if not fehler:
            return redirect("sicherung")
    elif request.GET.get("entfernen") == "fehlgeschlagen":
        fehler = "Das Gerät ließ sich nicht entfernen — Syncthing antwortet nicht."

    try:
        geraete = syncthing.status()
        syncthing_fehler = None
    except syncthing.SyncthingFehler as ausnahme:
        geraete, syncthing_fehler = None, str(ausnahme)
    if geraete:
        for geraet in geraete["geraete"]:
            geraet["entfernen_url"] = reverse("sicherung_entfernen", args=[geraet["id"]])

    return render(request, "sicherung.html", {
        "seitentitel": "Sicherung",
        "stand": _stand(),
        "ablage": verzeichnis() / DATEINAME,
        "stunden": get_config_int("SICHERUNG_STUNDEN", 24),
        "syncthing": geraete,
        "syncthing_fehler": syncthing_fehler,
        "stignore_ok": syncthing.stignore_ok(),
        "passwort_min": PASSWORT_MIN,
        "entfernen_warnungen": [
            "Die Kopie auf dem Gerät bleibt dort liegen, bekommt aber keine neuen Stände mehr.",
        ],
        "fehler": fehler,
        "eingabe": request.POST if fehler else {},
    })


@require_POST
@login_required
def sicherung_entfernen(request, geraet_id):
    if not request.user.is_superuser:
        return redirect("article_view", name="Aktuell")
    gid = syncthing.geraete_id(geraet_id)
    if gid:
        try:
            name = syncthing.entfernen(gid)
        except syncthing.SyncthingFehler as ausnahme:
            logger.warning("Sicherung: Gerät %s nicht entfernt: %s", gid, ausnahme)
            return redirect(reverse("sicherung") + "?entfernen=fehlgeschlagen")
        _protokoll(request, ChangeLog.ACTION_DELETE, gid, name)
    return redirect("sicherung")

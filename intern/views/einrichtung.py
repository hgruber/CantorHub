"""Die Ersteinrichtung einer neuen Installation (kein Login).

Die Logik liegt in ``intern/einrichtung.py``; die Weiterleitung hierher macht
``middleware.Ersteinrichtung``, solange es keinen Superuser gibt.
"""

import logging
import os
import shutil
import signal
import threading
from pathlib import Path

from django.conf import settings
from django.contrib.auth import login
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from intern import syncthing
from intern import wiederherstellung as wh
from intern.einrichtung import (
    BereitsEingerichtet,
    einrichten,
    hosts_festlegen,
    ist_eingerichtet,
    smtp_konfiguration,
)
from intern.forms import EinrichtungForm

logger = logging.getLogger(__name__)

__all__ = ["einrichtung", "wiederherstellen"]


def einrichtung(request):
    if ist_eingerichtet():
        raise Http404
    # Eine begonnene Wiederherstellung schließt die Einrichtung von Hand aus —
    # wer hierher kommt, landet bei ihr, bis sie fertig oder abgebrochen ist.
    if wh.lese_zustand():
        return redirect("einrichtung_wiederherstellen")

    url_aus_umgebung = os.environ.get("VEREINS_URL", "")
    # Die Adresse ergibt sich aus dem Aufruf selbst; hinter dem Proxy liefert
    # SECURE_PROXY_SSL_HEADER das richtige Schema.
    form = EinrichtungForm(
        request.POST or None,
        initial={
            "vereins_url": url_aus_umgebung
            or request.build_absolute_uri("/").rstrip("/"),
        },
    )
    if url_aus_umgebung:
        # _seed_config schreibt die Variable bei jedem Start zurück; ein anderer
        # Wert hier wäre nach dem nächsten Neustart wieder weg.
        form.fields["vereins_url"].disabled = True

    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        konfiguration = {
            "VEREINS_URL": d["vereins_url"],
            "DEFAULT_FROM_EMAIL": d["absender"],
            **smtp_konfiguration(
                d["email_host"].strip(),
                d["email_port"],
                d["email_host_user"],
                d["email_host_password"],
                d["email_verschluesselung"],
            ),
        }
        try:
            nutzer = einrichten(
                konto={
                    "username": d["username"],
                    "first_name": d["first_name"],
                    "last_name": d["last_name"],
                    "email": d["email"],
                },
                passwort=d["password1"],
                konfiguration=konfiguration,
                jetzt=timezone.now(),
                beispieldaten=d["beispieldaten"],
            )
        except BereitsEingerichtet:
            raise Http404
        logger.info("Ersteinrichtung abgeschlossen, erstes Konto: %s", nutzer.username)
        if not url_aus_umgebung:
            # Für diesen Prozess; die übrigen Arbeiter legen sie bei ihrer
            # nächsten Anfrage fest (middleware.Ersteinrichtung).
            hosts_festlegen(d["vereins_url"])
        login(request, nutzer)
        return redirect("konfiguration")

    return render(request, "einrichtung.html", {"form": form})


def _im_container():
    """Läuft das Portal im Abbild, mit gunicorn als PID 1 (start.sh: exec)?

    Nur dann darf die Wiederherstellung den Container beenden — in der
    Entwicklung wäre PID 1 das init des Rechners.
    """
    if settings.DEBUG:
        return False
    try:
        return b"gunicorn" in Path("/proc/1/cmdline").read_bytes()
    except OSError:
        return False


def _neu_starten():
    """gunicorn (PID 1) sauber beenden; die Restart-Policy startet den Container neu.

    Kurz verzögert, damit die Antwort mit dem Hinweis noch ankommt.
    """
    if not _im_container():
        return False
    threading.Timer(1.5, os.kill, args=(1, signal.SIGTERM)).start()
    return True


def _annehmen(request, klon):
    """Formular „Von diesem Gerät wiederherstellen“; Fehlertext oder ``None``."""
    gid = syncthing.geraete_id(request.POST.get("geraet"))
    if not gid:
        return "Das ist keine gültige Geräte-ID."
    passwort = ""
    if request.POST.get("modus") == "verschluesselt":
        passwort = request.POST.get("passwort", "")
        if not passwort:
            return "Für eine verschlüsselte Ablage braucht es ihr Passwort."
    name = request.POST.get("name", "").strip()[:60]
    syncthing.empfang_beginnen(gid, name, passwort, wh.empfangsordner())
    wh.schreibe_zustand(
        phase=wh.EMPFANGEN, geraet=gid, name=name, verschluesselt=bool(passwort), klon=klon,
    )
    logger.info("Wiederherstellung: Empfang von %s begonnen", gid.split("-", 1)[0])
    return None


def wiederherstellen(request):
    """Eine neue Installation aus einer Sicherung herstellen (intern/wiederherstellung.py).

    Offen wie die Ersteinrichtung selbst: solange es keinen Superuser gibt, für
    wen auch immer zuerst kommt. Eine eingespielte Sicherung bringt ihren
    Superuser mit und schließt die Seite damit.

    Mit ``?klon=1`` (bzw. dem Feld ``klon``) wird daraus ein Klon neben dem
    Original; ab dem Annehmen trägt der Zustand das Merkmal.
    """
    if ist_eingerichtet():
        raise Http404

    zustand = wh.lese_zustand()
    phase = (zustand or {}).get("phase")
    if zustand:
        klon = bool(zustand.get("klon"))
    else:
        klon = "1" in (request.GET.get("klon"), request.POST.get("klon"))
    fehler = None
    if request.method == "POST":
        aktion = request.POST.get("aktion")
        try:
            if aktion == "annehmen" and not zustand:
                fehler = _annehmen(request, klon)
            elif aktion == "ablehnen" and not zustand:
                gid = syncthing.geraete_id(request.POST.get("geraet"))
                if gid:
                    syncthing.ablehnen(gid)
            elif aktion == "abbrechen" and zustand:
                syncthing.empfang_abbrechen(zustand.get("geraet"), wh.datenverzeichnis())
                shutil.rmtree(wh.empfangsordner(), ignore_errors=True)
                wh.zustand_loeschen()
                logger.info("Wiederherstellung abgebrochen")
                return redirect("einrichtung")
            elif aktion == "erneut" and phase == wh.FEHLER:
                wh.schreibe_zustand(**{**zustand, "phase": wh.EMPFANGEN, "fehler": ""})
            elif aktion == "einspielen" and phase == wh.EMPFANGEN:
                if not syncthing.empfang_stand(zustand["geraet"])["fertig"]:
                    fehler = "Der Empfang ist noch nicht vollständig."
                else:
                    fehler = wh.pruefen(wh.empfangsordner(), wh.bekannte_migrationen())
                if not fehler:
                    # Ein Klon behält die Adresse, unter der er gerade bedient wird.
                    url = f"{request.scheme}://{request.get_host()}" if klon else ""
                    wh.schreibe_zustand(**{**zustand, "phase": wh.BEREIT, "klon_url": url})
                    logger.info("Wiederherstellung: bereit, Neustart angefordert")
                    kontext = {"phase": wh.BEREIT, "klon": klon}
                    if klon:
                        # Für den Hinweis, die ID auf dem Speichergerät zu löschen.
                        try:
                            kontext["eigene_id"] = syncthing.eigene_id()
                        except syncthing.SyncthingFehler:
                            pass
                    kontext["neustart"] = _neu_starten()
                    return render(request, "wiederherstellen.html", kontext)
        except syncthing.SyncthingFehler as ausnahme:
            fehler = str(ausnahme)
        if not fehler:
            ziel = reverse("einrichtung_wiederherstellen")
            return redirect(f"{ziel}?klon=1" if klon and not wh.lese_zustand() else ziel)
        zustand = wh.lese_zustand()
        phase = (zustand or {}).get("phase")

    kontext = {"phase": phase or "start", "zustand": zustand, "fehler": fehler, "klon": klon}
    try:
        kontext["eigene_id"] = syncthing.eigene_id()
        if not zustand:
            kontext["wartend"] = syncthing.status()["wartend"]
        elif phase == wh.EMPFANGEN:
            kontext["empfang"] = empfang = syncthing.empfang_stand(zustand["geraet"])
            if empfang["fertig"]:
                kontext["pruefung"] = wh.pruefen(wh.empfangsordner(), wh.bekannte_migrationen())
                kontext["inhalt"] = wh.zusammenfassung(wh.empfangsordner())
    except syncthing.SyncthingFehler as ausnahme:
        kontext["syncthing_fehler"] = str(ausnahme)
    return render(request, "wiederherstellen.html", kontext)

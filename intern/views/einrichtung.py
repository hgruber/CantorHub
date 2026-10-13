"""Die Ersteinrichtung einer neuen Installation (kein Login).

Die Logik liegt in ``intern/einrichtung.py``; die Weiterleitung hierher macht
``middleware.Ersteinrichtung``, solange es keinen Superuser gibt.
"""

import logging
import os

from django.contrib.auth import login
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone

from intern.einrichtung import (
    BereitsEingerichtet,
    einrichten,
    hosts_festlegen,
    ist_eingerichtet,
    smtp_konfiguration,
)
from intern.forms import EinrichtungForm

logger = logging.getLogger(__name__)


def einrichtung(request):
    if ist_eingerichtet():
        raise Http404

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

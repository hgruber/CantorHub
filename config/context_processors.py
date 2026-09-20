from django.conf import settings

# Attribut am Request, unter dem das Ergebnis einer Anfrage liegt.
_GEMERKT = "_project_meta"


def project_meta(request):
    """Globaler Vorlagenkontext — pro Anfrage genau einmal berechnet.

    Der Prozessor kostet rund elf Millisekunden und sieben Abfragen (Termin-Banner,
    offene Zusagen, Forum-Ungelesen, Änderungsprotokoll, Konfiguration), und er lief
    mehrfach pro Seite: einmal für die Seite selbst, ein zweites Mal in
    ``{% render_table %}`` — django_tables2 rendert die Tabellenvorlage mit ``request=`` —
    und in der Terminliste zusätzlich einmal pro Zeile, weil ``TemplateColumn`` dasselbe
    tut. Die Terminliste brauchte so 17 Läufe, 232 ms und 130 Abfragen; mit diesem
    Zwischenspeicher sind es 39 ms und 15 Abfragen.

    Das gespeicherte Ergebnis wird nicht verändert: ``RequestContext`` kopiert die Werte
    beim Binden der Vorlage in eine eigene Ebene.
    """
    gemerkt = getattr(request, _GEMERKT, None)
    if gemerkt is not None:
        return gemerkt
    ergebnis = _project_meta_berechnen(request)
    setattr(request, _GEMERKT, ergebnis)
    return ergebnis


def _project_meta_berechnen(request):
    from intern.app_settings import (
        get_brand_farbe, get_config_bool, get_config_int, get_vereinsname,
        get_vereinsname_lang, get_vereinsname_kurz,
    )
    result = {
        "VERSION": settings.VERSION,
        "offen_termine": 0,
        "upload_max_mb": get_config_int("UPLOAD_MAX_MB", 50),
        "vereinsname":      get_vereinsname(),
        "vereinsname_lang": get_vereinsname_lang(),
        "vereinsname_kurz": get_vereinsname_kurz(),
        "brand_farbe":      get_brand_farbe(),
    }
    # Fehlerseiten rendern durch denselben Prozessor, und ein Fehler aus
    # `CommonMiddleware` (etwa ein unerlaubter Host) tritt auf, bevor
    # `AuthenticationMiddleware` das Attribut gesetzt hat. Django macht es in
    # seinem eigenen `auth`-Prozessor genauso — ohne den Umweg würde aus jeder
    # 400er-Antwort ein nackter Traceback.
    nutzer = getattr(request, "user", None)
    if nutzer is not None and nutzer.is_authenticated:
        from django.utils.timezone import now
        from intern.models import ChangeLog, Termin, Zusage
        from intern.terminzeit import kommende_q
        # Eine Definition für alle drei Verwendungen: „bevorstehend“ schließt
        # den ganztägigen Termin von heute ein, dessen datum formal schon
        # vergangen ist (siehe intern/terminzeit.py). Gäbe es zwei Lesarten,
        # fiele eine bereits erteilte Zusage aus `answered` heraus und der
        # Termin bliebe für immer als „offen“ gezählt.
        jetzt = now()
        kommende = Termin.objects.filter(kommende_q(jetzt))
        answered = Zusage.objects.filter(
            person=request.user,
            termin__in=kommende,
            option__in=["1", "2", "3"],
        ).values("termin_id")
        result["offen_termine"] = (
            kommende.filter(anwesenheit=True).exclude(id__in=answered).count()
        )
        banner_termin = (
            kommende.select_related("ort").order_by("datum").first()
            if get_config_bool("TERMIN_BANNER_AKTIV", True) else None
        )
        result["banner_termin"] = banner_termin
        # Session key for the banner's dismissed state. Deliberately not read from the
        # template's `user` — detail views (mitglied_view/-_edit) shadow it with the
        # member being looked at, which would key the dismissal to a stranger's login.
        last_login = request.user.last_login
        result["banner_login"] = "%s-%s" % (
            request.user.pk, int(last_login.timestamp()) if last_login else 0,
        )
        if banner_termin is not None:
            zusage = (
                Zusage.objects.filter(person=request.user, termin=banner_termin)
                .order_by("-id")
                .values_list("option", flat=True)
                .first()
            )
            result["banner_my_option"] = zusage or ""
        # Unread forum messages light the dot on „Forum". Skipped for htmx requests: the
        # forum's 5 s poll renders through here too, and partials carry no sidebar.
        if not request.headers.get("HX-Request"):
            from intern.forum_gelesen import hat_ungelesene
            result["foren_ungelesen"] = hat_ungelesene(request.user)
        result["latest_changelog_id"] = (
            ChangeLog.objects.order_by("-id").values_list("id", flat=True).first() or 0
        )
        result["notify_enabled"] = request.user.notify_enabled
        result["notify_poll_ms"] = get_config_int("NOTIFY_POLL_MS", 10000)
        result["notify_dismiss_ms"] = get_config_int("NOTIFY_DISMISS_MS", 6000)
    return result

from django.conf import settings


def project_meta(request):
    from intern.app_settings import get_config_int, get_vereinsname, get_vereinsname_lang, get_vereinsname_kurz
    result = {
        "VERSION": settings.VERSION,
        "offen_termine": 0,
        "upload_max_mb": get_config_int("UPLOAD_MAX_MB", 50),
        "vereinsname":      get_vereinsname(),
        "vereinsname_lang": get_vereinsname_lang(),
        "vereinsname_kurz": get_vereinsname_kurz(),
    }
    if request.user.is_authenticated:
        from django.utils.timezone import now
        from intern.models import ChangeLog, Termin, Zusage
        answered = Zusage.objects.filter(
            person=request.user,
            termin__datum__gt=now(),
            option__in=["1", "2", "3"],
        ).values("termin_id")
        result["offen_termine"] = Termin.objects.filter(
            datum__gt=now(), anwesenheit=True,
        ).exclude(id__in=answered).count()
        banner_termin = (
            Termin.objects.filter(datum__gt=now())
            .select_related("ort")
            .order_by("datum")
            .first()
        )
        result["banner_termin"] = banner_termin
        if banner_termin is not None:
            zusage = (
                Zusage.objects.filter(person=request.user, termin=banner_termin)
                .order_by("-id")
                .values_list("option", flat=True)
                .first()
            )
            result["banner_my_option"] = zusage or ""
        result["latest_changelog_id"] = (
            ChangeLog.objects.order_by("-id").values_list("id", flat=True).first() or 0
        )
        result["notify_enabled"] = request.user.notify_enabled
        result["notify_poll_ms"] = get_config_int("NOTIFY_POLL_MS", 10000)
        result["notify_dismiss_ms"] = get_config_int("NOTIFY_DISMISS_MS", 6000)
    return result

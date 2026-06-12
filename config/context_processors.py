from django.conf import settings


def project_meta(request):
    from intern.app_settings import get_config_int
    result = {
        "VERSION": settings.VERSION,
        "offen_termine": 0,
        "upload_max_mb": get_config_int("UPLOAD_MAX_MB", 50),
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
        result["latest_changelog_id"] = (
            ChangeLog.objects.order_by("-id").values_list("id", flat=True).first() or 0
        )
        result["notify_enabled"] = request.user.notify_enabled
    return result

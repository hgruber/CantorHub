from django.conf import settings


def project_meta(request):
    result = {"VERSION": settings.VERSION, "offen_termine": 0}
    if request.user.is_authenticated:
        from django.utils.timezone import now
        from intern.models import Termin, Zusage
        answered = Zusage.objects.filter(
            person=request.user,
            termin__datum__gt=now(),
            option__in=["1", "2", "3"],
        ).values("termin_id")
        result["offen_termine"] = Termin.objects.filter(
            datum__gt=now(), anwesenheit=True,
        ).exclude(id__in=answered).count()
    return result

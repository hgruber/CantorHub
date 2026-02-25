from django.conf import settings


def project_meta(request):
    return {
        "VERSION": settings.VERSION,
    }

"""Gemeinsame View-Decorators."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def perm_or_home(perm, superuser_ok=True):
    """Zutritt nur mit ``perm`` (oder als Superuser); sonst zurück auf „Aktuell".

    Bewusst nicht ``permission_required``: das antwortet je nach Aufruf mit 403
    oder schickt auf die Login-Seite. Die Verwaltungsseiten dahinter sollen
    stattdessen wortlos auf die Startseite zurückfallen — wer das Recht nicht
    hat, sieht den Menüpunkt gar nicht erst, ein 403 wäre also nur verwirrend.

    Enthält ``login_required``, denn ohne Anmeldung gibt es keine Rechte zu
    prüfen; die Views brauchen es nicht zusätzlich.
    """

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            erlaubt = request.user.has_perm(perm) or (
                superuser_ok and request.user.is_superuser
            )
            if not erlaubt:
                return redirect("article_view", name="Aktuell")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator

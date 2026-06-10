"""Zugriffskontrolle für Mediendateien.

Zwei Wege zu einer Datei:

1. Session-basiert: nginx prüft jede /media/-Anfrage per auth_request gegen
   `media_auth` — nur eingeloggte Mitglieder erhalten Dateien. Bestehende
   /media/-URLs in Templates und Tabellen funktionieren damit unverändert.

2. Token-basiert (`datei_token`): für Links, die das Portal verlassen —
   insbesondere Forum-Nachrichten, die in XMPP-Räume (Conversations/Monal)
   weitergeleitet werden. Diese Clients haben keine Portal-Session. Der Token
   ist eine HMAC-Signatur der Datei-ID (abgeleitet aus SECRET_KEY, kein
   DB-Feld) und läuft nicht ab, damit alte Nachrichten aus der MAM-Historie
   weiterhin auflösen. Sicherheitsmodell: Wer den exakten Link kennt, darf
   die eine Datei laden — wie bei XEP-0363-Uploads.
"""

import mimetypes
import re
from urllib.parse import quote, unquote

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.core.signing import Signer

from filer.models import File

__all__ = ["media_auth", "datei_token", "file_token", "rewrite_media_urls"]

_signer = Signer(salt="intern.datei_token")


def file_token(pk):
    """Nicht ablaufender Capability-Token für eine Datei-ID."""
    return _signer.signature(str(pk))


def media_auth(request):
    """nginx auth_request-Endpunkt: 204 für eingeloggte Nutzer, sonst 403."""
    if request.user.is_authenticated:
        return HttpResponse(status=204)
    return HttpResponse(status=403)


def datei_token(request, pk, token, filename):
    """Liefert eine Datei gegen gültigen Token aus — ohne Session."""
    from django.utils.crypto import constant_time_compare

    if not constant_time_compare(token, file_token(pk)):
        raise Http404
    f = get_object_or_404(File, pk=pk)

    content_type = (
        f.mime_type
        or mimetypes.guess_type(f.original_filename or "")[0]
        or "application/octet-stream"
    )
    if settings.DEBUG:
        return FileResponse(f.file.open("rb"), content_type=content_type)
    response = HttpResponse(content_type=content_type)
    response["X-Accel-Redirect"] = "/protected-media/" + quote(f.file.name)
    return response


_MEDIA_URL_RE = re.compile(
    r"(https?://[^\s\"'<>]+?)" + re.escape(settings.MEDIA_URL) + r"([^\s\"'<>]+)"
)


def rewrite_media_urls(text):
    """Ersetzt /media/-URLs in ausgehendem Text durch Token-URLs.

    Wird beim Weiterleiten von Forum-Nachrichten an XMPP verwendet, damit
    Clients ohne Portal-Session geteilte Dateien laden können. URLs, die
    keiner Filer-Datei zugeordnet werden können (z. B. Thumbnails), bleiben
    unverändert.
    """

    def _replace(match):
        origin, path = match.group(1), unquote(match.group(2))
        f = File.objects.filter(file=path).first()
        if f is None:
            return match.group(0)
        name = quote(f.original_filename or f.file.name.rsplit("/", 1)[-1])
        return f"{origin}/intern/datei/{f.pk}/{file_token(f.pk)}/{name}"

    return _MEDIA_URL_RE.sub(_replace, text)

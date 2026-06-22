import logging

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from easy_thumbnails.files import get_thumbnailer
from filer.models import File, Folder

from intern.folder_access import folder_access, is_folder_visible
from intern.views.folders import _folder_breadcrumb

logger = logging.getLogger(__name__)

__all__ = ["gallerie_view"]


@login_required
def gallerie_view(request, ordner_id):
    folder = get_object_or_404(Folder, pk=ordner_id)
    if not is_folder_visible(request.user, folder):
        raise Http404

    can_read, _, _ = folder_access(request.user, folder)
    if not can_read:
        raise Http404

    images = File.objects.filter(
        folder=folder,
        mime_type__startswith="image/",
    ).select_related("owner").order_by("original_filename")

    items = []
    for img in images:
        try:
            thumb = get_thumbnailer(img.file).get_thumbnail(
                {"size": (400, 400), "crop": True, "quality": 85}
            )
        except Exception:
            logger.debug("Thumbnail für Datei %s fehlgeschlagen", img.pk)
            continue
        owner_name = ""
        if img.owner:
            owner_name = img.owner.get_full_name() or img.owner.username
        items.append({
            "thumb": thumb.url,
            "url": img.url,
            "name": img.name or img.original_filename,
            "description": img.description or "",
            "owner": owner_name,
            "pk": img.pk,
        })

    return render(request, "gallerie.html", {
        "folder": folder,
        "items": items,
        "breadcrumb": _folder_breadcrumb(folder, user=request.user),
        "seitentitel": folder.name,
        "edit": None,
    })

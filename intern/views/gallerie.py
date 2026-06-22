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

    files = File.objects.filter(
        folder=folder,
    ).select_related("owner").order_by("original_filename")

    items = []
    lb_idx = 0
    for f in files:
        mime = f.mime_type or ""
        is_image = mime.startswith("image/")
        is_thumbnailable = is_image or mime.endswith("pdf")

        thumb_url = None
        if is_thumbnailable:
            thumb_opts = (
                {"size": (400, 400), "crop": True, "quality": 85}
                if is_image
                else {"size": (400, 566), "crop": False, "quality": 85}
            )
            try:
                thumb = get_thumbnailer(f.file).get_thumbnail(thumb_opts)
                thumb_url = thumb.url
            except Exception:
                logger.debug("Thumbnail für Datei %s fehlgeschlagen", f.pk)
                if is_image:
                    continue

        owner_name = ""
        if f.owner:
            owner_name = f.owner.get_full_name() or f.owner.username

        items.append({
            "is_image": is_image,
            "lb_index": lb_idx if is_image else None,
            "thumb": thumb_url,
            "url": f.url,
            "name": f.name or f.original_filename,
            "description": f.description or "",
            "owner": owner_name,
            "pk": f.pk,
        })
        if is_image:
            lb_idx += 1

    return render(request, "gallerie.html", {
        "folder": folder,
        "items": items,
        "breadcrumb": _folder_breadcrumb(folder, user=request.user),
        "seitentitel": folder.name,
        "edit": None,
    })

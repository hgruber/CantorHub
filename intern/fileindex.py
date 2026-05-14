"""Lightweight per-file text index for content search in the folder browser.

Text is extracted lazily (on the first search that touches a file) and stored in
the DateiIndex model. PDFs go through PyMuPDF; plain-text files are read
directly; every other type gets an empty index row so it is not re-examined on
every search. Extraction never raises — failures yield an empty row.
"""

import os

from django.db import transaction

from .models import DateiIndex

_TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".log"}
_MAX_PAGES = 50
_MAX_CHARS = 1_000_000


def _filename(filer_file):
    return filer_file.original_filename or filer_file.name or ""


def _extract_pdf(data):
    try:
        import fitz  # PyMuPDF

        parts = []
        total = 0
        with fitz.open(stream=data, filetype="pdf") as doc:
            for i in range(min(doc.page_count, _MAX_PAGES)):
                txt = doc[i].get_text()
                parts.append(txt)
                total += len(txt)
                if total >= _MAX_CHARS:
                    break
        return "".join(parts)[:_MAX_CHARS]
    except Exception:
        return ""


def extract_text(filer_file):
    """Return extracted text for a filer File, or "" if unsupported/unreadable.

    mime_type is not trusted here — uploads via the folder browser do not set
    it — so the file type is decided by magic bytes and extension.
    """
    ext = os.path.splitext(_filename(filer_file))[1].lower()
    try:
        with filer_file.file.open("rb") as fh:
            data = fh.read()
    except Exception:
        return ""

    if data[:5] == b"%PDF-" or ext == ".pdf":
        return _extract_pdf(data)
    if ext in _TEXT_EXTENSIONS:
        try:
            return data.decode("utf-8", errors="ignore")[:_MAX_CHARS]
        except Exception:
            return ""
    return ""


def index_file(filer_file):
    """Extract and store text for one filer File. Always writes a row."""
    text = extract_text(filer_file)
    with transaction.atomic():
        DateiIndex.objects.update_or_create(
            file=filer_file,
            defaults={"text": text, "file_size": filer_file._file_size or 0},
        )


def ensure_indexed(file_qs):
    """Index any files in file_qs that lack a current index row.

    A row is current when it exists and its stored file_size matches the file's
    current size. Each file is indexed independently so one failure does not
    abort the rest.
    """
    files = list(file_qs)
    if not files:
        return
    existing = {
        row["file_id"]: row["file_size"]
        for row in DateiIndex.objects.filter(
            file_id__in=[f.pk for f in files]
        ).values("file_id", "file_size")
    }
    for f in files:
        current = existing.get(f.pk)
        if current is not None and current == (f._file_size or 0):
            continue
        try:
            index_file(f)
        except Exception:
            pass

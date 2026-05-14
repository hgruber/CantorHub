"""easy-thumbnails source generator for PDF files.

Renders the first page of a PDF into a PIL image so the rest of the
easy-thumbnails pipeline (and its caching) works for PDFs exactly like it
does for images. Registered via THUMBNAIL_SOURCE_GENERATORS in settings.
"""

from io import BytesIO

from PIL import Image


def pdf_source(source, **options):
    """Return a PIL image of the PDF's first page, or None if not a PDF."""
    try:
        source.seek(0)
        data = source.read()
    except Exception:
        return None

    if not data[:5] == b"%PDF-":
        return None

    try:
        import fitz  # PyMuPDF

        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.page_count == 0:
                return None
            pix = doc[0].get_pixmap(dpi=150)
            return Image.open(BytesIO(pix.tobytes("png")))
    except Exception:
        return None

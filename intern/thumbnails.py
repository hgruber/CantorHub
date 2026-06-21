"""easy-thumbnails source generators for PDF and Word files.

Registered via THUMBNAIL_SOURCE_GENERATORS in settings. Each generator
receives a file-like `source` and returns a PIL Image or None.
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


def docx_source(source, **options):
    """Return a PIL text-preview image of a .docx file, or None if not a docx."""
    try:
        source.seek(0)
        data = source.read()
    except Exception:
        return None

    # .docx is a ZIP file
    if data[:4] != b"PK\x03\x04":
        return None

    try:
        from docx import Document
        from PIL import ImageDraw, ImageFont

        doc = Document(BytesIO(data))

        lines = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                lines.append(text)
            if len(lines) >= 30:
                break

        if not lines:
            return None

        width, height = 595, 842  # A4 proportions
        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default(size=14)
        margin = 40
        line_height = 22
        y = margin
        max_chars = (width - 2 * margin) // 8  # approx. chars per line at size 14

        for line in lines:
            # Simple word wrap
            while line:
                chunk = line[:max_chars]
                draw.text((margin, y), chunk, fill="black", font=font)
                line = line[max_chars:]
                y += line_height
                if y > height - margin:
                    break
            if y > height - margin:
                break

        return img
    except Exception:
        return None

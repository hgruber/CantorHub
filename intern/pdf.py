"""Branded PDF letterhead for all CantorHub-generated documents."""

from io import BytesIO

from django.contrib.staticfiles import finders
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

# ── Farben ────────────────────────────────────────────────────────────────────
BRAND = (193/255, 68/255, 104/255)   # #c14468 — nur für Linien
BLACK = (0, 0, 0)
GRAY  = (0.35, 0.35, 0.35)           # Untertitel / Metaangaben

# ── Layout ────────────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4
MARGIN   = 2.0 * cm
HEADER_H = 4.5 * cm    # Höhe des Briefkopfbereichs (DIN 5008 Form B: 45 mm)
FOOTER_Y = 1.8 * cm
LINE_H   = 0.65 * cm
LABEL_X  = MARGIN
VALUE_X  = MARGIN + 5.0 * cm

_LOGO_STATIC = "intern/brand/JG-Frankfurt-transparent.png"


def _draw_header(c, vereinsname_lang, vereinsadresse):
    # Logo: farbig, oben links, etwas kleiner
    logo_path = finders.find(_LOGO_STATIC)
    if logo_path:
        img = ImageReader(logo_path)
        iw, ih = img.getSize()
        logo_w = 5.5 * cm
        logo_h = logo_w * ih / iw
        logo_x = MARGIN
        logo_y = PAGE_H - HEADER_H + (HEADER_H - logo_h) / 2
        c.drawImage(img, logo_x, logo_y, width=logo_w, height=logo_h, mask="auto")

    # Vereinsname + Adresse rechts, oben bündig, schwarz
    text_y = PAGE_H - 1.0 * cm
    c.setFillColorRGB(*BLACK)
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(PAGE_W - MARGIN, text_y, vereinsname_lang)

    c.setFont("Helvetica", 8.5)
    for line in (vereinsadresse or "").strip().splitlines():
        line = line.strip()
        if line:
            text_y -= 0.46 * cm
            c.drawRightString(PAGE_W - MARGIN, text_y, line)

    # Dünne farbige Zierlinie unter dem Briefkopf
    c.setStrokeColorRGB(*BRAND)
    c.setLineWidth(1.2)
    c.line(MARGIN, PAGE_H - HEADER_H, PAGE_W - MARGIN, PAGE_H - HEADER_H)


def _draw_footer(c, vereinsname_lang, vereinsadresse):
    # Dünne farbige Linie
    c.setStrokeColorRGB(*BRAND)
    c.setLineWidth(0.8)
    c.line(MARGIN, FOOTER_Y, PAGE_W - MARGIN, FOOTER_Y)

    footer_left = vereinsname_lang
    if vereinsadresse:
        first_line = vereinsadresse.strip().splitlines()[0].strip()
        footer_left = f"{vereinsname_lang} · {first_line}"

    c.setFillColorRGB(*BLACK)
    c.setFont("Helvetica", 7.5)
    c.drawString(MARGIN, FOOTER_Y - 0.5 * cm, footer_left)
    c.drawRightString(PAGE_W - MARGIN, FOOTER_Y - 0.5 * cm, "Seite 1")


def new_letterhead_pdf(title, subtitle, vereinsname_lang, vereinsadresse):
    """Create a Canvas with letterhead already drawn.

    Returns (buf, canvas, content_y) — content_y is the first free line
    below the document title separator.
    """
    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)

    _draw_header(c, vereinsname_lang, vereinsadresse)
    _draw_footer(c, vereinsname_lang, vereinsadresse)

    # Dokumenttitel
    title_y = PAGE_H - HEADER_H - 0.9 * cm
    c.setFillColorRGB(*BLACK)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(MARGIN, title_y, title)

    subtitle_y = title_y - 0.6 * cm
    c.setFillColorRGB(*GRAY)
    c.setFont("Helvetica", 9)
    c.drawString(MARGIN, subtitle_y, subtitle)

    sep_y = subtitle_y - 0.45 * cm
    c.setStrokeColorRGB(*BRAND)
    c.setLineWidth(0.4)
    c.line(MARGIN, sep_y, PAGE_W - MARGIN, sep_y)

    return buf, c, sep_y - 2.7 * cm


def draw_section(c, y, title):
    """Draw a bold section heading; return updated y."""
    y -= 0.3 * cm
    c.setFillColorRGB(*BLACK)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(LABEL_X, y, title)
    return y - LINE_H


def draw_field(c, y, label, value):
    """Draw a label-value pair; return updated y."""
    c.setFillColorRGB(*BLACK)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(LABEL_X, y, label)
    c.setFont("Helvetica", 10)
    c.drawString(VALUE_X, y, str(value) if value else "")
    return y - LINE_H


def draw_checkbox(c, y, text, checked=True):
    """Draw a [X] / [ ] checkbox line; return updated y."""
    c.setFillColorRGB(*BLACK)
    c.setFont("Helvetica", 10)
    c.drawString(LABEL_X, y, f"{'[X]' if checked else '[ ]'}  {text}")
    return y - LINE_H


def draw_signature(c, y, name):
    """Draw name and submission note; return updated y."""
    y -= 0.8 * cm
    c.setFillColorRGB(*BLACK)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(LABEL_X, y, name)
    y -= 0.55 * cm
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(*GRAY)
    c.drawString(LABEL_X, y, "(per Webformular persönlich bestätigt)")
    return y - LINE_H

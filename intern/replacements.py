import locale
import re
from datetime import date, datetime, timedelta
from typing import Union

from filer.models import File


def internal_links(match, request):
    print(
        f"{match.group(1)}\n{match.group(2)}\n{match.group(3)}\n|{match.group(4)}|\n{match.group(5)}\n"
    )
    if match.group(2) == "Datei:":
        try:
            f = File.objects.get(original_filename=match.group(4))
            return f'<a href="{f.url}">Datei: {match.group(4)}</a>'
        except Exception as e:
            return f'<span title="{e}" class="not_found">Datei: {match.group(4)}</span>'

    elif match.group(2) == "Aktion:":
        return f"<div>Aktion: {match.group(4)}</div>"
    elif match.group(2) == "Geo:":
        return f"<div>Karte: {match.group(4)}</div>"
    else:
        return f'<a href="/intern/artikel/{match.group(4)}/">{match.group(4)}</a>'


def apply_replacements(text, request=None):
    """Wendet alle Ersetzungen auf den Text an"""

    def _internal_links(match):
        return internal_links(match, request)

    # Definiere deine regulären Ausdrücke und Ersetzungen
    REPLACEMENTS = [
        (r"^======(.*)======$", r"<h5>\1</h5>"),
        (r"^=====(.*)=====$", r"<h4>\1</h4>"),
        (r"^====(.*)====$", r"<h3>\1</h3>"),
        (r"^===(.*)===$", r"<h2>\1</h2>"),
        (r"^==(.*)==$", r"<h1>\1</h1>"),
        (
            r"(\[\[(([^\]]*?)\:)?\s*([^\[\]]*?)(\|([^\[\]]+?))?\]\]([a-z]+)?)",
            _internal_links,
        ),
        (r"\[(https?://[^\s\]]+)\s+([^\]]+)\]", r'<a href="\1">\2</a>'),  # [URL Name]
        (
            r"(?<![\"])(https?://[^\s\"]+\.(?:png|jpg|jpeg|gif|bmp|webp))(?![\"])",
            r'<img src="\1"></img>',
        ),
        (
            r"(?<![\"])(https?://[^\s\"]+\.(mp3|wav|ogg|aac|flac|m4a))(?![\"])",
            r'<audio controls src="\1"></audio>',
        ),
        (
            r"(?<![\"])(https?://[^\s\"]+\.(?:mp4|webm|ogg|avi|mov|wmv|flv|mkv))(?![\"])",
            r'<video controls src="\1"></video>',
        ),
        (r"(?<![\"])(https?://[^\s\"]+)(?![\"])", r'<a href="\1">\1</a>'),  # URL
        (r"^\s*([^<].*)$", r"<p>\1</p>"),
        (r"(^|\s)(@\w+)", r'<span class="mention">\2</span>'),  # Erwähnungen
    ]

    if not text:
        return text

    result = []
    for line in text.splitlines():
        if line == None or line == "":
            continue
        repl = line
        for pattern, replacement in REPLACEMENTS:
            repl = re.sub(pattern, replacement, repl, flags=re.IGNORECASE)
        result.append(f"\t\t\t\t{repl}")
    return "\n".join(result)


def format_datetime(dt: Union[datetime, date]) -> str:
    """
    Formatiert ein datetime-Objekt mit deutscher Sprache
    """
    # Setze locale auf Deutsch (falls nicht bereits gesetzt)
    try:
        locale.setlocale(locale.LC_TIME, "de_DE.UTF-8")
    except locale.Error:
        try:
            locale.setlocale(locale.LC_TIME, "de_DE")
        except locale.Error:
            pass  # Verwende System-locale

    if isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime(dt.year, dt.month, dt.day)

    today = datetime.now().date()
    dt_date = dt.date()

    # Heute
    if dt_date == today:
        return dt.strftime("%H:%M")

    # Gestern
    if dt_date == today - timedelta(days=1):
        return f"gestern {dt.strftime('%H:%M')}"

    # Wochentag
    if dt_date > today - timedelta(days=7):
        return dt.strftime("%A %H:%M")

    # Datum mit Monat
    if dt_date.year == today.year:
        return dt.strftime("%d. %B")

    # Datum mit Jahr
    return dt.strftime("%d.%m.%Y")

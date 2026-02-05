import locale
import re
from datetime import date, datetime, timedelta
from typing import Union

# Definiere deine regulären Ausdrücke und Ersetzungen
REPLACEMENTS = [
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
    (r"(^|\s)(@\w+)", r'<span class="mention">\2</span>'),  # Erwähnungen
]


def apply_replacements(text):
    """Wendet alle Ersetzungen auf den Text an"""
    if not text:
        return text

    result = text
    for pattern, replacement in REPLACEMENTS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result


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

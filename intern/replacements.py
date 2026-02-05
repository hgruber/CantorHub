import re

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

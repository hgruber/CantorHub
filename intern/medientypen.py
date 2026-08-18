"""Welche Datei ist im Browser abspielbar — und als was.

Eine Quelle für alle Stellen, die das entscheiden: der Ordner-Browser
(`views/folders.py`) und der Wiki-Player (`replacements.py`). filer setzt
`mime_type` nicht zuverlässig — Uploads über den Ordner-Browser landen als
`application/octet-stream` (siehe `fileindex.extract_text`) —, deshalb ist die
Endung gleichberechtigter Rückfall.
"""

import os

AUDIO_ENDUNGEN = (".mp3", ".m4a", ".ogg", ".oga", ".opus", ".wav", ".flac", ".aac")

# .mkv/.avi/.wmv/.flv fehlen bewusst: kein Browser spielt sie verlässlich, sie
# sollen als Datei-Link erscheinen statt als toter Player. Die Regex-Regeln für
# externe URLs in `replacements.py` sind großzügiger — die betreffen aber fremde
# Server, wo wir ohnehin nichts versprechen können.
VIDEO_ENDUNGEN = (".mp4", ".m4v", ".webm", ".ogv", ".mov")


def medientyp(mime, dateiname):
    """`"audio"`, `"video"` oder `None`.

    Der MIME-Typ hat Vorrang, die Endung ist der Rückfall — dieselbe Rangfolge
    wie in `folders._ist_audio()`, sonst treffen die beiden unterschiedliche
    Mengen. `.ogg` ist damit Audio, solange kein `video/ogg` dagegen spricht.
    """
    mime = (mime or "").lower()
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    endung = os.path.splitext(dateiname or "")[1].lower()
    if endung in AUDIO_ENDUNGEN:
        return "audio"
    if endung in VIDEO_ENDUNGEN:
        return "video"
    return None

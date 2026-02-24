import html
import locale
import re
from datetime import date, datetime, timedelta
from typing import Union

from filer.models import File


class ListProcessor:
    def __init__(self):
        self.stack = []  # Speichert die aktiven Listenarten ('ul' oder 'ol') auf den Ebenen

    def process_line(self, line):
        if line.startswith("*"):
            level = line.count("*")
            return self._handle_level(level, line[level:].strip(), "ul")
        elif line.startswith("#"):
            level = line.count("#")
            return self._handle_level(level, line[level:].strip(), "ol")
        else:
            # Normale Zeile - schließe alle offenen Ebenen
            tags = ""
            while self.stack:
                tags += "</ul>" if self.stack.pop() == "ul" else "</ol>"
            if tags == "":
                return line
            return tags

    def _handle_level(self, level, content, tag_type):
        # Schließe überflüssige Ebenen
        while self.stack and len(self.stack) > level:
            # Schließe die äußerste Ebene
            current_type = self.stack.pop()
            tags = f"</{current_type}>"
            return tags + f"<li>{content}</li>"

        # Öffne neue Ebenen
        tags = ""
        while len(self.stack) < level:
            tags += f"<{tag_type}>"
            self.stack.append(tag_type)

        # Prüfe, ob wir eine neue Liste des gleichen Typs öffnen müssen
        if len(self.stack) == level and self.stack[-1] != tag_type:
            # Wechsel von ul zu ol oder umgekehrt
            tags = f"</{self.stack.pop()}><{tag_type}>"
            self.stack.append(tag_type)

        return tags + f"<li>{content}</li>"


class CodeBlockProcessor:
    def __init__(self):
        self.in_code_block = False
        self.code_lines = []

    def process_line(self, line):
        if line.startswith(" "):
            # Eingezogene Zeile - Codeblock
            if not self.in_code_block:
                # Erste eingezogene Zeile - öffne Codeblock
                self.in_code_block = True
                self.code_lines = []
                return "<pre><code>" + html.escape(line), True
            else:
                # Weitere eingezogene Zeile
                return html.escape(line), True
        else:
            # Normale Zeile - schließe Codeblock wenn nötig
            if self.in_code_block:
                self.in_code_block = False
                result = "</code></pre>" + line
                # Füge alle gesammelten Codezeilen hinzu
                if self.code_lines:
                    result = (
                        "<pre><code>"
                        + "".join(self.code_lines)
                        + "</code></pre>"
                        + line
                    )
                return result, False
            else:
                # Normale Zeile, keine aktiven Codeblock
                return line, False


def insert_file_object(f):
    return f'<a href="{f.url}">Datei: {f.original_filename}</a>'


def abstimmung(match, request):
    from intern.models import Abstimmung

    seite = request.resolver_match.kwargs["name"]
    titel = match.group(1)
    abstimmung = seite + ":" + titel
    max_stimmen = match.group(2)
    options = match.group(3).split(";")
    res = Abstimmung.objects.values(
        "person_id", "person__first_name", "person__last_name", "option"
    ).filter(abstimmung=abstimmung)
    context = {
        "titel": titel,
        "max_stimmen": max_stimmen,
        "options": options,
        "result": str(list(res)),
    }
    return str(context)
    return (
        "Abstimmung:" + match.group(1) + " (" + match.group(2) + ") " + match.group(3)
    )


def internal_links(match, request):
    #    print( f"{match.group(1)}\n{match.group(2)}\n{match.group(3)}\n|{match.group(4)}|\n{match.group(5)}\n" )
    if match.group(2) == "Datei:":
        try:
            f = File.objects.get(original_filename=match.group(4))
            return insert_file_object(f)
        except Exception as e:
            return (
                f'<span title="{e}" class="not_found">⚠️ Datei: {match.group(4)}</span>'
            )

    elif match.group(2) == "Aktion:":
        return f"<div>Aktion: {match.group(4)}</div>"
    elif match.group(2) == "Geo:":
        return f"<div>Karte: {match.group(4)}</div>"
    else:
        return f'<a href="/intern/artikel/{match.group(4)}/">{match.group(4)}</a>'


def apply_replacements(text, request=None):
    """Wendet alle Ersetzungen auf den Text an"""

    list_processor = ListProcessor()
    code_processor = CodeBlockProcessor()

    # Definiere deine regulären Ausdrücke und Ersetzungen
    REPLACEMENTS = [
        (r"^======(.*)======$", r"<h5>\1</h5>"),
        (r"^=====(.*)=====$", r"<h4>\1</h4>"),
        (r"^====(.*)====$", r"<h3>\1</h3>"),
        (r"^===(.*)===$", r"<h2>\1</h2>"),
        (r"^==(.*)==$", r"<h1>\1</h1>"),
        (r"^:(.*)$", r'<div class="indent">\1</div>'),
        (r"^%(.*)$", r'<div class="citation">\1</div>'),
        (r"^@(.*)$", r'<div class="boxed">\1</div>'),
        (
            r"(\[\[(([^\]]*?)\:)?\s*([^\[\]]*?)(\|([^\[\]]+?))?\]\]([a-z]+)?)",
            lambda match: internal_links(match, request),
        ),
        (r"\[(https?://[^\s\]]+)\s+([^\]]+)\]", r'<a href="\1">\2</a>'),  # [URL Name]
        (
            r"(?<![\"])(https?://[^\s\"]+\.(?:png|jpg|jpeg|gif|bmp|svg|webp))(?![\"])",
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
        (
            r"(?<![\"])(https?://[^\s\"<>]+)(?![\"])",
            r'<a href="\1">\1</a>',
        ),  # URL
        (r"^\s*([^<].*)$", r"<p>\1</p>"),
        (r"''''([\s\S]*)''''", r"<em><strong>\1</strong></em>"),
        (r"'''([\s\S]*)'''", r"<strong>\1</strong>"),
        (r"''([\s\S]*)''", r"<em>\1</em>"),
        (r'""([\s\S]*)""', r"&quot;\1&quot;"),
        (r"\$([\s\S]*)\$", lambda match: html.escape(match.group(1))),  # no format
        (r"(^|\s)(@\w+)", r'<span class="mention">\2</span>'),  # Erwähnungen
    ]

    FULLTEXT_REPLACEMENTS = [
        (
            r"^{abstimmung:([^:]+):(\d+):([^\}]+)\}",
            lambda match: abstimmung(match, request),
        ),
    ]

    if not text:
        return text

    for pattern, replacement in FULLTEXT_REPLACEMENTS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE | re.MULTILINE)

    result = []
    for line in text.splitlines():
        if line == None or line == "" or re.match(r"^\s+$", line):
            continue
        repl = list_processor.process_line(line)
        if request != None:  # Skip codeblock for forum
            repl, skip_block = code_processor.process_line(repl)
            if skip_block:
                result.append(repl)
                continue
            if repl.startswith("</code></pre>"):
                result.append("</code></pre>\n")
                repl = repl[13:]
        for pattern, replacement in REPLACEMENTS:
            repl = re.sub(pattern, replacement, repl, flags=re.IGNORECASE)
        result.append(f"{repl}")
    return "\n".join(result)


def get_references(article_list):
    pattern = r"\[\[Datei:([^|\]]+)"
    matches = set()

    for artikel in article_list:
        for name in re.findall(pattern, artikel):
            cleaned = name.strip()  # entfernt leading & trailing whitespace
            cleaned = cleaned.strip("\"'")  # entfernt umschließende Quotes
            cleaned = cleaned.strip()  # nochmal strip für Sicherheit
            matches.add(cleaned)
    return list(matches)


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

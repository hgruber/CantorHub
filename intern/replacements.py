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
            return False, self._handle_level(level, line[level:].strip(), "ul")
        elif line.startswith("#"):
            level = line.count("#")
            return False, self._handle_level(level, line[level:].strip(), "ol")
        else:
            # Normale Zeile - schließe alle offenen Ebenen
            tags = ""
            while self.stack:
                tags += "</ul>" if self.stack.pop() == "ul" else "</ol>"
            if tags == "":
                return False, line
            return tags, line

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


class TableProcessor:
    def __init__(self):
        self.in_table = False
        self.in_thead = False

    def _make_row(self, cells, tag):
        return '<tr>' + ''.join(f'<{tag}>{c}</{tag}>' for c in cells) + '</tr>'

    def process_line(self, line):
        """Returns (prefix_to_emit, modified_line)."""
        if line.startswith('!'):
            cells = [c.strip() for c in line[1:].split('!')]
            row = self._make_row(cells, 'th')
            if not self.in_table:
                self.in_table = True
                self.in_thead = True
                return '', '<table class="wiki-table"><thead>' + row
            return '', row
        elif line.startswith('_'):
            parts = [p.strip() for p in line[1:].split('|')]
            row = '<tr><th>' + parts[0] + '</th>' + ''.join(f'<td>{c}</td>' for c in parts[1:]) + '</tr>'
            prefix = ''
            if not self.in_table:
                self.in_table = True
                prefix = '<table class="wiki-table"><tbody>'
            elif self.in_thead:
                self.in_thead = False
                prefix = '</thead><tbody>'
            return prefix, row
        elif line.startswith('|'):
            cells = [c.strip() for c in line[1:].split('|')]
            row = self._make_row(cells, 'td')
            prefix = ''
            if not self.in_table:
                self.in_table = True
                prefix = '<table class="wiki-table"><tbody>'
            elif self.in_thead:
                self.in_thead = False
                prefix = '</thead><tbody>'
            return prefix, row
        else:
            if self.in_table:
                self.in_table = False
                closing = '</thead></table>' if self.in_thead else '</tbody></table>'
                self.in_thead = False
                return closing, line
            return '', line

    def close(self):
        if self.in_table:
            self.in_table = False
            closing = '</thead></table>' if self.in_thead else '</tbody></table>'
            self.in_thead = False
            return closing
        return ''


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

    def close(self):
        if self.in_code_block:
            return "</code></pre>"
        return ""


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
    table_processor = TableProcessor()

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
        if line is None or line == "" or re.match(r"^\s+$", line):
            continue
        line, repl = list_processor.process_line(line)
        if line:
            result.append(f"{line}")
        if request is not None:  # Skip codeblock for forum
            repl, skip_block = code_processor.process_line(repl)
            if skip_block:
                table_closing = table_processor.close()
                if table_closing:
                    result.append(table_closing)
                result.append(repl)
                continue
            if repl.startswith("</code></pre>"):
                result.append("</code></pre>\n")
                repl = repl[13:]
        table_prefix, repl = table_processor.process_line(repl)
        if table_prefix:
            result.append(table_prefix)
        for pattern, replacement in REPLACEMENTS:
            repl = re.sub(pattern, replacement, repl, flags=re.IGNORECASE)
        result.append(f"{repl}")
    result.append(code_processor.close())
    result.append(table_processor.close())
    if request is not None:
        result.append(
            '<p id="footer"><img src="/static/intern/images/JG-Frankfurt-wG-color.svg" style="width: 14px;">&nbsp;Just Gospel!</p>'
        )
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
    same_year = dt.strftime("%Y") == today.strftime("%Y")
    with_time = dt.strftime("%H:%M") != "00:00"

    if dt_date > today:
        if with_time and same_year:
            return dt.strftime("%d.\u00a0%B\u00a0 %H:%M")
        elif with_time:
            return dt.strftime("%d.\u00a0%B\u00a0%Y %H:%M")
        elif same_year:
            return dt.strftime("%d.\u00a0%B")
        else:
            return dt.strftime("%d.\u00a0%B\u00a0%Y")

    # Heute
    if dt_date == today:
        return dt.strftime("%H:%M")

    # Gestern
    if dt_date == today - timedelta(days=1):
        return f"gestern {dt.strftime('%H:%M')}"

    # Wochentag
    if dt_date > today - timedelta(days=7):
        return dt.strftime("%A\u00a0%H:%M")

    # Datum mit Monat
    if dt_date.year == today.year:
        return dt.strftime("%d.\u00a0%B")

    # Datum mit Jahr
    return dt.strftime("%d.%m.%Y")


def format_bytes(size_bytes: int) -> str:
    """
    Konvertiert Byte-Größe in eine formatierte Zeichenkette mit korrekten Metrik-Präfixen.
    Verwendet multiples von 1000 (decimal prefixes).

    Args:
        size_bytes (int): Größe in Bytes

    Returns:
        str: Formatierter String mit Byte-Größe und Präfix (B, k, M, G, T)
    """
    if size_bytes == 0:
        return "0 B"

    # Präfixe in multiples von 1000
    units = ["B", "kB", "MB", "GB", "TB"]
    unit_index = 0
    size = float(size_bytes)

    # Teile durch 1000 solange, bis die Zahl kleiner als 1000 ist
    while size >= 1000 and unit_index < len(units) - 1:
        size /= 1000
        unit_index += 1

    # Runde auf 2 Dezimalstellen, aber entferne führende Nullen
    if size == int(size):
        return f"{int(size)}\u00a0{units[unit_index]}"
    else:
        # Formatiere mit 2 Dezimalstellen, aber entferne führende Nullen
        formatted_size = f"{size:.2f}".rstrip("0").rstrip(".")
        return f"{formatted_size}\u00a0{units[unit_index]}"

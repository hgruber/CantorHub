import html
import locale
import re
from datetime import date, datetime, timedelta
from typing import Union

from intern.app_settings import get_vereinsname_kurz

from easy_thumbnails.files import get_thumbnailer
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


class BlockLineProcessor:
    """Buffers consecutive lines sharing a prefix char into a single <div>."""

    def __init__(self, prefix_char, css_class):
        self.prefix_char = prefix_char
        self.css_class = css_class
        self.active = False
        self.lines = []

    def process_line(self, line):
        """Returns (prefix_to_emit, modified_line).
        modified_line is None while buffering — caller must skip."""
        if line.startswith(self.prefix_char):
            self.lines.append(line[1:].strip())
            self.active = True
            return '', None
        if self.active:
            self.active = False
            block = f'<div class="{self.css_class}">' + ' '.join(self.lines) + '</div>'
            self.lines = []
            return block, line
        return '', line

    def close(self):
        if self.active:
            self.active = False
            block = f'<div class="{self.css_class}">' + ' '.join(self.lines) + '</div>'
            self.lines = []
            return block
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
                return "<pre><code>" + line, True
            else:
                # Weitere eingezogene Zeile
                return line, True
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
    mime = f.mime_type or ""
    filename = html.escape(f.original_filename or "")
    # URLs stammen aus Dateinamen und können Anführungszeichen enthalten —
    # escapen, damit sie das href/src-Attribut nicht verlassen können.
    url = html.escape(f.url)
    caption = f"<figcaption>{filename}</figcaption>"
    if mime.startswith("image") or mime.endswith("pdf"):
        try:
            thumb = get_thumbnailer(f.file).get_thumbnail(
                {"size": (200, 200), "quality": 85}
            )
            alt = html.escape(f.original_filename or "")
            return (
                f'<figure class="wiki-figure">'
                f'<a href="{url}">'
                f'<img src="{html.escape(thumb.url)}" alt="{alt}" class="datei-preview" /></a>'
                f'{caption}</figure>'
            )
        except Exception:
            pass
    return (
        f'<figure class="wiki-figure">'
        f'<a href="{url}">Datei: {filename}</a>'
        f'{caption}</figure>'
    )


ABSTIMMUNG_DIRECTIVE = (
    r"^{abstimmung:([^:]+):(\d+):(?:(\d{1,2}\.\d{1,2}\.\d{4}):)?([^\}]+)\}"
)


def _parse_deadline(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        return None


def parse_abstimmung_directive(text, titel):
    """Findet die Abstimmungs-Direktive mit dem gegebenen Titel im Artikeltext.

    Liefert (max_stimmen, options, deadline) oder None.
    """
    for match in re.finditer(
        ABSTIMMUNG_DIRECTIVE, text or "", re.IGNORECASE | re.MULTILINE
    ):
        if match.group(1).strip() != titel:
            continue
        max_stimmen = int(match.group(2))
        deadline = _parse_deadline(match.group(3))
        options = [o.strip() for o in match.group(4).split(";") if o.strip()]
        return max_stimmen, options, deadline
    return None


def render_abstimmung(
    request,
    seite,
    titel,
    max_stimmen,
    options,
    deadline,
    show_results=False,
    outdated=False,
):
    """Rendert das Abstimmungs-Widget als HTML-String."""
    from django.template.loader import render_to_string

    from intern.models import Abstimmung

    key = f"{seite}:{titel}"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", key).strip("-")

    rows = Abstimmung.objects.values(
        "person_id", "person__first_name", "person__last_name", "option"
    ).filter(abstimmung=key)

    voters_by_option = {}
    my_votes = set()
    for row in rows:
        name = f"{row['person__first_name']} {row['person__last_name']}".strip()
        voters_by_option.setdefault(row["option"], []).append(name)
        if row["person_id"] == request.user.id:
            my_votes.add(row["option"])

    max_count = max((len(v) for v in voters_by_option.values()), default=0)
    option_data = []
    for opt in options:
        voters = sorted(voters_by_option.get(opt, []))
        count = len(voters)
        option_data.append(
            {
                "text": opt,
                "count": count,
                "voters": voters,
                "percent": round(count / max_count * 100) if max_count else 0,
            }
        )

    has_voted = bool(my_votes)
    locked = bool(deadline and date.today() > deadline)
    if locked:
        show_results = True
        option_data.sort(key=lambda o: o["count"], reverse=True)

    deadline_target = None
    if deadline:
        deadline_target = (
            datetime(deadline.year, deadline.month, deadline.day)
            + timedelta(days=1)
        ).isoformat()

    context = {
        "slug": slug,
        "seite": seite,
        "titel": titel,
        "max_stimmen": max_stimmen,
        "options": option_data,
        "my_votes": my_votes,
        "has_voted": has_voted,
        "locked": locked,
        "outdated": outdated,
        "deadline": deadline,
        "deadline_target": deadline_target,
        "show_results": show_results,
    }
    return render_to_string("_abstimmung.html", context, request=request)


def abstimmung(match, request):
    if request is None:
        return ""
    seite = request.resolver_match.kwargs.get("name", "")
    titel = match.group(1).strip()
    max_stimmen = int(match.group(2))
    deadline = _parse_deadline(match.group(3))
    options = [o.strip() for o in match.group(4).split(";") if o.strip()]

    # Voting is only allowed on the most recent article version.
    outdated = False
    version_param = request.GET.get("version")
    if version_param:
        from intern.models import Artikel

        latest = Artikel.objects.filter(name=seite).order_by("-version").first()
        if latest and str(latest.version) != str(version_param):
            outdated = True

    return render_abstimmung(
        request, seite, titel, max_stimmen, options, deadline, outdated=outdated
    )


# Legacy read-only results directive: {auswertung:<key>:<num>}
# where <key> is the full Abstimmung name (may itself contain colons).
AUSWERTUNG_DIRECTIVE = r"^{auswertung:(.+):\d+\}"


def render_auswertung(request, key):
    """Rendert die reine Ergebnisanzeige einer Abstimmung als HTML-String."""
    from django.template.loader import render_to_string

    from intern.models import Abstimmung

    rows = Abstimmung.objects.values(
        "person__first_name", "person__last_name", "option"
    ).filter(abstimmung=key)

    voters_by_option = {}
    for row in rows:
        name = f"{row['person__first_name']} {row['person__last_name']}".strip()
        voters_by_option.setdefault(row["option"], []).append(name)

    max_count = max((len(v) for v in voters_by_option.values()), default=0)
    option_data = [
        {
            "text": opt,
            "count": len(voters),
            "voters": sorted(voters),
            "percent": round(len(voters) / max_count * 100) if max_count else 0,
        }
        for opt, voters in voters_by_option.items()
    ]
    option_data.sort(key=lambda o: o["count"], reverse=True)

    context = {
        "slug": re.sub(r"[^a-zA-Z0-9]+", "-", key).strip("-"),
        "titel": key.rpartition(":")[2] or key,
        "options": option_data,
    }
    return render_to_string("_auswertung.html", context, request=request)


def auswertung(match, request):
    if request is None:
        return ""
    return render_auswertung(request, match.group(1).strip())


def internal_links(match, request):
    #    print( f"{match.group(1)}\n{match.group(2)}\n{match.group(3)}\n|{match.group(4)}|\n{match.group(5)}\n" )
    if match.group(2) == "Datei:":
        try:
            f = File.objects.get(original_filename=match.group(4))
            return insert_file_object(f)
        except Exception as e:
            return (
                f'<span title="{html.escape(str(e))}" class="not_found">⚠️ Datei: {match.group(4)}</span>'
            )

    elif match.group(2) == "Aktion:":
        return f"<div>Aktion: {match.group(4)}</div>"
    elif match.group(2) == "Geo:":
        return f"<div>Karte: {match.group(4)}</div>"
    else:
        prefix = match.group(2) or ""
        name = match.group(4)
        display = match.group(6) or match.group(4)
        if request is not None:
            from intern.models import ArtikelPermission
            perms = ArtikelPermission.objects.filter(artikel_name=name)
            if perms.exists():
                gids = request.user.groups.values_list("id", flat=True)
                up = perms.filter(group_id__in=gids)
                if not (up.filter(can_read=True).exists() or up.filter(can_edit=True).exists()):
                    return display
        return f'<a href="/intern/artikel/{prefix}{name}/">{display}</a>'


def apply_replacements(text, request=None):
    """Wendet alle Ersetzungen auf den Text an"""

    list_processor = ListProcessor()
    code_processor = CodeBlockProcessor()
    table_processor = TableProcessor()
    citation_processor = BlockLineProcessor('%', 'citation')
    indent_processor = BlockLineProcessor(':', 'indent')
    boxed_processor = BlockLineProcessor('@', 'boxed')

    # Definiere deine regulären Ausdrücke und Ersetzungen
    REPLACEMENTS = [
        (r"^======(.*)======$", lambda m: f"<h5>{m.group(1)}</h5>"),
        (r"^=====(.*)=====$", lambda m: f"<h4>{m.group(1)}</h4>"),
        (r"^====(.*)====$", lambda m: f"<h3>{m.group(1)}</h3>"),
        (r"^===(.*)===$", lambda m: f"<h2>{m.group(1)}</h2>"),
        (r"^==(.*)==$", lambda m: f"<h1>{m.group(1)}</h1>"),
        (
            r"(\[\[(([^\]]*?)\:)?\s*([^\[\]]*?)(\|([^\[\]]+?))?\]\]([a-z]+)?)",
            lambda match: internal_links(match, request),
        ),
        (r"\[(https?://[^\s\]]+)\s+([^\]]+)\]", lambda m: f'<a href="{m.group(1)}">{m.group(2)}</a>'),  # [URL Name]
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
        (r"''''([\s\S]*)''''", lambda m: f"<em><strong>{m.group(1)}</strong></em>"),
        (r"'''([\s\S]*)'''", lambda m: f"<strong>{m.group(1)}</strong>"),
        (r"''([\s\S]*)''", lambda m: f"<em>{m.group(1)}</em>"),
        (r'""([\s\S]*)""', lambda m: f"&quot;{m.group(1)}&quot;"),
        (r"\$([\s\S]*)\$", r"\1"),  # no format (content pre-escaped)
        (r"(^|\s)(@\w+)", r'<span class="mention">\2</span>'),  # Erwähnungen
    ]

    FULLTEXT_REPLACEMENTS = [
        (ABSTIMMUNG_DIRECTIVE, lambda match: abstimmung(match, request)),
        (AUSWERTUNG_DIRECTIVE, lambda match: auswertung(match, request)),
    ]

    if not text:
        return text

    # Block-level widgets are rendered up front and stashed behind HTML-comment
    # placeholders so the per-line processing below leaves their markup intact.
    placeholders = {}
    for pattern, replacement in FULLTEXT_REPLACEMENTS:

        def _store(match, _repl=replacement):
            key = f"<!--block-{len(placeholders)}-->"
            placeholders[key] = _repl(match)
            return key

        text = re.sub(pattern, _store, text, flags=re.IGNORECASE | re.MULTILINE)

    result = []
    for line in text.splitlines():
        if line is None or line == "" or re.match(r"^\s+$", line):
            continue
        if not (line.startswith('<!--block-') and line.endswith('-->')):
            line = html.escape(line)
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
        citation_prefix, repl = citation_processor.process_line(repl)
        if repl is None:
            continue
        if citation_prefix:
            result.append(citation_prefix)
        indent_prefix, repl = indent_processor.process_line(repl)
        if repl is None:
            continue
        if indent_prefix:
            result.append(indent_prefix)
        boxed_prefix, repl = boxed_processor.process_line(repl)
        if repl is None:
            continue
        if boxed_prefix:
            result.append(boxed_prefix)
        for pattern, replacement in REPLACEMENTS:
            repl = re.sub(pattern, replacement, repl, flags=re.IGNORECASE)
        result.append(f"{repl}")
    result.append(code_processor.close())
    result.append(table_processor.close())
    result.append(citation_processor.close())
    result.append(indent_processor.close())
    result.append(boxed_processor.close())
    if request is not None:
        result.append(
            f'<p id="footer"><img src="/static/intern/images/JG-Frankfurt-wG-color.svg" style="width: 14px;">&nbsp;{get_vereinsname_kurz()}!</p>'
        )
    output = "\n".join(result)
    for key, value in placeholders.items():
        output = output.replace(key, value)
    return output


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

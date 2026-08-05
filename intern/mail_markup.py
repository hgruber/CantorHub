"""Wiki-orientiertes Markup für E-Mail-Texte aus der Konfiguration.

Die ``MAIL_*``-Schlüssel der ``Konfiguration`` enthalten den **vollständigen**
Mailtext — inklusive Buttons und Hinweisen. Damit sich niemand eine zweite
Syntax merken muss, wird dieselbe Auszeichnung wie im Artikel-Wiki
(``intern/replacements.py``) verwendet:

===============================  ==========================================
``== Titel ==`` … ``======``     Überschrift (5 Ebenen)
``'''fett'''``                   fett
``''kursiv''``                   kursiv
``''''fett kursiv''''``          fett + kursiv
``* Punkt`` / ``# Punkt``        Aufzählung / nummerierte Liste
``% Zeile``                      kleiner grauer Hinweisblock
``@ Zeile``                      hervorgehobene Hinweisbox
``: Zeile``                      eingerückter Absatz
``[https://… Name]``             benannter Link
``$Text$``                       keine Formatierung
``{button:Label}``               Button auf ``{link}``
``{button:Label:URL}``           Button auf eine abweichende URL
===============================  ==========================================

``replacements.py`` wird bewusst nicht wiederverwendet: es erzeugt CSS-Klassen
(in E-Mail-Clients wirkungslos), bettet Bilder/Audio ein und kennt Direktiven,
die in einer Mail nichts verloren haben. Hier entstehen stattdessen Inline-Styles
und aus **einer** Quelle beide MIME-Teile — HTML und Plain-Text.
"""

import html as _html
import re

from intern.app_settings import get_brand_farbe

# Farben analog zum Mail-Layout (Inline-Styles, da E-Mail-Clients kein CSS laden)
# _BRAND kommt aus BRAND_FARBE, wird bewusst nicht hier als Konstante gelesen
# (Projektregel: kein Konfig-Zugriff zur Importzeit) — siehe _button()/_link().
_TEXT = "#111827"
_MUTED = "#6b7280"
_BOX_BG = "#fff3cd"
_BOX_FG = "#856404"

_P = f"margin:0 0 16px 0;color:{_TEXT};font-size:15px;line-height:1.6;"
_NOTE = f"margin:0 0 16px 0;color:{_MUTED};font-size:13px;line-height:1.6;word-break:break-word;"
_INDENT = f"margin:0 0 16px 24px;color:{_TEXT};font-size:15px;line-height:1.6;"
_LIST = f"margin:0 0 16px 0;padding-left:22px;color:{_TEXT};font-size:15px;line-height:1.6;"
_HEADING_SIZES = ["19px", "17px", "16px", "15px", "14px"]

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_HEADING_RE = re.compile(r"^(={2,6})(.*?)\1\s*$")
_BUTTON_RE = re.compile(r"^\{button:([^}]*)\}$")
_BUTTON_PARTS_RE = re.compile(r"^(?P<label>[^:]*)(?::(?P<url>.*))?$")
_STASH_RE = re.compile("\x00(\\d+)\x00")


def render_mail_markup(raw, placeholders=None, link=None):
    """Rendert einen Konfigurationstext zu ``(html, plain)``.

    ``placeholders`` ist ein Dict für ``{platzhalter}``; unbekannte Platzhalter
    bleiben unverändert stehen. ``link`` ist die Ziel-URL für ``{button:Label}``
    ohne eigene URL — fehlt sie, wird der Button weggelassen (kein toter Link).
    """
    if not raw:
        return "", ""
    values = placeholders or {}
    return (
        _render(raw, values, link, html_mode=True),
        _render(raw, values, link, html_mode=False),
    )


def _substitute(raw, values, html_mode):
    """Setzt {platzhalter} ein; im HTML-Modus werden die Werte escaped."""
    def repl(match):
        key = match.group(1)
        if key not in values:
            return match.group(0)
        value = "" if values[key] is None else str(values[key])
        return _escape(value) if html_mode else value

    return _PLACEHOLDER_RE.sub(repl, raw)


def _escape(value):
    """HTML-Escaping ohne Anführungszeichen — ``'`` bleibt erhalten, sonst würde
    die Wiki-Auszeichnung ``'''fett'''`` zerstört. Attributwerte (href) enthalten
    per Konstruktion keine Anführungszeichen."""
    return _html.escape(value, quote=False)


def _render(raw, values, link, html_mode):
    text = _escape(raw) if html_mode else raw
    text = _substitute(text, values, html_mode)

    out = []
    buffer = []          # gesammelte Zeilen des aktuellen Blocks
    kind = None          # None | "p" | "%" | "@" | ":"
    list_items = []      # (level, "ul"|"ol", text)

    def flush_block():
        nonlocal kind
        if buffer:
            out.append(_block(buffer, kind, html_mode))
            buffer.clear()
        kind = None

    def flush_list():
        if list_items:
            out.append(_list(list_items, html_mode))
            list_items.clear()

    for line in text.split("\n"):
        stripped = line.strip()

        if not stripped:
            flush_block()
            flush_list()
            continue

        button = _BUTTON_RE.match(stripped)
        if button:
            flush_block()
            flush_list()
            rendered = _button(button.group(1), link, html_mode)
            if rendered:
                out.append(rendered)
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            flush_block()
            flush_list()
            level = len(heading.group(1)) - 2
            out.append(_heading(heading.group(2).strip(), level, html_mode))
            continue

        if stripped[0] in "*#":
            flush_block()
            level = len(stripped) - len(stripped.lstrip(stripped[0]))
            tag = "ul" if stripped[0] == "*" else "ol"
            list_items.append((level, tag, stripped[level:].strip()))
            continue

        flush_list()
        prefix = stripped[0] if stripped[0] in "%@:" else "p"
        if kind is not None and prefix != kind:
            flush_block()
        kind = prefix
        buffer.append(stripped[1:].strip() if prefix != "p" else stripped)

    flush_block()
    flush_list()

    if html_mode:
        return "\n".join(part for part in out if part)
    return "\n\n".join(part for part in out if part).strip() + "\n"


def _block(lines, kind, html_mode):
    if html_mode:
        body = "<br>".join(_inline(line, True) for line in lines)
        if kind == "%":
            return f'<p style="{_NOTE}">{body}</p>'
        if kind == ":":
            return f'<p style="{_INDENT}">{body}</p>'
        if kind == "@":
            return (
                '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                'border="0" style="margin:0 0 16px 0;">'
                f'<tr><td style="background-color:{_BOX_BG};border-radius:4px;padding:14px 16px;'
                f'color:{_BOX_FG};font-size:14px;line-height:1.6;">{body}</td></tr></table>'
            )
        return f'<p style="{_P}">{body}</p>'
    return "\n".join(_inline(line, False) for line in lines)


def _list(items, html_mode):
    if not html_mode:
        out = []
        counters = {}
        for level, tag, text in items:
            indent = "  " * (level - 1)
            if tag == "ol":
                counters[level] = counters.get(level, 0) + 1
                out.append(f"{indent}{counters[level]}. {_inline(text, False)}")
            else:
                counters.pop(level, None)
                out.append(f"{indent}- {_inline(text, False)}")
        return "\n".join(out)

    html_out = []
    stack = []
    for level, tag, text in items:
        while len(stack) > level or (stack and len(stack) == level and stack[-1] != tag):
            html_out.append(f"</{stack.pop()}>")
        while len(stack) < level:
            style = _LIST if not stack else "margin:6px 0 0 0;padding-left:22px;"
            html_out.append(f'<{tag} style="{style}">')
            stack.append(tag)
        html_out.append(f'<li style="margin:0 0 6px 0;">{_inline(text, True)}</li>')
    while stack:
        html_out.append(f"</{stack.pop()}>")
    return "".join(html_out)


def _heading(text, level, html_mode):
    if not html_mode:
        return _inline(text, False)
    size = _HEADING_SIZES[min(level, len(_HEADING_SIZES) - 1)]
    return (
        f'<p style="margin:0 0 12px 0;color:{_TEXT};font-size:{size};'
        f'font-weight:700;line-height:1.3;">{_inline(text, True)}</p>'
    )


def _button(inner, link, html_mode):
    parts = _BUTTON_PARTS_RE.match(inner)
    label = (parts.group("label") or "").strip()
    url = (parts.group("url") or "").strip() or (link or "")
    if not url or not label:
        return ""
    if not html_mode:
        return f"{label}: {url}"
    url = _escape(url)  # der Fallback-Link kommt ungefiltert aus dem Aufrufer
    brand = get_brand_farbe()
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:0 0 24px 0;">'
        f'<tr><td style="border-radius:4px;background-color:{brand};">'
        f'<a href="{url}" style="display:inline-block;padding:12px 28px;color:#ffffff;'
        'font-size:15px;font-weight:700;text-decoration:none;border-radius:4px;'
        f'background-color:{brand};line-height:1.4;">{label}</a>'
        "</td></tr></table>"
    )


def _link(url, label, html_mode):
    if not html_mode:
        return url if label == url else f"{label}: {url}"
    return (
        f'<a href="{url}" style="color:{get_brand_farbe()};word-break:break-word;">{label}</a>'
    )


def _inline(text, html_mode):
    """Zeichenformatierung innerhalb einer Zeile."""
    stash = []

    def keep(value):
        stash.append(value)
        return f"\x00{len(stash) - 1}\x00"

    # $...$ — Inhalt bleibt unformatiert
    text = re.sub(r"\$([^$]*)\$", lambda m: keep(m.group(1)), text)

    # [https://… Name]
    text = re.sub(
        r"\[(https?://[^\s\]]+)\s+([^\]]+)\]",
        lambda m: keep(_link(m.group(1), m.group(2).strip(), html_mode)),
        text,
    )

    # nackte URLs (Satzzeichen am Ende gehören nicht zur Adresse)
    def bare_url(match):
        url = match.group(0)
        trailing = ""
        while url and url[-1] in ".,;:!?)":
            trailing = url[-1] + trailing
            url = url[:-1]
        return keep(_link(url, url, html_mode)) + trailing

    text = re.sub(r"https?://[^\s<>\"]+", bare_url, text)

    if html_mode:
        text = re.sub(r"''''(.+?)''''", r"<em><strong>\1</strong></em>", text)
        text = re.sub(r"'''(.+?)'''", r"<strong>\1</strong>", text)
        text = re.sub(r"''(.+?)''", r"<em>\1</em>", text)
    else:
        text = re.sub(r"''''(.+?)''''", r"\1", text)
        text = re.sub(r"'''(.+?)'''", r"\1", text)
        text = re.sub(r"''(.+?)''", r"\1", text)

    return _STASH_RE.sub(lambda m: stash[int(m.group(1))], text)

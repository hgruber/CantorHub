import re

from django.template import Library
from django.utils.safestring import mark_safe

register = Library()

_TAG_SPLIT = re.compile(r"(<[^>]*>)")


@register.filter
def highlight(value, query):
    """Wrap case-insensitive occurrences of `query` in the already-rendered HTML
    `value` with a <span class="search-hl">, touching only text between tags so
    HTML markup is never broken. Returns `value` unchanged when `query` is empty.
    """
    value = str(value)
    query = (query or "").strip()
    if not query:
        return mark_safe(value)

    pattern = re.compile(re.escape(query), re.IGNORECASE)
    parts = _TAG_SPLIT.split(value)
    for i, part in enumerate(parts):
        if i % 2 == 0:  # text between tags (odd indices are the tags themselves)
            parts[i] = pattern.sub(
                lambda m: f'<span class="search-hl">{m.group(0)}</span>', part
            )
    return mark_safe("".join(parts))

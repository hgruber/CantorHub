from django_tables2 import RequestConfig


def paginate_ordered(request, probe_table, offset, page_size):
    """Apply the requested column sort to the full dataset, then slice.

    Build probe_table over the complete (unsliced) queryset or list.
    RequestConfig applies ?sort= to the underlying data before slicing,
    so every page window contains the globally-correct items.
    Returns (page_list, has_more).
    """
    RequestConfig(request, paginate=False).configure(probe_table)
    window = list(probe_table.data[offset : offset + page_size + 1])
    has_more = len(window) > page_size
    return (window[:page_size] if has_more else window), has_more

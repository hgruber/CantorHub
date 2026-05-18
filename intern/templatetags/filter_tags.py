from django import template
from django_filters import ModelChoiceFilter, ModelMultipleChoiceFilter
from django.forms import NullBooleanField

register = template.Library()

_NO_FILTER_VALUES = frozenset(("", "unknown", "1"))


@register.inclusion_tag("filter_chips.html")
def filter_chips(filter_obj, request, skip=None):
    chips = []
    get = request.GET
    skip_set = set(skip) if skip else set()

    for field in filter_obj.form:
        name = field.name
        if name in skip_set:
            continue
        values = get.getlist(name)
        if not values or all(v == "" for v in values):
            continue

        # NullBooleanField "unknown" means no filter is applied — skip the chip
        if isinstance(field.field, NullBooleanField) and all(
            v in _NO_FILTER_VALUES for v in values
        ):
            continue

        # Build URL without this param
        params = request.GET.copy()
        del params[name]
        url = request.path + ("?" + params.urlencode() if params else "")

        label = field.label or name
        display_value = None
        chip_type = "default"

        filter_field = filter_obj.filters.get(name)

        if isinstance(field.field, NullBooleanField):
            # "false"/"3" → red chip; "true"/"2" → green chip
            if len(values) == 1 and values[0] in ("false", "3"):
                chip_type = "false"
            else:
                chip_type = "true"
        elif isinstance(filter_field, (ModelChoiceFilter, ModelMultipleChoiceFilter)):
            # Resolve PKs to human-readable names via the filter's queryset,
            # with fallback to the model's full manager in case the filtered
            # queryset excludes the selected object (e.g. inactive user).
            parts = []
            qs = filter_field.queryset
            for v in values:
                if v:
                    try:
                        parts.append(str(qs.get(pk=v)))
                    except Exception:
                        try:
                            parts.append(str(qs.model.objects.get(pk=v)))
                        except Exception:
                            parts.append(v)
            display_value = ", ".join(parts) if parts else None
        elif hasattr(field.field, "choices") and field.field.choices:
            choice_dict = dict(field.field.choices)
            parts = []
            for v in values:
                if v in choice_dict:
                    parts.append(str(choice_dict[v]))
                elif v:
                    parts.append(v)
            display_value = ", ".join(parts) if parts else None
        elif any(v for v in values):
            display_value = ", ".join(v for v in values if v) or None

        chips.append({
            "label": label,
            "value": display_value,
            "url": url,
            "chip_type": chip_type,
        })

    return {"chips": chips}

import django_filters as filters
import django_tables2 as tables
from django.db.models import Q
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import Artikel, Lied, Ort, Termin, User
from .replacements import format_bytes, format_datetime


class ForumTabelle(tables.Table):
    thema = tables.Column()
    zugriff = tables.Column()
    anzahl_mitteilungen = tables.Column(
        verbose_name="Anzahl",
        attrs={"th": {"class": "right"}, "td": {"class": "right"}},
    )

    class Meta:
        row_attrs = {"data-href": lambda record: reverse("forum_view", args=[record.id])}

    def render_zugriff(self, record):
        return format_html(
            "<nobr>{}</nobr><br /><time>{}</time>",
            record.letzter_absender,
            format_datetime(record.zugriff),
        )


class OrdnerTabelle(tables.Table):
    select = tables.CheckBoxColumn(
        accessor="id",
        orderable=False,
        attrs={"th__input": {"class": "select-all"}, "td": {"style": "width: 0px;"}},
    )

    def render_select(self, record, value):
        if record.get("name") == "..":
            return ""
        return format_html(
            '<input type="checkbox" name="select" value="{}" data-type="{}">',
            record["id"],
            record.get("type", ""),
        )
    type = tables.Column(
        attrs={"th": {"style": "width: 15px;"}, "td": {"style": "width: 15px;"}}
    )
    name = tables.Column()
    pfad = tables.Column(verbose_name="Pfad", empty_values=(), orderable=False)
    size = tables.Column(attrs={"td": {"class": "right"}})
    besitzer = tables.Column()
    created = tables.DateTimeColumn()
    modified = tables.DateTimeColumn()

    def render_name(self, record):
        if "original_filename" in record:
            name = record["original_filename"]
        else:
            name = record["name"]
        if record["type"] == "Folder":
            url = reverse("folder_view", args=[record["id"]])
        else:
            url = "/media/" + record["link"]
        return format_html('<a href="{}">{}</a>', url, name)

    def render_type(self, record):
        media = static("filer/icons/file-unknown.svg")
        if record["type"] == "Folder":
            if record["name"] == "..":
                media = static("intern/images/folder-up.svg")
                url = reverse("folder_view", args=[record["id"]])
            else:
                media = static("filer/icons/folder.svg")
                url = reverse("folder_view", args=[record["id"]])
            return format_html('<a href="{}"><img src="{}" /></a>', url, media)
        elif record.get("thumb_url"):
            media = record["thumb_url"]
        elif record["mime"].endswith("pdf"):
            media = static("filer/icons/file-pdf.svg")
        url = f"/media/{record['link']}"
        return format_html('<a href="{}"><img src="{}" /></a>', url, media)

    def render_pfad(self, record):
        return record.get("pfad", "")

    def render_size(self, record):
        if record["type"] == "File":
            return format_bytes(record["size"])
        else:
            return record["count"]

    class Meta:
        attrs = {"class": "table"}
        row_attrs = {
            "data-id": lambda record: "" if record.get("name") == ".." else record["id"],
            "data-type": lambda record: "" if record.get("name") == ".." else record.get("type", ""),
            "data-name": lambda record: (
                "" if record.get("name") == ".."
                else (record.get("original_filename") or record.get("name") or "")
            ),
        }


class TerminTabelle(tables.Table):
    datum = tables.DateTimeColumn()
    kurz = tables.Column(
        verbose_name="Termin",
        orderable=False,
    )
    anwesenheit_option = tables.Column(
        verbose_name="Du",
        orderable=False,
        empty_values=(),
    )
    anzahl_songs = tables.Column(
        verbose_name="Songs",
        orderable=False,
        attrs={"td": {"class": "right"}},
    )
    anzahl_zusagen_sopran = tables.Column(
        verbose_name="S",
        orderable=False,
        attrs={"td": {"class": "right att-yes"}},
    )
    anzahl_zusagen_alt = tables.Column(
        verbose_name="A",
        orderable=False,
        attrs={"td": {"class": "right att-yes"}},
    )
    anzahl_zusagen_tenor = tables.Column(
        verbose_name="T",
        orderable=False,
        attrs={"td": {"class": "right att-yes"}},
    )
    anzahl_zusagen_bass = tables.Column(
        verbose_name="B",
        orderable=False,
        attrs={"td": {"class": "right att-yes"}},
    )
    anzahl_absagen = tables.Column(
        verbose_name="Absage",
        orderable=False,
        attrs={"td": {"class": "right att-no"}},
    )
    anzahl_vielleicht = tables.Column(
        verbose_name="Eventuell",
        orderable=False,
        attrs={"td": {"class": "right att-maybe"}},
    )
    anzahl_keine_angabe = tables.Column(
        verbose_name="Offen",
        orderable=False,
        attrs={"td": {"class": "right att-na"}},
    )
    lang = tables.Column(
        verbose_name="Info",
        orderable=False,
        attrs={"td": {"style": "min-width: 372px;"}},
    )

    def render_datum(self, value):
        return format_datetime(value)

    def render_anwesenheit_option(self, value, record):
        if not record.anwesenheit:
            return ""
        if value == "1":
            return mark_safe('<span class="att-inline att-inline-yes">Zusage</span>')
        elif value == "2":
            return mark_safe('<span class="att-inline att-inline-no">Absage</span>')
        elif value == "3":
            return mark_safe('<span class="att-inline att-inline-maybe">Eventuell</span>')
        else:
            return mark_safe('<span class="att-inline att-inline-na">Offen</span>')

    def render_anzahl_songs(self, value):
        if value > 0:
            return value
        else:
            return ""

    def render_anzahl_zusagen_sopran(self, value, record):
        return self._att_badge(value, "yes") if value and record.anwesenheit else ""

    def render_anzahl_zusagen_alt(self, value, record):
        return self._att_badge(value, "yes") if value and record.anwesenheit else ""

    def render_anzahl_zusagen_tenor(self, value, record):
        return self._att_badge(value, "yes") if value and record.anwesenheit else ""

    def render_anzahl_zusagen_bass(self, value, record):
        return self._att_badge(value, "yes") if value and record.anwesenheit else ""

    def render_anzahl_absagen(self, value, record):
        return self._att_badge(value, "no") if value and record.anwesenheit else ""

    def render_anzahl_vielleicht(self, value, record):
        return self._att_badge(value, "maybe") if value and record.anwesenheit else ""

    def render_anzahl_keine_angabe(self, value, record):
        return self._att_badge(value, "na") if value and record.anwesenheit else ""

    @staticmethod
    def _att_badge(value, kind):
        return format_html('<span class="att-count att-count-{}">{}</span>', kind, value)

    class Meta:
        row_attrs = {"data-href": lambda record: reverse("termin_view", args=[record.id])}


class RepertoireFilter(filters.FilterSet):
    titel = filters.CharFilter(field_name="titel", lookup_expr="icontains")
    tempo = filters.ChoiceFilter(field_name="tempo", choices=Lied.CHOICES)
    original = filters.BooleanFilter(
        field_name="original",
        lookup_expr="isnull",
        exclude=True,
        label="Original",
    )
    aufnahme = filters.BooleanFilter(
        field_name="aufnahme",
        lookup_expr="isnull",
        exclude=True,
        label="Aufnahme",
    )
    sheet = filters.BooleanFilter(
        field_name="pdf",
        lookup_expr="isnull",
        exclude=True,
        label="Notenblatt",
    )
    notensatz = filters.BooleanFilter(
        field_name="noten",
        lookup_expr="isnull",
        exclude=True,
        label="Notensatz",
    )
    dirigent_qs = (
        User.objects.filter(dirigent__isnull=False, is_active=True)
        .distinct()
        .order_by("last_name", "first_name")
    )
    dirigent = filters.ModelMultipleChoiceFilter(
        field_name="dirigent", queryset=dirigent_qs
    )
    solist_qs = (
        User.objects.filter(solist__isnull=False, is_active=True)
        .distinct()
        .order_by("last_name", "first_name")
    )
    solist = filters.ModelMultipleChoiceFilter(field_name="solist", queryset=solist_qs)
    konzert_qs = (
        Termin.objects.filter(konzert__isnull=False).distinct().order_by("-datum")
    )
    konzert = filters.ModelMultipleChoiceFilter(
        field_name="termin", queryset=konzert_qs
    )

    class Meta:
        model = Lied
        fields = [
            "titel",
            "konzert",
            "aktiv",
            "hymne",
            "acapella",
            "weihnacht",
            "tempo",
            "original",
            "aufnahme",
            "notensatz",
            "sheet",
            "solist",
            "dirigent",
        ]


_PLAY_ICON_SVG = (
    '<svg viewBox="0 0 24 24" width="11" height="11" fill="currentColor" '
    'class="audio-btn-icon" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>'
)

_PDF_ICON_SVG = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
    '<polyline points="14 2 14 8 20 8"/>'
    '<line x1="9" y1="13" x2="15" y2="13"/>'
    '<line x1="9" y1="17" x2="13" y2="17"/></svg>'
)

_NOTES_ICON_SVG = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M9 18V5l12-2v13"/>'
    '<circle cx="6" cy="18" r="3"/>'
    '<circle cx="18" cy="16" r="3"/></svg>'
)

_CROSS_SVG = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" aria-hidden="true">'
    '<line x1="12" y1="3" x2="12" y2="21"/>'
    '<line x1="6"  y1="9" x2="18" y2="9"/></svg>'
)

_MIC_SVG = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<rect x="9" y="2" width="6" height="12" rx="3"/>'
    '<path d="M5 11a7 7 0 0 0 14 0"/>'
    '<line x1="12" y1="18" x2="12" y2="22"/>'
    '<line x1="8" y1="22" x2="16" y2="22"/></svg>'
)

_SNOWFLAKE_SVG = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round" aria-hidden="true">'
    '<line x1="12" y1="2"  x2="12" y2="22"/>'
    '<line x1="2"  y1="12" x2="22" y2="12"/>'
    '<line x1="5"  y1="5"  x2="19" y2="19"/>'
    '<line x1="19" y1="5"  x2="5"  y2="19"/></svg>'
)

_TEMPO_LEVELS = {"l": 1, "m": 2, "s": 3}
_TEMPO_LABELS = {"l": "Langsam", "m": "Mittel", "s": "Schnell"}


def _chip_aktiv(active):
    label = "Aktiv" if active else "Archiviert"
    cls = "eig-dot--on" if active else "eig-dot--off"
    return format_html(
        '<span class="eig-chip eig-chip--dot" title="{label}" aria-label="{label}">'
        '<span class="eig-dot {cls}"></span></span>',
        label=label, cls=cls,
    )


def _chip_beats(beats):
    return format_html(
        '<span class="eig-chip eig-chip--beats" title="{bpm} Beats per Minute" '
        'aria-label="{bpm} BPM"><span class="eig-beats">{bpm}</span></span>',
        bpm=beats,
    )


def _chip_tempo(value):
    level = _TEMPO_LEVELS.get(value, 0)
    if not level:
        return ""
    label = _TEMPO_LABELS.get(value, "")
    chevrons = "›" * level
    return format_html(
        '<span class="eig-chip eig-chip--tempo eig-tempo-{level}" '
        'title="Tempo: {label}" aria-label="Tempo {label}">'
        '<span class="eig-tempo">{chev}</span></span>',
        level=level, label=label, chev=chevrons,
    )


def _chip_icon(svg, label, extra_cls=""):
    return format_html(
        '<span class="eig-chip {extra}" title="{label}" aria-label="{label}">{icon}</span>',
        extra=extra_cls, label=label, icon=mark_safe(svg),
    )


def _audio_button_html(url, song_id, title, kind):
    """Render a single play button. kind is 'original' or 'jg'."""
    type_label = "Original" if kind == "original" else "JG Aufnahme"
    badge = "" if kind == "original" else '<span class="audio-btn-label">JG</span>'
    return format_html(
        '<button type="button" class="audio-btn audio-btn--{kind}" '
        'data-audio-url="{url}" data-song-id="{sid}" '
        'data-title="{title}" data-type="{type}" '
        'title="{type} abspielen" aria-label="{type} – {title} abspielen">'
        "{icon}{badge}</button>",
        kind=kind,
        url=url,
        sid=song_id,
        title=title,
        type=type_label,
        icon=mark_safe(_PLAY_ICON_SVG),
        badge=mark_safe(badge),
    )


class RepertoireTabelle(tables.Table):
    original = tables.Column(
        verbose_name="Audio",
        empty_values=(),
        orderable=False,
        attrs={
            "td": {"class": "audio-cell"},
            "th": {"class": "audio-cell-head", "title": "Original / JG Aufnahme"},
        },
    )
    titel = tables.Column(
        attrs={"td": {"data-id": lambda record: record.id}},
    )
    eigenschaften = tables.Column(
        verbose_name="Eigenschaften",
        empty_values=(),
        orderable=False,
        accessor="id",
        attrs={
            "td": {"class": "eig-cell"},
            "th": {"class": "eig-cell-head", "title": "Aktiv / Beats / Tempo / Hymne / Acapella / Weihnachten"},
        },
    )

    pdf = tables.Column(
        verbose_name="PDF",
        empty_values=(),
        orderable=False,
        attrs={
            "td": {"class": "file-icon-cell"},
            "th": {"class": "file-icon-cell-head", "title": "Notenblatt (PDF)"},
        },
    )
    noten = tables.Column(
        verbose_name="Noten",
        empty_values=(),
        orderable=False,
        attrs={
            "td": {"class": "file-icon-cell"},
            "th": {"class": "file-icon-cell-head", "title": "Notensatz"},
        },
    )

    solist = tables.ManyToManyColumn(attrs={"td": {"style": "font-size: 0.8em;"}})
    dirigent = tables.ManyToManyColumn(attrs={"td": {"style": "font-size: 0.8em;"}})

    komponist = tables.Column(attrs={"td": {"style": "font-size: 0.8em;"}})
    bearbeiter = tables.Column(attrs={"td": {"style": "font-size: 0.8em;"}})

    class Meta:
        row_attrs = {"data-href": lambda record: reverse("titel_view", args=[record.id])}

    def __init__(self, *args, visible_fields=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.visible_fields = visible_fields
        if visible_fields is not None:
            for name in list(self.columns.names()):
                if name not in visible_fields:
                    self.columns.hide(name)

    def render_original(self, record):
        parts = []
        if getattr(record, "original", None):
            parts.append(_audio_button_html(
                record.original.url, record.id, record.titel, "original"
            ))
        if getattr(record, "aufnahme", None):
            parts.append(_audio_button_html(
                record.aufnahme.url, f"r{record.id}", record.titel, "jg"
            ))
        if not parts:
            return ""
        return mark_safe("".join(parts))

    def render_pdf(self, record):
        if not getattr(record, "pdf", None):
            return ""
        return format_html(
            '<a href="{url}" target="_blank" rel="noopener" '
            'class="file-icon-btn file-icon-btn--pdf" '
            'title="Notenblatt: {title}" aria-label="Notenblatt {title} öffnen">'
            "{icon}</a>",
            url=record.pdf.url,
            title=record.titel,
            icon=mark_safe(_PDF_ICON_SVG),
        )

    def render_noten(self, record):
        if not getattr(record, "noten", None):
            return ""
        return format_html(
            '<a href="{url}" target="_blank" rel="noopener" '
            'class="file-icon-btn file-icon-btn--notes" '
            'title="Notensatz: {title}" aria-label="Notensatz {title} öffnen">'
            "{icon}</a>",
            url=record.noten.url,
            title=record.titel,
            icon=mark_safe(_NOTES_ICON_SVG),
        )

    def render_eigenschaften(self, record):
        parts = [_chip_aktiv(bool(record.aktiv))]
        if record.beats:
            parts.append(_chip_beats(record.beats))
        tempo_chip = _chip_tempo(record.tempo)
        if tempo_chip:
            parts.append(tempo_chip)
        if record.hymne:
            parts.append(_chip_icon(_CROSS_SVG, "Hymne"))
        if record.acapella:
            parts.append(_chip_icon(_MIC_SVG, "Acapella"))
        if record.weihnacht:
            parts.append(_chip_icon(_SNOWFLAKE_SVG, "Weihnachten"))
        return mark_safe("".join(parts))


class MitgliederFilter(filters.FilterSet):
    stimme = filters.MultipleChoiceFilter(field_name="stimme", choices=User.STIMMEN)
    konzert_qs = Termin.objects.filter(anwesenheit=True).distinct().order_by("-datum")

    status = filters.ChoiceFilter(
        label="Status",
        choices=[
            ("1", "Zusage"),
            ("2", "Absage"),
            ("3", "Eventuell"),
            ("0", "keine Auswahl"),
        ],
        method="filter_status",
    )
    konzert = filters.ModelChoiceFilter(
        label="Termin",
        queryset=konzert_qs,
        method=lambda qs, name, value: qs,
    )

    def filter_status(self, queryset, name, value):
        termin = self.form.cleaned_data.get("konzert")

        if not termin or not value:
            return queryset
        if value == "0":
            return queryset.exclude(zusage__termin=termin)

        return queryset.filter(
            zusage__termin=termin,
            zusage__option=value,
        ).distinct()

    class Meta:
        model = User
        fields = [
            "stimme",
        ]


class MitgliederTabelle(tables.Table):
    avatar = tables.Column()
    first_name = tables.Column()
    last_name = tables.Column()
    stimme = tables.Column()
    email = tables.EmailColumn()
    xmpp = tables.EmailColumn()
    geburtstag = tables.DateColumn()
    last_login = tables.DateTimeColumn()
    mitteilungen = tables.Column(
        attrs={
            "td": {"class": "right"},
        }
    )
    strasse = tables.Column()
    plz = tables.Column()
    ort = tables.Column()
    telefon = tables.Column()
    telefon_job = tables.Column()
    telefon_mobil = tables.Column()
    telefon_job_mobil = tables.Column()
    fax = tables.Column()

    class Meta:
        row_attrs = {"data-href": lambda record: reverse("mitglied_view", args=[record.id])}

    def __init__(self, *args, visible_fields=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.visible_fields = visible_fields
        if visible_fields is not None:
            for name in list(self.columns.names()):
                if name not in visible_fields:
                    self.columns.hide(name)

    def render_avatar(self, value, record):
        if record.avatar:
            # Try to get the thumbnail, fall back to original if needed
            try:
                thumbnail_url = record.avatar.thumbnails.get("admin_clipboard_icon")
            except Exception:
                # If thumbnail is not available, use the original image
                thumbnail_url = record.avatar.url
            return format_html(
                '<a href="{}/"><img src="{}" width="40" height="40"></a>',
                record.id,
                thumbnail_url,
            )
        # Fallback to default avatar image
        return format_html(
            '<img src="{}" width="40" height="40">',
            static("filer/icons/file-unknown.svg"),
        )


class ArtikelTabelle(tables.Table):
    name = tables.Column(verbose_name="Artikel")
    autor = tables.Column(
        verbose_name="Letzter Autor",
        order_by=("autor__last_name", "autor__first_name"),
    )
    datum = tables.DateTimeColumn(verbose_name="Zuletzt bearbeitet")
    size = tables.Column(
        verbose_name="Größe",
        attrs={"th": {"class": "right"}, "td": {"class": "right"}},
    )

    class Meta:
        order_by = "-datum"
        row_attrs = {
            "data-href": lambda record: reverse("article_view", args=[record.name])
        }

    def render_autor(self, value):
        return str(value) if value else ""

    def render_datum(self, value):
        return format_datetime(value)

    def render_size(self, value):
        return format_bytes(value)


class OrtTabelle(tables.Table):
    name = tables.Column(verbose_name="Name")
    strasse = tables.Column(verbose_name="Straße")
    plz = tables.Column(verbose_name="PLZ")
    ort = tables.Column(verbose_name="Ort")

    class Meta:
        attrs = {"class": "table table-hover"}
        row_attrs = {"data-href": lambda record: reverse("ort_view", args=[record.id])}

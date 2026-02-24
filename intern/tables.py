import django_tables2 as tables
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import format_html

from .replacements import format_datetime


class ForumTabelle(tables.Table):
    thema = tables.Column(linkify=("forum_view", {"forum": tables.A("id")}))
    zugriff = tables.Column()
    anzahl_mitteilungen = tables.Column(
        verbose_name="Anzahl",
        attrs={"th": {"class": "right"}, "td": {"class": "right"}},
    )

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
    type = tables.Column(
        attrs={"th": {"style": "width: 15px;"}, "td": {"style": "width: 15px;"}}
    )
    name = tables.Column()
    size = tables.Column(attrs={"td": {"class": "right"}})
    besitzer = tables.Column()
    created = tables.DateTimeColumn()
    modified = tables.DateTimeColumn()

    def render_name(self, record):
        if "original_filename" in record:
            name = record["original_filename"]
        name = record["name"]
        if record["type"] == "Folder":
            url = reverse("folder_view", args=[record["id"]])
        else:
            url = "/media/" + record["link"]
        return format_html('<a href="{}">{}</a>', url, name)

    def render_type(self, record):
        media = static("filer/icons/file-unknown.svg")
        if record["type"] == "Folder":
            media = static("filer/icons/folder.svg")
        elif record["mime"].startswith("image"):
            media = f"/media/{record['link']}"
        elif record["mime"].endswith("pdf"):
            media = static("filer/icons/file-pdf.svg")
        return format_html('<img src="{}" />', media)

    class Meta:
        attrs = {"class": "table"}


class TerminTabelle(tables.Table):
    datum = tables.DateTimeColumn()
    kurz = tables.Column(
        orderable=False,
        linkify=("forum_view", {"forum": tables.A("id")}),  # TODO
    )
    lang = tables.Column(orderable=False)


class RepertoireTabelle(tables.Table):
    titel = tables.Column(linkify=("forum_view", {"forum": tables.A("id")}))  # TODO


class MitgliederTabelle(tables.Table):
    first_name = tables.Column()
    last_name = tables.Column()
    avatar = tables.Column()
    stimme = tables.Column()
    email = tables.EmailColumn()
    geburtstag = tables.DateColumn()
    last_login = tables.DateTimeColumn()
    mitteilungen = tables.Column(
        attrs={
            "td": {"class": "right"},
        }
    )

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

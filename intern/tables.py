import django_tables2 as tables
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import format_html


class FolderFilesTable(tables.Table):
    type = tables.Column(
        attrs={"th": {"style": "width: 15px;"}, "td": {"style": "width: 15px;"}}
    )
    name = tables.Column()
    size = tables.Column(attrs={"td": {"class": "right"}})
    full_name = tables.Column()
    created = tables.DateTimeColumn()
    modified = tables.DateTimeColumn()

    def render_name(self, record):
        if "original_filename" in record:
            name = record["original_filename"]
        name = record["name"]
        url = reverse("folder_view", args=[record["id"]])
        return format_html('<a href="{}">{}</a>', url, name)

    def render_type(self, record):
        if record["type"] == "Folder":
            return format_html('<img src="{}" />', static("filer/icons/folder.svg"))
        if record["mime"].startswith("image"):
            return format_html(
                '<img src="/media/{}" />',
                record["link"],
            )
        return format_html('<img src="{}" />', static("filer/icons/file-unknown.svg"))

    class Meta:
        attrs = {"class": "table"}


class MitgliederTabelle(tables.Table):
    first_name = tables.Column()
    last_name = tables.Column()
    avatar = tables.FileColumn()
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
            return format_html(
                '<a href="{}/"><img src="{}" width="50" height="50"></a>',
                record.id,
                record.avatar.url,
            )
        return format_html(
            '<img src="{}" width="50" height="50">',
            File.objects.get(original_filename="kein_photo.png"),
        )

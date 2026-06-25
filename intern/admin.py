from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import *


class TerminLiedInline(admin.TabularInline):
    model = Konzert
    extra = 0
    fields = ("lied", "position")


class TerminUserInline(admin.TabularInline):
    model = Zusage
    extra = 0
    fields = ("person", "option")


class UserTerminInline(admin.TabularInline):
    model = Zusage
    extra = 0
    fields = ("termin", "option")


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = [
        "first_name",
        "last_name",
        "stimme",
        "email",
        "is_active",
        "is_staff",
        "is_superuser",
        "bild",
    ]
    # fields = []
    # fieldsets = ()
    # readonly_fields = []
    list_filter = ["stimme", "is_active", "is_staff", "is_superuser"]
    search_fields = ["first_name", "last_name", "ort"]
    # ordering_fields = ['first_name']


@admin.register(Artikel)
class ArtikelAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "autor",
        "datum",
    ]


class ForumPermissionInline(admin.TabularInline):
    model = ForumPermission
    extra = 0
    fields = ("group",)


class ForumOptOutInline(admin.TabularInline):
    model = ForumOptOut
    extra = 0
    fields = ("user",)
    raw_id_fields = ("user",)


@admin.register(Forum)
class ForumAdmin(admin.ModelAdmin):
    list_display = [
        "thema",
        "anzahl_mitteilungen",
        "sender",
        "zugriff",
    ]
    inlines = [ForumPermissionInline, ForumOptOutInline]

    def get_queryset(self, request):
        return Forum.objects.extra_data().order_by("-zugriff")

    def anzahl_mitteilungen(self, obj):
        return obj.anzahl_mitteilungen

    def zugriff(self, obj):
        return obj.zugriff


@admin.register(Mitteilung)
class MitteilungAdmin(admin.ModelAdmin):
    list_display = [
        "sender",
        "datum",
        "forum",
        "mitteilung",
    ]
    list_filter = [
        "forum",
        "sender",
    ]


@admin.register(Ort)
class OrtAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "plz",
        "ort",
    ]


@admin.register(Termin)
class TerminAdmin(admin.ModelAdmin):
    list_display = (
        "kurz",
        "ort__name",
        "lang",
        "datum",
        "repertoire",
        "anwesenheit",
    )
    inlines = [TerminLiedInline, TerminUserInline]


@admin.register(Lied)
class LiedAdmin(admin.ModelAdmin):
    list_display = ("titel", "original", "aktiv", "tempo", "beats", "hymne", "acapella")
    list_filter = ("aktiv", "tempo", "hymne", "acapella")
    filter_horizontal = (
        "solist",
        "dirigent",
    )


@admin.register(Abstimmung)
class AbstimmungAdmin(admin.ModelAdmin):
    list_display = (
        "person",
        "abstimmung",
        "option",
    )


@admin.register(TabellenPreferenzen)
class TabellenPreferenzenAdmin(admin.ModelAdmin):
    list_display = (
        "person",
        "tabelle",
        "sichtbare_spalten",
    )


@admin.register(Konfiguration)
class KonfigurationAdmin(admin.ModelAdmin):
    list_display = ("key", "value", "description")
    search_fields = ("key", "description")


@admin.register(ChangeLog)
class ChangeLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "action", "model_name", "object_repr")
    list_filter = ("action", "model_name", "user")
    search_fields = ("object_repr", "model_name")
    readonly_fields = ("timestamp", "user", "action", "model_name", "object_id", "object_repr", "changes")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

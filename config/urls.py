from django.conf.urls.static import static
from django.contrib import admin
from django.conf import settings
from django.urls import include, path
from django.views.generic import RedirectView

from intern import views
from intern.carddav import views as carddav_views

handler400 = "intern.views.custom_400"
handler403 = "intern.views.custom_403"
handler404 = "intern.views.custom_404"
handler500 = "intern.views.custom_500"

urlpatterns = [
    path("favicon.ico", RedirectView.as_view(url="/static/intern/images/JG-Frankfurt-wG-color.svg", permanent=True)),
    path("datenschutz/", views.datenschutz, name="datenschutz"),
    path("tiles/<int:z>/<int:x>/<int:y>.png", views.tiles_proxy, name="tiles_proxy"),
    # Oeffentliche Auftritts-Mailingliste (kein Login)
    path("auftritte/", views.auftritte_anmeldung, name="auftritte_anmeldung"),
    path("auftritte/bestaetigen/<str:token>/", views.auftritte_bestaetigen,
         name="auftritte_bestaetigen"),
    path("auftritte/abmelden/<str:token>/", views.auftritte_abmelden,
         name="auftritte_abmelden"),
    # CardDAV-Adressbuch (eigene HTTP-Basic-Anmeldung, keine Portal-Sitzung).
    # /.well-known/ ist nach RFC 6764 die Adresse, die iOS beim Einrichten
    # allein aus dem Hostnamen ableitet; beide Schreibweisen, damit kein
    # APPEND_SLASH-Redirect dazwischenfunkt.
    path(".well-known/carddav", carddav_views.well_known),
    path(".well-known/carddav/", carddav_views.well_known),
    path("carddav", carddav_views.dav_root),
    path("carddav/", include("intern.carddav.urls")),
    path("", views.home),
    path("intern/", include("intern.urls")),
    path("admin/", admin.site.urls),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

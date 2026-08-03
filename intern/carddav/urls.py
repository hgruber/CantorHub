"""URL-Muster des CardDAV-Diensts.

Jede Sammlung ist mit **und** ohne abschliessenden Schrägstrich eingetragen.
``APPEND_SLASH`` der CommonMiddleware greift nur, wenn der Pfad ohne Schrägstrich
nicht auflöst — und einen 301 mitten im Abgleich quittieren die Clients
unterschiedlich, teils gar nicht.
"""

from django.urls import path

from . import views

app_name = "carddav"

urlpatterns = [
    path("", views.dav_root, name="root"),
    path("principal/<int:pk>/", views.principal, name="principal"),
    path("adressbuch/<int:pk>/", views.home_set, name="home"),
    path("adressbuch/<int:pk>/mitglieder/", views.adressbuch, name="buch"),
    path(
        "adressbuch/<int:pk>/mitglieder/<int:mid>.vcf",
        views.kontakt,
        name="kontakt",
    ),
]

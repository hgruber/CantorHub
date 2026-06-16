from django.conf.urls.static import static
from django.contrib import admin
from django.conf import settings
from django.urls import include, path
from django.views.generic import RedirectView

from intern import views

handler400 = "intern.views.custom_400"
handler403 = "intern.views.custom_403"
handler404 = "intern.views.custom_404"
handler500 = "intern.views.custom_500"

urlpatterns = [
    path("favicon.ico", RedirectView.as_view(url="/static/intern/images/JG-Frankfurt-wG-color.svg", permanent=True)),
    path("", views.home),
    path("intern/", include("intern.urls")),
    path("admin/", admin.site.urls),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

from django.conf.urls.static import static
from django.contrib import admin
from django.conf import settings
from django.urls import include, path

from intern import views

urlpatterns = [
    path("", views.home),
    path("intern/", include("intern.urls")),
    path("admin/", admin.site.urls),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

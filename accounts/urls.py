from django.urls import path

from . import views

urlpatterns = [
    path("<int:forum>/", views.view, name="view"),
    path("more", views.more, name="more"),
    path("send", views.send, name="send"),
]

from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="login.html", next_page="/intern/forum/146/"
        ),
        name="login",
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(next_page="login"),
        name="logout",
    ),
    path("forum/<int:forum>/", views.view, name="view"),
    path("forum/more", views.more, name="more"),
    path("forum/send", views.send, name="send"),
]

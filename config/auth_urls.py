from django.urls import path

from apps.accounts import views

app_name = "auth"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", views.login, name="login"),
    path("refresh/", views.refresh, name="refresh"),
    path("logout/", views.logout, name="logout"),
    path("logout-all/", views.logout_all, name="logout-all"),
    path("verify/", views.verify, name="verify"),
    path("me/", views.me, name="me"),
]

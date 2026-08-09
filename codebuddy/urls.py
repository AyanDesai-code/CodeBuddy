from django.contrib import admin
from django.urls import include, path

from projects import views


urlpatterns = [
    path(
        "",
        views.home,
        name="home",
    ),

    path(
        "admin/",
        admin.site.urls,
    ),

    path(
        "accounts/",
        include("accounts.urls"),
    ),

    path(
        "accounts/",
        include(
            "allauth.urls"
        ),
    ),

    path(
        "projects/",
        include("projects.urls"),
    ),
]
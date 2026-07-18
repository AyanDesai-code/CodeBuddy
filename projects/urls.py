from django.urls import path

from . import views

urlpatterns = [
    path("", views.project_list, name="project_list"),
    path("new/", views.new_project, name="new_project"),
    path("<int:pk>/setup/", views.project_setup, name="project_setup"),
]
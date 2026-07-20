from django.urls import path

from . import views

urlpatterns = [
    path("", views.project_list, name="project_list"),
    path("new/", views.new_project, name="new_project"),
    path("<int:pk>/setup/", views.project_setup, name="project_setup"),
    path("<int:pk>/generate/",views.generate_workspace,name="generate_workspace",),
    path("<int:pk>/workspace/",views.workspace, name="workspace",),
    path("<int:project_pk>/workspace/<int:folder_pk>/",views.workspace_folder,name="workspace_folder",),
]
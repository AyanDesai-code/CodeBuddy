from django.urls import path

from . import views

urlpatterns = [
    path("", views.project_list, name="project_list"),
    path("new/", views.new_project, name="new_project"),
    path("<int:pk>/setup/", views.project_setup, name="project_setup"),
    path("<int:pk>/generate/",views.generate_workspace,name="generate_workspace",),
    path("<int:pk>/workspace/",views.workspace, name="workspace",),
    path("<int:project_pk>/workspace/<int:folder_pk>/",views.workspace_folder,name="workspace_folder",),
    path("<int:project_pk>/workspace/<int:folder_pk>/edit/",views.edit_workspace_folder,name="edit_workspace_folder",),
    path("<int:project_pk>/workspace/<int:folder_pk>/regenerate/",views.regenerate_workspace_folder,name="regenerate_workspace_folder",),
    path("<int:project_pk>/tasks/<int:task_pk>/toggle/",views.toggle_task,name="toggle_task",),
    path("<int:project_pk>/tasks/new/",views.new_task,name="new_task",),
    path("<int:project_pk>/tasks/<int:task_pk>/edit/",views.edit_task,name="edit_task",),
    path("<int:project_pk>/tasks/<int:task_pk>/delete/",views.delete_task,name="delete_task",),
    path("<int:project_pk>/tasks/generate-more/",views.generate_more_tasks,name="generate_more_tasks",),
    path("<int:project_pk>/assistant/",views.workspace_assistant,name="workspace_assistant",),
    path("<int:project_pk>/history/",views.project_change_history,name="project_change_history",),
    path("<int:project_pk>/history/<int:change_pk>/",views.project_change_detail,name="project_change_detail",),
    path("<int:project_pk>/history/<int:change_pk>/undo/",views.undo_project_change,name="undo_project_change",),
    path("<int:project_pk>/review/",views.project_review,name="project_review",),
    path("<int:project_pk>/conflicts/<int:conflict_pk>/resolve/",views.resolve_project_conflict,name="resolve_project_conflict",),
    path("<int:project_pk>/conflicts/<int:conflict_pk>/ignore/",views.ignore_project_conflict,name="ignore_project_conflict",),   
    path("<int:project_pk>/conflicts/<int:conflict_pk>/apply-fix/",views.apply_project_conflict_fix,name="apply_project_conflict_fix",),
]
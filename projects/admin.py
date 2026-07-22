from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import (
    Project,
    ProjectChange,
    ProjectMessage,
    ProjectState,
    Task,
    WorkspaceFolder,
    WorkspaceMessage,
    ProjectHealthReviewRecord
)

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "owner", "status", "created_at")
    search_fields = ("name", "description")
    list_filter = ("status",)


@admin.register(ProjectMessage)
class ProjectMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "role", "created_at")
    list_filter = ("role",)


@admin.register(WorkspaceFolder)
class WorkspaceFolderAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "project", "parent")

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "project",
        "completed",
        "priority",
    )

    list_filter = (
        "completed",
        "priority",
    )

    search_fields = (
        "title",
        "project__name",
    )

    ordering = (
        "project",
        "order",
    )
@admin.register(ProjectState)
class ProjectStateAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project",
        "updated_at",
    )
@admin.register(WorkspaceMessage)
class WorkspaceMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project",
        "role",
        "created_at",
    )

    list_filter = (
        "role",
        "created_at",
    )

@admin.register(ProjectChange)
class ProjectChangeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project",
        "summary",
        "created_at",
    )

    list_filter = (
        "created_at",
    )

    search_fields = (
        "project__name",
        "summary",
        "user_message",
    )
admin.site.register(ProjectHealthReviewRecord)
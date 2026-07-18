from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Project, ProjectMessage, WorkspaceFolder


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
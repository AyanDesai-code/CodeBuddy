from django.db import models

# Create your models here.
from django.conf import settings
from django.db import models


class Project(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        GENERATING = "generating", "Generating"
        ACTIVE = "active", "Active"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="projects",
    )
    name = models.CharField(max_length=150, blank=True)
    original_idea = models.TextField(blank=True)
    project_type = models.CharField(max_length=50, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name or f"Draft Project {self.pk}"

class ProjectMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
    
class WorkspaceFolder(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="folders",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )
    icon = models.CharField(max_length=10, blank=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    folder_type = models.CharField(max_length=50, blank=True)
    order = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order"]
class Task(models.Model):
    class Priority(models.IntegerChoices):
        LOW = 1, "Low"
        MEDIUM = 2, "Medium"
        HIGH = 3, "High"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="tasks",
    )

    title = models.CharField(max_length=200)

    description = models.TextField(blank=True)

    completed = models.BooleanField(default=False)

    priority = models.IntegerField(
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )

    order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-priority", "created_at"]

    def __str__(self):
        return self.title
class ProjectState(models.Model):
    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="state",
    )

    facts = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)



    def __str__(self):
        return f"State for {self.project}"

class WorkspaceMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="workspace_messages",
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
    )

    content = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.get_role_display()}: {self.content[:50]}"
    
class ProjectChange(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="changes",
    )

    user_message = models.TextField()

    summary = models.TextField(blank=True)

    facts_before = models.JSONField(
        default=dict,
        blank=True,
    )

    facts_after = models.JSONField(
        default=dict,
        blank=True,
    )

    sections_before = models.JSONField(
        default=dict,
        blank=True,
    )

    sections_after = models.JSONField(
        default=dict,
        blank=True,
    )

    tasks_before = models.JSONField(
        default=list,
        blank=True,
    )

    tasks_after = models.JSONField(
        default=list,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Change {self.pk} — {self.project}"

class ProjectHealthReviewRecord(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="health_reviews",
    )

    health_score = models.PositiveSmallIntegerField()

    critical_issues = models.JSONField(
        default=list,
        blank=True,
    )

    warnings = models.JSONField(
        default=list,
        blank=True,
    )

    strengths = models.JSONField(
        default=list,
        blank=True,
    )

    summary = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.project.name} — "
            f"{self.health_score}%"
        )

class ProjectConflict(models.Model):
    class Severity(models.TextChoices):
        WARNING = "warning", "Warning"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"
        IGNORED = "ignored", "Ignored"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="conflicts",
    )
    key = models.CharField(
            max_length=100,
            db_index=True,
    )

    review = models.ForeignKey(
        ProjectHealthReviewRecord,
        on_delete=models.CASCADE,
        related_name="conflicts",
    )

    title = models.CharField(
        max_length=255,
    )

    description = models.TextField()

    severity = models.CharField(
        max_length=20,
        choices=Severity.choices,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )

    source_type = models.CharField(
        max_length=50,
        blank=True,
    )

    source_reference = models.CharField(
        max_length=255,
        blank=True,
    )

    suggested_fix = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = [
            "-created_at",
        ]
    

    def __str__(self):
        return (
            f"{self.project.name}: "
            f"{self.title}"
        )
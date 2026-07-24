
# Create your models here.
from django.conf import settings
from django.db import models
from django.utils import timezone


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

    class Status(models.TextChoices):
        TODO = "todo", "To Do"
        IN_PROGRESS = "in_progress", "In Progress"
        REVIEW = "review", "Review"
        DONE = "done", "Done"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="tasks",
    )
    milestone = models.ForeignKey(
        "ProjectMilestone",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )

    title = models.CharField(
        max_length=200,
    )

    description = models.TextField(
        blank=True,
    )

    completed = models.BooleanField(
        default=False,
    )

    priority = models.IntegerField(
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.TODO,
    )

    start_date = models.DateField(
        null=True,
        blank=True,
    )

    due_date = models.DateField(
        null=True,
        blank=True,
    )

    estimated_hours = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
    )

    dependencies = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="dependents",
    )

    order = models.PositiveIntegerField(
        default=0,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = [
            "order",
            "-priority",
            "created_at",
        ]
    @property
    def incomplete_dependencies(self):
        return self.dependencies.exclude(
            status=self.Status.DONE,
        )


    @property
    def is_blocked(self):
        return self.incomplete_dependencies.exists()


    @property
    def is_overdue(self):
        if self.due_date is None:
            return False

        if self.status == self.Status.DONE:
            return False

        return self.due_date < timezone.localdate()

    def __str__(self):
        return self.title

class ProjectMilestone(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="milestones",
    )

    name = models.CharField(
        max_length=200,
    )

    description = models.TextField(
        blank=True,
    )

    target_date = models.DateField(
        null=True,
        blank=True,
    )

    completed = models.BooleanField(
        default=False,
    )

    order = models.PositiveIntegerField(
        default=0,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = [
            "order",
            "target_date",
            "created_at",
        ]

    def __str__(self):
        return self.name

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

class ProjectEvent(models.Model):
    class EventType(models.TextChoices):
        PROJECT_CREATED = (
            "project_created",
            "Project Created",
        )
        WORKSPACE_GENERATED = (
            "workspace_generated",
            "Workspace Generated",
        )
        WORKSPACE_UPDATED = (
            "workspace_updated",
            "Workspace Updated",
        )
        PROJECT_REVIEWED = (
            "project_reviewed",
            "Project Reviewed",
        )
        CONFLICT_FIXED = (
            "conflict_fixed",
            "Conflict Fixed",
        )
        CONFLICT_RESOLVED = (
            "conflict_resolved",
            "Conflict Resolved",
        )
        CONFLICT_IGNORED = (
            "conflict_ignored",
            "Conflict Ignored",
        )
        CHANGE_UNDONE = (
            "change_undone",
            "Change Undone",
        )
        TASK_COMPLETED = (
            "task_completed",
            "Task Completed",
        )
        TASK_REOPENED = (
            "task_reopened",
            "Task Reopened",
        )
        TASK_STATUS_CHANGED = (
            "task_status_changed",
            "Task Status Changed",
        )
        TASK_DEPENDENCIES_CHANGED = (
            "task_dependencies_changed",
            "Task Dependencies Changed",
        )
        SCHEDULE_GENERATED = (
            "schedule_generated",
            "Schedule Generated",
        )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="events",
    )

    event_type = models.CharField(
        max_length=40,
        choices=EventType.choices,
    )

    title = models.CharField(
        max_length=200,
    )

    description = models.TextField(
        blank=True,
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.project.name}: "
            f"{self.get_event_type_display()}"
        )

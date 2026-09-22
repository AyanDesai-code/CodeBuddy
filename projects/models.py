import io
import tarfile

from django.core.files.base import ContentFile
# Create your models here.
from django.conf import settings
from django.db import models
from django.utils import timezone
from pydantic import BaseModel, Field
from decimal import Decimal
from django import forms
class Project(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        GENERATING = "generating", "Generating"
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

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
    schedule_needs_refresh = models.BooleanField(
        default=False,
    )

    schedule_refresh_reason = models.TextField(
        blank=True,
    )

    schedule_last_generated_at = models.DateTimeField(
        null=True,
        blank=True,
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

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
    )

    content = models.TextField()

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return (
            f"{self.get_role_display()}: "
            f"{self.content[:80]}"
        )
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
    assignee = models.ForeignKey(
        "ProjectMembership",
        on_delete=models.SET_NULL,
        related_name="assigned_tasks",
        null=True,
        blank=True,
)
    assigned_at = models.DateTimeField(
        null=True,
        blank=True,
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
    @property
    def duration_days(self):
        if (
            self.start_date is None
            or self.due_date is None
        ):
            return None

        days = (
            self.due_date
            - self.start_date
        ).days + 1

        if days < 1:
            return None

        return days


    @property
    def duration_display(self):
        days = self.duration_days

        if days is None:
            return ""

        if days == 1:
            return "1 day"

        if days < 7:
            return f"{days} days"

        weeks = days // 7
        remaining_days = days % 7

        if weeks == 1:
            week_text = "1 week"
        else:
            week_text = f"{weeks} weeks"

        if remaining_days == 0:
            return week_text

        if remaining_days == 1:
            day_text = "1 day"
        else:
            day_text = f"{remaining_days} days"

        return f"{week_text}, {day_text}"

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
        MEMBER_ADDED = (
            "member_added",
            "Member Added",
        )

        MEMBER_REMOVED = (
            "member_removed",
            "Member Removed",
        )

        MEMBER_ROLE_CHANGED = (
            "member_role_changed",
            "Member Role Changed",
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
from django.conf import settings
from django.db import models

class ProjectRole(models.Model):
    project = models.ForeignKey(
        "Project",
        on_delete=models.CASCADE,
        related_name="project_roles",
    )

    name = models.CharField(
        max_length=80,
    )

    description = models.TextField(
        blank=True,
    )

    responsibilities = models.TextField(
        blank=True,
    )

    skills = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = [
            "name",
        ]

    def __str__(self):
        return self.name
class ProjectMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        EDITOR = "editor", "Editor"
        VIEWER = "viewer", "Viewer"

    project = models.ForeignKey(
        "Project",
        on_delete=models.CASCADE,
        related_name="memberships",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="project_memberships",
    )

    # Permission level
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.VIEWER,
    )

    # Project responsibility/title
    project_role = models.ForeignKey(
        "ProjectRole",
        on_delete=models.SET_NULL,
        related_name="memberships",
        null=True,
        blank=True,
    )

    role_notes = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "project",
                    "user",
                ],
                name="unique_project_member",
            ),
        ]

    def __str__(self):
        title = (
            self.project_role.name
            if self.project_role
            else self.get_role_display()
        )

        return (
            f"{self.user} — "
            f"{self.project} — "
            f"{title}"
        )
    from decimal import Decimal

from django.db import models


class ProjectResource(models.Model):
    class ResourceType(models.TextChoices):
        DOCUMENTATION = (
            "documentation",
            "Documentation",
        )
        TUTORIAL = "tutorial", "Tutorial"
        VIDEO = "video", "Video"
        ARTICLE = "article", "Article"
        COURSE = "course", "Course"
        TOOL = "tool", "Tool"

    project = models.ForeignKey(
        "Project",
        on_delete=models.CASCADE,
        related_name="resources",
    )

    folder = models.ForeignKey(
        "WorkspaceFolder",
        on_delete=models.CASCADE,
        related_name="resources",
    )

    title = models.CharField(
        max_length=255,
    )

    url = models.URLField(
        blank=True,
    )

    description = models.TextField(
        blank=True,
    )

    resource_type = models.CharField(
        max_length=30,
        choices=ResourceType.choices,
        default=ResourceType.DOCUMENTATION,
    )

    difficulty = models.CharField(
        max_length=30,
        blank=True,
    )

    is_official = models.BooleanField(
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
    topic = models.CharField(
        max_length=100,
        blank=True,
    )

    reason_needed = models.TextField(
        blank=True,
    )

    related_task = models.CharField(
        max_length=200,
        blank=True,
    )

    class Meta:
        ordering = [
            "order",
            "pk",
        ]

    def __str__(self):
        return self.title


class BudgetItem(models.Model):
    class Category(models.TextChoices):
        HARDWARE = "hardware", "Hardware"
        ELECTRONICS = "electronics", "Electronics"
        MECHANICAL = "mechanical", "Mechanical"
        SOFTWARE = "software", "Software"
        API = "api", "API"
        HOSTING = "hosting", "Hosting"
        DESIGN = "design", "Design"
        MARKETING = "marketing", "Marketing"
        LABOR = "labor", "Labor"
        OTHER = "other", "Other"

    class RequirementLevel(models.TextChoices):
        REQUIRED = "required", "Required"
        RECOMMENDED = "recommended", "Recommended"
        OPTIONAL = "optional", "Optional"

    class PurchaseStatus(models.TextChoices):
        PLANNED = "planned", "Planned"
        ORDERED = "ordered", "Ordered"
        PURCHASED = "purchased", "Purchased"
        SKIPPED = "skipped", "Skipped"

    project = models.ForeignKey(
        "Project",
        on_delete=models.CASCADE,
        related_name="budget_items",
    )

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        default=Category.OTHER,
    )

    requirement_level = models.CharField(
        max_length=20,
        choices=RequirementLevel.choices,
        default=RequirementLevel.REQUIRED,
    )

    purchase_status = models.CharField(
        max_length=20,
        choices=PurchaseStatus.choices,
        default=PurchaseStatus.PLANNED,
    )

    quantity = models.PositiveIntegerField(default=1)

    unit_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    actual_unit_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    is_recurring = models.BooleanField(default=False)

    is_physical_part = models.BooleanField(
        default=False,
    )

    source_name = models.CharField(
        max_length=100,
        blank=True,
    )

    source_url = models.URLField(blank=True)

    alternative_notes = models.TextField(
        blank=True,
    )

    confidence = models.PositiveSmallIntegerField(
        default=3,
    )

    order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["order", "pk"]

    @property
    def estimated_total(self):
        return self.quantity * self.unit_cost

    @property
    def actual_total(self):
        if self.actual_unit_cost is None:
            return None

        return (
            self.quantity
            * self.actual_unit_cost
        )

    def __str__(self):
        return self.name

class GeneratedLearningResource(BaseModel):
    title: str
    topic: str
    url: str
    description: str
    reason_needed: str
    related_task: str
    difficulty: str

class GitHubRepository(models.Model):
    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="github_repository",
    )

    installation_id = models.BigIntegerField(
    null=True,
    blank=True,
)

    default_branch = models.CharField(
        max_length=255,
        default="main",
    )

    repository_id = models.BigIntegerField(
        unique=True,
    )

    owner = models.CharField(
        max_length=255,
    )

    name = models.CharField(
        max_length=255,
    )

    html_url = models.URLField()

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return (
            f"{self.owner}/{self.name}"
        )


class GitHubIssueLink(models.Model):
    task = models.OneToOneField(
        Task,
        on_delete=models.CASCADE,
        related_name="github_issue_link",
    )

    repository = models.ForeignKey(
        GitHubRepository,
        on_delete=models.CASCADE,
        related_name="issue_links",
    )

    issue_id = models.BigIntegerField(
        unique=True,
    )

    issue_number = models.PositiveIntegerField()

    issue_url = models.URLField()

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return (
            f"{self.repository} "
            f"#{self.issue_number}"
        )
class FeedbackSubmission(models.Model):
    class FeedbackType(models.TextChoices):
        SUGGESTION = (
            "suggestion",
            "Suggestion",
        )
        BUG = (
            "bug",
            "Bug Report",
        )
        FEATURE = (
            "feature",
            "Feature Request",
        )
        OTHER = (
            "other",
            "Other",
        )

    class Priority(models.TextChoices):
        LOW = (
            "low",
            "Nice to have",
        )
        MEDIUM = (
            "medium",
            "Important",
        )
        HIGH = (
            "high",
            "Very important",
        )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feedback_submissions",
    )

    feedback_type = models.CharField(
        max_length=20,
        choices=FeedbackType.choices,
        default=FeedbackType.SUGGESTION,
    )

    title = models.CharField(
        max_length=180,
    )

    message = models.TextField()

    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )

    contact_email = models.EmailField(
        blank=True,
    )

    page_url = models.URLField(
        blank=True,
    )

    is_resolved = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return (
            f"{self.get_feedback_type_display()}: "
            f"{self.title}"
        )
class Notification(models.Model):
    class Type(models.TextChoices):
        PROJECT_ADDED = "project_added", "Added to project"
        TASK_ASSIGNED = "task_assigned", "Task assigned"
        TASK_COMPLETED = "task_completed", "Task completed"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )

    notification_type = models.CharField(
        max_length=50,
        choices=Type.choices,
    )

    project = models.ForeignKey(
        "Project",
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
    )

    task = models.ForeignKey(
        "Task",
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="notifications_created",
        null=True,
        blank=True,
    )

    message = models.CharField(
        max_length=300,
    )

    is_read = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]
class TaskEmailReminder(models.Model):
    class ReminderType(models.TextChoices):
        THREE_DAYS = (
            "three_days",
            "3 Days Before",
        )
        TOMORROW = (
            "tomorrow",
            "Tomorrow",
        )
        TODAY = (
            "today",
            "Today",
        )
        OVERDUE = (
            "overdue",
            "Overdue",
        )

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="email_reminders",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="task_email_reminders",
    )

    reminder_type = models.CharField(
        max_length=30,
        choices=ReminderType.choices,
    )

    sent_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "task",
                    "user",
                    "reminder_type",
                ],
                name=(
                    "unique_task_email_reminder"
                ),
            ),
        ]

from django.conf import settings
from django.db import models


class AgentRun(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        BLOCKED = "blocked", "Blocked"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    project = models.ForeignKey(
        "Project",
        on_delete=models.CASCADE,
        related_name="agent_runs",
    )

    task = models.ForeignKey(
        "Task",
        on_delete=models.CASCADE,
        related_name="agent_runs",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_runs",
    )
    resumed_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resumed_runs",
    )

    model_name = models.CharField(
        max_length=100,
        default="gpt-6-astra",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
    )

    progress = models.PositiveSmallIntegerField(
        default=0,
    )

    current_step = models.CharField(
        max_length=255,
        blank=True,
    )

    result = models.TextField(
        blank=True,
    )
    result = models.TextField(
        blank=True,
    )

    result_summary = models.TextField(
        blank=True,
    )

    result_actions = models.JSONField(
        default=list,
        blank=True,
    )

    result_files = models.JSONField(
        default=list,
        blank=True,
    )

    result_verification = models.JSONField(
        default=list,
        blank=True,
    )

    result_warnings = models.JSONField(
        default=list,
        blank=True,
    )

    error = models.TextField(
        blank=True,
    )

    error = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    started_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )


class AgentRunLog(models.Model):
    run = models.ForeignKey(
        AgentRun,
        on_delete=models.CASCADE,
        related_name="logs",
    )

    message = models.TextField()

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["created_at"]

class AgentRunEvent(models.Model):
    run = models.ForeignKey(
        AgentRun,
        on_delete=models.CASCADE,
        related_name="events",
    )

    event_type = models.CharField(
        max_length=30,
    )

    tool_name = models.CharField(
        max_length=50,
        blank=True,
    )

    data = models.JSONField(
        default=dict,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["created_at"]

class ConnectedAccount(models.Model):
    class Provider(models.TextChoices):
        GITHUB = "github", "GitHub"
        GOOGLE = "google", "Google"
        SLACK = "slack", "Slack"
        NOTION = "notion", "Notion"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="connected_accounts",
    )

    provider = models.CharField(
        max_length=50,
        choices=Provider.choices,
    )

    external_account_id = models.CharField(
        max_length=255,
    )

    external_username = models.CharField(
        max_length=255,
        blank=True,
    )

    access_token = models.TextField()

    refresh_token = models.TextField(
        blank=True,
    )

    token_type = models.CharField(
        max_length=50,
        blank=True,
    )

    scope = models.TextField(
        blank=True,
    )

    access_token_expires_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    refresh_token_expires_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "user",
                    "provider",
                    "external_account_id",
                ],
                name=(
                    "unique_connected_account"
                ),
            ),
        ]

    def __str__(self):
        name = (
            self.external_username
            or self.external_account_id
        )

        return (
            f"{self.user} → "
            f"{self.provider}: {name}"
        )

class AgentWorkspaceRecord(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PRESERVED = "preserved", "Preserved"
        DELETED = "deleted", "Deleted"

    run = models.OneToOneField(
        AgentRun,
        on_delete=models.CASCADE,
        related_name="workspace_record",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    # Where the execution workspace currently lives.
    workspace_path = models.TextField(
        blank=True,
    )

    # Repository state at the time it was loaded.
    repository_owner = models.CharField(
        max_length=255,
        blank=True,
    )

    repository_name = models.CharField(
        max_length=255,
        blank=True,
    )

    repository_branch = models.CharField(
        max_length=255,
        blank=True,
    )

    base_commit_sha = models.CharField(
        max_length=64,
        blank=True,
    )

    last_synced_commit_sha = models.CharField(
        max_length=64,
        blank=True,
    )

    # Recovery information.
    manifest = models.JSONField(
        default=dict,
        blank=True,
    )

    patch = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    preserved_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    workspace_snapshot = models.FileField(
        upload_to="agent_workspace_snapshots/",
        blank=True,
    )

    workspace_snapshot_manifest = models.JSONField(
        default=dict,
        blank=True,
    )

    def __str__(self):
        return f"Workspace for AgentRun {self.run_id}"
class AgentApprovalRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        DENIED = "denied", "Denied"
        CANCELLED = "cancelled", "Cancelled"

    run = models.ForeignKey(
        AgentRun,
        on_delete=models.CASCADE,
        related_name="approval_requests",
    )

    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_agent_approvals",
    )

    action_type = models.CharField(
        max_length=100,
    )

    title = models.CharField(
        max_length=255,
    )

    description = models.TextField()

    tool_name = models.CharField(
        max_length=100,
        blank=True,
    )

    tool_arguments = models.JSONField(
        default=dict,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    consumed_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    continuation_run = models.OneToOneField(
        AgentRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="continued_approval",
    )

    def __str__(self):
        return (
            f"Approval {self.pk}: "
            f"{self.title} ({self.status})"
        )
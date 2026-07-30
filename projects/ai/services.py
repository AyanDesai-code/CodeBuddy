from pydantic import BaseModel, Field
from openai import OpenAI
from typing import Literal
from datetime import date
import time

client = OpenAI()


class GeneratedBudgetItem(BaseModel):
    name: str
    description: str = ""

    category: Literal[
    "hardware",
    "electronics",
    "mechanical",
    "software",
    "api",
    "hosting",
    "design",
    "marketing",
    "labor",
    "other",
] = "other"

    requirement_level: Literal[
        "required",
        "recommended",
        "optional",
    ] = "required"

    quantity: int = Field(
        default=1,
        ge=1,
    )

    unit_cost: float = Field(
        default=0,
        ge=0,
    )

    is_recurring: bool = False
    is_physical_part: bool = False

    source_name: str = ""
    source_url: str = ""

    alternative_notes: str = ""

    confidence: int = Field(
        default=3,
        ge=1,
        le=5,
    )
class GeneratedProjectBudget(BaseModel):
    summary: str = ""

    budget_items: list[
        GeneratedBudgetItem
    ] = Field(default_factory=list)
class ProjectInterviewReply(BaseModel):
    message: str
    ready: bool
SYSTEM_PROMPT = """
You are BuilderOS, an AI operating system for planning software,
hardware, and mixed projects.

Your current role is PROJECT DISCOVERY.

Your job is only to collect enough high-level information to generate
a useful first project workspace.

You are NOT designing the project yet.
You are NOT selecting exact components yet.
You are NOT conducting a full engineering requirements interview.

Ask exactly ONE focused question at a time.

Try to finish discovery within 5 to 8 user answers.

Here is what you need to understand:

- what the user wants to build
- the main goal
- the intended user
- the most important features or requirements
- the approximate budget or target cost
- the approximate timeline
- any major non-negotiable constraints
- the user's experience or available resources, only if highly relevant

Set ready=true once you can have this information, do not ask for anything additional
Do NOT ask low-level questions such as:

- exact ports or protocol versions
- exact component models
- exact libraries or APIs
- PCB details
- wiring details
- certification strategy
- production tooling details
- manufacturing partner details
- exact funding allocation
- detailed regulatory planning
- implementation choices that can be researched later

Do not ask for information already provided.

If the user's latest answer repeats earlier information, acknowledge it
briefly and continue without asking for it again.

Prefer making clearly labeled reasonable assumptions over extending the
interview.

Once you have all the information that ive listed above set ready=true.

When ready=true, the message must briefly summarize the project and say
that BuilderOS is ready to generate the workspace.

Make the whole interaction short and cordial,

Return only the structured response required by ProjectInterviewReply.
"""

TaskStatus = Literal[
    "todo",
    "in_progress",
    "review",
    "done",
]

def generate_reply(project) -> ProjectInterviewReply:
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        }
    ]

    for message in project.messages.order_by("created_at"):
        messages.append(
            {
                "role": message.role,
                "content": message.content,
            }
        )

    response = client.responses.parse(
        model="gpt-5-mini",
        reasoning={
            "effort": "minimal",
        },
        input=messages,
        text_format=ProjectInterviewReply,
    )

    return response.output_parsed
WORKSPACE_PROMPT = """
You are BuilderOS's workspace generator.

Using the complete project discovery conversation, generate a useful
initial workspace for the project.

Return:

- a clear project name
- content for every requested workspace section
- a structured task list

The workspace should help a beginner move from idea to completion.

Keep the content practical, specific, and editable.

Required folder types:

- overview
- requirements
- roadmap
- tasks
- resources
- budget
- learning
- documentation
- testing

Section requirements:

overview:
Summarize what is being built, who it is for, its main goal, constraints,
and any assumptions.

requirements:
List functional requirements, non-functional requirements, constraints,
and success criteria.

roadmap:
Create ordered phases from research and planning through prototyping,
testing, refinement, and completion.

tasks:
Summarize the major work that must be completed. The detailed task list
is returned separately in the tasks field.

resources:
Recommend initial hardware parts, materials, software, libraries,
frameworks, APIs, services, and tools. Only include categories relevant
to the project. Clearly label recommendations requiring verification.

budget:
Provide a concise preliminary budget summary. Mention likely one-time,
recurring, optional, and contingency costs. Clearly label estimates.
Do not attempt to return structured budget records in this section.

learning:
Recommend what the user needs to learn and which official documentation
or types of resources to look for. Do not invent URLs.

documentation:
Create the initial structure for project documentation, including setup,
architecture, decisions, build notes, and maintenance.

testing:
Create a staged testing plan with test goals, procedures, and success
criteria.

Do not claim uncertain prices, compatibility, or technical facts as
guaranteed. Mark estimates and assumptions clearly.

You MUST return exactly one section for every required folder type.

Every folder_type must exactly match one of:

overview
requirements
roadmap
tasks
resources
budget
learning
documentation
testing

Do not omit any section.

TASK REQUIREMENTS

Generate between 8 and 10 useful tasks.

For every task return:

- title
- description
- priority
- status
- dependency_indexes

Task titles must:

- be specific to this project
- begin with an action verb
- represent one clear piece of work
- be ordered from earliest to latest

Keep every task description under 25 words.

Priority must be exactly:

1 = Low
2 = Medium
3 = High

Status must be exactly one of:

todo
in_progress
review
done

New tasks should normally use "todo" unless the project context clearly
indicates the work is already underway or completed.

TASK DEPENDENCY RULES

dependency_indexes must contain the 1-based positions of tasks that must
be completed before the current task can begin.

Example:

Task 1: Define requirements
dependency_indexes: []

Task 2: Create wireframes
dependency_indexes: [1]

Task 3: Choose the technology stack
dependency_indexes: [1]

Task 4: Build the application
dependency_indexes: [2, 3]

Rules:

- Use 1-based task positions, not database IDs.
- A task may depend only on tasks appearing before it.
- Never make a task depend on itself.
- Never reference a task position that does not exist.
- Avoid circular dependencies.
- Use only direct dependencies.
- Do not make every task depend on the immediately previous task.
- Create parallel branches where work can happen independently.
- Most tasks should have zero to two direct dependencies.
- Final testing or release tasks may depend on multiple implementation
  tasks.

IMPORTANT LATENCY REQUIREMENTS

Your goal is to produce a useful first workspace quickly.

Do not generate an exhaustive project plan.

Generate only enough information for the user to immediately begin work.

Limit every workspace section to approximately 75 to 150 words.

Generate exactly one section for each required folder type.

Do not repeat information across sections.

Do not generate large explanations or long paragraphs.

Prefer bullet lists whenever possible.

Assume additional detail can be generated later using BuilderOS tools.

Optimize for speed while remaining useful.
"""
class GeneratedSection(BaseModel):
    folder_type: Literal[
        "overview",
        "requirements",
        "roadmap",
        "tasks",
        "resources",
        "budget",
        "learning",
        "documentation",
        "testing",
    ]

    content: str
class GeneratedTask(BaseModel):
    title: str
    description: str
    priority: int
    status: TaskStatus = "todo"

    # References other generated tasks by their
    # 1-based position in the returned task list.
    dependency_indexes: list[int] = Field(
        default_factory=list
    )
import time

from pydantic import BaseModel


class GeneratedWorkspace(BaseModel):
    project_name: str
    sections: list[GeneratedSection]
    tasks: list[GeneratedTask]


def generate_workspace_content(project) -> GeneratedWorkspace:
    conversation = build_workspace_generation_input(project)

    started_at = time.monotonic()

    try:
        print("Calling OpenAI...")

        response = client.responses.parse(
            model="gpt-5-mini",
            reasoning={
                "effort": "minimal",
            },
            instructions=WORKSPACE_PROMPT,
            input=conversation,
            text_format=GeneratedWorkspace,
        )

        print("OpenAI finished.")

        generated_workspace = response.output_parsed

        if generated_workspace is None:
            print("Raw output:")
            print(response.output)

            raise ValueError(
                "Workspace generation returned no parsed output."
            )

        elapsed = time.monotonic() - started_at

        print("Parsed successfully.")
        print(
            "WORKSPACE GENERATION TIME: "
            f"{elapsed:.2f} seconds"
        )

        return generated_workspace

    except Exception:
        elapsed = time.monotonic() - started_at

        print(
            "WORKSPACE GENERATION FAILED AFTER: "
            f"{elapsed:.2f} seconds"
        )

   
BUDGET_PROMPT = """
You are BuilderOS's project budget and parts-list generator.

Using the project discovery conversation and current workspace, generate
a realistic structured budget and parts list.

Return:

- summary
- budget_items

The budget_items list must contain the meaningful expenses needed to
build, test, operate, and launch the project.

For hardware or mixed projects, consider:

- electronics
- mechanical components
- structural materials
- fasteners
- wires
- connectors
- adapters
- power supplies
- batteries
- development equipment
- testing equipment
- useful spare parts

For software or mixed projects, consider:

- hosting
- databases
- APIs
- domains
- software subscriptions
- design tools
- testing services
- deployment services

For each budget item return:

- name
- description
- category
- requirement_level
- quantity
- unit_cost
- is_recurring
- is_physical_part
- source_name
- source_url
- alternative_notes
- confidence

Allowed category values:

hardware
electronics
mechanical
software
api
hosting
design
marketing
labor
other

requirement_level must be exactly one of:

required
recommended
optional

confidence must be an integer from 1 through 5.

Rules:

- Do not create zero-cost placeholder items.
- Use realistic estimated costs in USD.
- Do not claim prices are live or exact.
- Include source URLs only when reasonably confident they are valid.
- Use an empty string when no reliable URL is available.
- Put required items before recommended and optional items.
- Separate one-time and recurring costs correctly.
- Include only categories relevant to this project.
- Ensure suggested physical parts are mutually compatible.
- Explain cheaper or compatible alternatives when useful.
- Return at least one usable budget item.
"""
def generate_project_budget(
    project,
) -> GeneratedProjectBudget:
    discovery_text = build_compact_discovery_text(
        project
    )

    workspace_text = build_compact_workspace_text(
        project,
        section_types={
            "overview",
            "requirements",
            "roadmap",
            "resources",
            "budget",
        },
        content_limit=1600,
    )

    project_state = getattr(
        project,
        "state",
        None,
    )

    canonical_facts = (
        project_state.facts
        if project_state is not None
        else {}
    )

    generation_input = f"""
PROJECT NAME:

{project.name}


PROJECT DISCOVERY:

{discovery_text}


CANONICAL PROJECT FACTS:

{canonical_facts}


CURRENT WORKSPACE:

{workspace_text}
"""

    started_at = time.monotonic()

    print("Calling OpenAI for project budget...")

    response = client.responses.parse(
        model="gpt-5-mini",
        reasoning={
            "effort": "minimal",
        },
        instructions=BUDGET_PROMPT,
        input=generation_input,
        text_format=GeneratedProjectBudget,
    )

    elapsed = (
        time.monotonic()
        - started_at
    )

    print(
        "BUDGET GENERATION TIME: "
        f"{elapsed:.2f} seconds"
    )

    result = response.output_parsed

    if result is None:
        print(response.output)

        raise ValueError(
            "Budget generation returned "
            "no parsed output."
        )

    if not result.budget_items:
        raise ValueError(
            "Budget generation returned "
            "no budget items."
        )

    print(
        "Generated "
        f"{len(result.budget_items)} "
        "budget items."
    )

    return result
class RegeneratedSection(BaseModel):
    content: str

SECTION_REGENERATION_PROMPT = """
You are BuilderOS, an AI project-planning assistant.

Rewrite one section of an existing project workspace.

Use the complete project discovery conversation and the other workspace
sections as context.

Only rewrite the requested section.

Requirements:

- Keep the result specific to the project.
- Improve clarity, usefulness, organization, and detail.
- Stay consistent with the project's requirements, budget, timeline,
  materials, tasks, and other workspace sections.
- Do not rewrite or discuss unrelated sections.
- Do not include commentary about the rewriting process.
- Return only the replacement content for the requested section.
"""
def regenerate_workspace_section(
    project,
    folder,
) -> RegeneratedSection:
    conversation_text = "\n\n".join(
        f"{message.role.upper()}: {message.content}"
        for message in project.messages.order_by("created_at")
    )

    workspace_text = "\n\n".join(
        (
            f"SECTION: {workspace_folder.name}\n"
            f"{workspace_folder.description}"
        )
        for workspace_folder in project.folders.order_by("order")
        if workspace_folder.pk != folder.pk
    )

    current_section = (
        f"SECTION TO REWRITE: {folder.name}\n\n"
        f"CURRENT CONTENT:\n{folder.description}"
    )

    regeneration_input = f"""
PROJECT DISCOVERY CONVERSATION:

{conversation_text}

OTHER WORKSPACE SECTIONS:

{workspace_text}

{current_section}
"""

    response = client.responses.parse(
        model="gpt-5-mini",
        reasoning={
            "effort": "minimal",
        },
        instructions=SECTION_REGENERATION_PROMPT,
        input=regeneration_input,
        text_format=RegeneratedSection,
    )

    return response.output_parsed

class AdditionalTasks(BaseModel):
    tasks: list[GeneratedTask]
MORE_TASKS_PROMPT = """
You are BuilderOS, an AI project-planning assistant.

Generate additional actionable tasks for an existing project.

Use the project discovery conversation, current workspace, and existing
tasks as context.

Requirements:

- Generate 3 to 5 useful new tasks.
- Do not repeat or closely duplicate an existing task.
- Fill meaningful gaps in the current plan.
- Keep tasks specific to this project.
- Begin each title with an action verb.
- Each task should represent one clear piece of work.
- Respect the project's budget, requirements, timeline, and resources.
- Do not recreate tasks merely because they are completed.
- priority must be exactly:
  1 = Low
  2 = Medium
  3 = High
  Every generated task must also include:

status

Status must be one of:

todo
in_progress
review
done

New tasks should almost always use "todo".
"""
def generate_additional_tasks(
    project,
) -> AdditionalTasks:
    conversation_text = "\n\n".join(
        (
            f"{message.role.upper()}: "
            f"{message.content}"
        )
        for message in project.messages.order_by(
            "created_at"
        )
    )

    workspace_text = "\n\n".join(
        (
            f"SECTION: {folder.name}\n"
            f"{folder.description}"
        )
        for folder in project.folders.order_by(
            "order"
        )
    )

    existing_tasks_text = "\n".join(
        (
            f"- {task.title} | "
            f"Priority: "
            f"{task.get_priority_display()} | "
            f"Completed: {task.completed}"
        )
        for task in project.tasks.order_by(
            "order"
        )
    )

    generation_input = f"""
PROJECT DISCOVERY:

{conversation_text}

CURRENT WORKSPACE:

{workspace_text}

EXISTING TASKS:

{existing_tasks_text}
"""

    started_at = time.monotonic()

    response = client.responses.parse(
        model="gpt-5-mini",
        reasoning={
            "effort": "minimal",
        },
        instructions=MORE_TASKS_PROMPT,
        input=generation_input,
        text_format=AdditionalTasks,
    )

    elapsed = (
        time.monotonic()
        - started_at
    )

    print(
        "ADDITIONAL TASK GENERATION TIME: "
        f"{elapsed:.2f} seconds"
    )

    result = response.output_parsed

    if result is None:
        raise ValueError(
            "Additional task generation returned "
            "no parsed output."
        )

    return result
class CanonicalFactUpdate(BaseModel):
    key: str
    previous_value: str | None
    new_value: str
    reason: str


class WorkspaceChangeAnalysis(BaseModel):
    summary: str
    canonical_updates: list[CanonicalFactUpdate]

    affected_sections: list[
        Literal[
            "overview",
            "requirements",
            "roadmap",
            "tasks",
            "resources",
            "budget",
            "learning",
            "documentation",
            "testing",
        ]
    ]

    assistant_message: str
    impact_explanation: str
VALID_WORKSPACE_SECTIONS = {
    "overview",
    "requirements",
    "roadmap",
    "tasks",
    "resources",
    "budget",
    "learning",
    "documentation",
    "testing",
}


def normalize_affected_sections(
    sections,
) -> list[str]:
    normalized = []
    seen = set()

    for section in sections:
        section_type = (
            str(section)
            .strip()
            .lower()
        )

        if section_type not in VALID_WORKSPACE_SECTIONS:
            continue

        if section_type in seen:
            continue

        seen.add(section_type)
        normalized.append(section_type)

    return normalized
WORKSPACE_CHANGE_PROMPT = """
You are BuilderOS, a dependency-aware AI project manager.

Analyze the user's latest workspace-assistant message.

Your job is only to identify the requested project change and determine
the smallest set of project data that must change.

Do not rewrite workspace sections.
Do not modify tasks.
Do not claim that changes have already been applied.

You will receive:

- original project discovery
- current canonical project facts
- current workspace sections
- current tasks
- recent workspace-assistant conversation
- latest user request

Return:

1. A concise summary of the requested change.
2. Canonical fact updates.
3. The minimum set of affected workspace sections.
4. A brief assistant message.
5. A concise impact explanation.

MINIMAL-CHANGE RULE

Select a section only when its current content would become inaccurate,
contradictory, incomplete, or misleading because of the user's change.

Do not select a section merely because it is loosely related.

Do not select every downstream section by default.

Preserve unaffected content.

SECTION SELECTION GUIDANCE

overview:
Select only when the project's core purpose, target user, main goal,
major constraint, or central assumption changed.

requirements:
Select when a functional requirement, non-functional requirement,
constraint, success criterion, or measurable target changed.

roadmap:
Select only when sequencing, phases, deadlines, dependencies, or major
implementation direction must change.

tasks:
Select only when existing tasks must be added, removed, renamed, reprioritized,
or otherwise updated.

resources:
Select when required materials, components, software, APIs, services,
tools, or compatibility requirements changed.

budget:
Select when prices, budget limits, allocations, recurring costs,
contingency, or cost assumptions changed.

learning:
Select only when the user must learn a meaningfully different skill,
technology, process, standard, or tool.

documentation:
Select only when architecture notes, setup instructions, decisions,
maintenance information, or documentation structure must change.

testing:
Select when validation methods, safety checks, acceptance criteria,
performance targets, or test procedures changed.

EXAMPLES

User:
"Increase the total budget from $5,000 to $8,000."

Usually affected:
- budget

Possibly affected:
- resources, but only if the larger budget enables a specifically
  requested resource change

Usually not affected:
- overview
- roadmap
- learning
- documentation
- testing
- tasks

User:
"Change the deadline from 12 months to 6 months."

Usually affected:
- roadmap
- tasks

Possibly affected:
- requirements, only if scope or success criteria must change

User:
"Replace the Raspberry Pi with an ESP32."

Usually affected:
- requirements
- resources
- tasks
- documentation
- testing

Possibly affected:
- roadmap, only if implementation sequencing changes

Usually not affected:
- budget unless costs meaningfully change
- overview unless this changes the project's core definition
- learning unless new skills are required

User:
"Add Bluetooth control."

Usually affected:
- requirements
- resources
- tasks
- documentation
- testing

Do not include sections that can remain accurate without modification.

CANONICAL FACT RULES

- Treat explicit user changes as authoritative.
- Include only facts that actually changed.
- Use short, stable keys.
- previous_value may be null if no previous fact exists.
- new_value must be a string.
- Do not create duplicate fact updates.

The assistant_message should briefly state what BuilderOS understood.
Do not say that the workspace has already been updated.

The impact_explanation must be 1 to 3 sentences.

Do not ask follow-up questions unless the request is impossible to
interpret.

If information is missing, make the smallest clearly labeled reasonable
assumption.

Return only the structured WorkspaceChangeAnalysis response.
"""
def truncate_text(
    value: str | None,
    limit: int,
) -> str:
    text = (value or "").strip()

    if len(text) <= limit:
        return text

    return (
        text[:limit].rstrip()
        + "\n[truncated]"
    )


def build_compact_discovery_text(
    project,
) -> str:
    messages = list(
        project.messages.order_by(
            "created_at"
        )
    )

    if not messages:
        return "No discovery conversation exists."

    first_user_message = next(
        (
            message
            for message in messages
            if message.role == "user"
        ),
        None,
    )

    final_assistant_message = next(
        (
            message
            for message in reversed(
                messages
            )
            if message.role == "assistant"
        ),
        None,
    )

    parts = []

    if first_user_message is not None:
        parts.append(
            "ORIGINAL IDEA:\n"
            + truncate_text(
                first_user_message.content,
                1200,
            )
        )

    if final_assistant_message is not None:
        parts.append(
            "DISCOVERY SUMMARY:\n"
            + truncate_text(
                final_assistant_message.content,
                2200,
            )
        )

    return "\n\n".join(parts)


def build_recent_workspace_messages(
    project,
    limit: int = 6,
) -> str:
    recent_messages = list(
        project.workspace_messages
        .order_by("-created_at")[:limit]
    )

    recent_messages.reverse()

    if not recent_messages:
        return (
            "No previous workspace-assistant "
            "conversation exists."
        )

    return "\n\n".join(
        (
            f"{message.role.upper()}:\n"
            f"{truncate_text(message.content, 900)}"
        )
        for message in recent_messages
    )


def build_compact_workspace_text(
    project,
    *,
    section_types=None,
    content_limit: int = 1800,
) -> str:
    folders = project.folders.order_by(
        "order"
    )

    if section_types is not None:
        folders = folders.filter(
            folder_type__in=section_types
        )

    section_blocks = []

    for folder in folders:
        content = truncate_text(
            folder.description,
            content_limit,
        )

        section_blocks.append(
            (
                f"SECTION TYPE: "
                f"{folder.folder_type}\n"
                f"SECTION NAME: "
                f"{folder.name}\n"
                f"CONTENT:\n"
                f"{content}"
            )
        )

    return (
        "\n\n".join(section_blocks)
        or "No workspace sections exist."
    )

def build_compact_tasks_text(
    project,
    *,
    include_descriptions: bool = False,
    description_limit: int = 300,
) -> str:
    tasks = project.tasks.order_by(
        "order"
    )

    task_blocks = []

    for task in tasks:
        lines = [
            f"TASK ID: {task.pk}",
            f"TITLE: {task.title}",
            f"PRIORITY: {task.priority}",
            f"STATUS: {task.status}",
            f"COMPLETED: {task.completed}",
        ]

        if include_descriptions:
            lines.insert(
                2,
                (
                    "DESCRIPTION: "
                    + truncate_text(
                        task.description,
                        description_limit,
                    )
                ),
            )

        task_blocks.append(
            "\n".join(lines)
        )

    return (
        "\n\n".join(task_blocks)
        or "No tasks exist."
    )


CASCADE_SECTION_PROMPT = """
You are BuilderOS, a dependency-aware AI project manager.

Rewrite exactly one workspace section after a project-level change.

You will receive:

- the original project discovery conversation
- the user's requested change
- the updated canonical project facts
- the current tasks
- all workspace sections
- the specific section to rewrite

Requirements:

- Return only replacement content for the requested section.
- Keep the section consistent with the updated canonical facts.
- Use already-updated sections as authoritative context.
- Preserve useful information that is still valid.
- Remove or revise information contradicted by the new project facts.
- Keep the content practical, specific, organized, and editable.
- Clearly label estimates, assumptions, risks, and uncertain facts.
- Do not claim uncertain compatibility, prices, or performance as guaranteed.
- Do not discuss the rewriting process.
- Do not rewrite unrelated sections.

Section-specific expectations:

overview:
Update the project summary, goal, users, constraints, risks, and assumptions.

requirements:
Update functional requirements, non-functional requirements, constraints,
success criteria, and measurable targets.

resources:
Update relevant hardware, materials, software, libraries, APIs, tools,
services, and compatibility considerations.

budget:
Update cost categories and estimates based on the revised requirements
and resources.

roadmap:
Update phases, dependencies, sequencing, decision gates, and timeline
based on the revised requirements, resources, and budget.

learning:
Update the knowledge and documentation the user must study.

testing:
Update test goals, procedures, metrics, acceptance criteria, and safety checks.

documentation:
Update the documentation structure, setup notes, architecture notes,
decisions, build notes, and maintenance guidance.

The tasks section is managed separately and must not be rewritten here.
"""

class TaskToUpdate(BaseModel):
    task_id: int
    new_title: str
    description: str
    priority: int
    status: TaskStatus | None = None

class TaskSynchronization(BaseModel):
    tasks_to_add: list[GeneratedTask]
    tasks_to_update: list[TaskToUpdate]
    task_ids_to_remove: list[int]
    summary: str

TASK_SYNCHRONIZATION_PROMPT = """
You are BuilderOS, a dependency-aware AI project manager.

Synchronize an existing project's task list after a project-level change.

You will receive:

- the requested project change
- updated canonical project facts
- updated workspace sections
- all existing tasks and their completion status

Return:

- tasks_to_add
- tasks_to_update
- task_ids_to_remove
- a short summary

Rules:

- Every existing task includes a TASK ID.
- Use task_id to identify tasks that should be updated.
- task_ids_to_remove must contain only valid IDs of existing unfinished tasks.
- Never request removal of a completed task.
- Prefer updating an existing task rather than deleting it and creating a replacement.
- Do not use task titles as identifiers.
- Keep tasks consistent with the updated project facts and workspace.
- Do not recreate work already represented by an existing task.
- Do not add near-duplicate tasks.
- Preserve useful tasks that are still relevant.
- Begin all new task titles with an action verb.
- Every task must be one clear, actionable piece of work.
- Priority must be exactly:
  1 = Low
  2 = Medium
  3 = High

  Each task also has a workflow status.

Allowed values:

todo
in_progress
review
done

When updating a task:

- Preserve its current status unless the project change clearly requires
  moving it.
- Use review only if the work is awaiting testing, validation, or
  approval.
- Use done only if the project clearly states the work is complete.

Return status for every added and updated task.

Return only the structured response required by TaskSynchronization.
"""

class UpdatedWorkspaceSection(BaseModel):
    folder_type: str
    content: str

class WorkspaceUpdatePlan(BaseModel):
    summary: str
    canonical_updates: list[CanonicalFactUpdate]

    affected_sections: list[
        Literal[
            "overview",
            "requirements",
            "roadmap",
            "tasks",
            "resources",
            "budget",
            "learning",
            "documentation",
            "testing",
        ]
    ]

    sections: list[UpdatedWorkspaceSection]

    tasks_to_add: list[GeneratedTask]
    tasks_to_update: list[TaskToUpdate]
    task_ids_to_remove: list[int]

    task_summary: str
    assistant_message: str
    impact_explanation: str
FAST_WORKSPACE_UPDATE_PROMPT = """
You are BuilderOS, a fast dependency-aware AI project manager.

Apply one requested project change to an existing workspace.

You will receive:

- a compact project discovery summary
- current canonical project facts
- current workspace sections
- current database-backed tasks
- recent workspace-assistant messages
- the latest user request

Return one complete update plan containing:

1. A concise summary of the requested change.
2. Canonical fact updates.
3. The minimum set of affected workspace sections.
4. Replacement content for affected text sections.
5. Task additions, updates, and removals.
6. A concise user-facing response.
7. A short explanation of why the changes matter.

MINIMAL CHANGE RULES

- Change only what the user requested.
- Do not rewrite unaffected sections.
- Do not select a section merely because it is loosely related.
- Preserve valid existing information.
- Make the smallest reasonable interpretation.
- Do not add optional features the user did not request.

VALID WORKSPACE SECTIONS

overview
requirements
roadmap
tasks
resources
budget
learning
documentation
testing

TEXT SECTION RULES

The following are text sections:

overview
requirements
roadmap
resources
budget
learning
documentation
testing

- Return replacement content only for affected text sections.
- Do not return a text replacement for "tasks".
- Tasks are stored separately in the database.
- Keep each returned section under 180 words.
- Prefer short headings and bullet lists.
- Clearly label estimates and assumptions.

TASK RULES

- Existing tasks are identified by TASK ID.
- Never invent a task ID.
- Prefer updating an existing task over deleting it.
- Never remove completed tasks.
- Remove only unfinished tasks made obsolete by the change.
- Avoid duplicate or near-duplicate tasks.
- Add no more than 5 tasks.
- Keep task descriptions under 35 words.
- Priority must be exactly 1, 2, or 3.
- Status must be exactly one of:

todo
in_progress
review
done

- Preserve an existing task's status unless the request clearly requires
  changing it.

CANONICAL FACT RULES

- Include only facts that actually changed.
- Use short, stable keys.
- previous_value may be null.
- new_value must be a string.
- Do not create duplicate updates.

RESPONSE RULES

- summary must be concise.
- assistant_message should state what BuilderOS changed.
- impact_explanation must be 1 to 3 sentences.
- task_summary should briefly describe task-list changes.
- Do not ask discovery questions.
- Do not describe internal reasoning.
- Return only the structured WorkspaceUpdatePlan response.
"""
class RegeneratedWorkspaceSections(BaseModel):
    sections: list[UpdatedWorkspaceSection]
    
    

    
COMBINED_CASCADE_PROMPT = """
You are BuilderOS, a dependency-aware AI project manager.

Rewrite all requested workspace sections after a project-level change.

You will receive:

- the original project discovery conversation
- the workspace assistant conversation
- the requested project change
- updated canonical project facts
- current workspace sections
- current database-backed tasks
- the exact section types that must be rewritten

Requirements:

- Return exactly one replacement for every requested section type.
- Do not return any section type that was not requested.
- Keep all returned sections mutually consistent.
- Treat the updated canonical project facts as authoritative.
- Preserve useful existing information that is still valid.
- Remove or revise information contradicted by the updated facts.
- Do not invent optional features the user did not request.
- Make the smallest reasonable interpretation of broad requests.
- Clearly label assumptions, estimates, risks, and uncertainties.
- Keep content practical, specific, organized, and editable.
- Do not describe the rewriting process.
- Do not rewrite the database-backed tasks section.

Valid section types are:

overview
requirements
roadmap
resources
budget
learning
documentation
testing
"""

class ProjectHealthFinding(BaseModel):
    key: str
    title: str
    description: str
    severity: Literal[
        "critical",
        "warning",
    ]
    source_type: str
    source_reference: str
    suggested_fix: str

class ProjectHealthReview(BaseModel):
    health_score: int
    findings: list[ProjectHealthFinding]
    strengths: list[str]
    summary: str

PROJECT_HEALTH_PROMPT = """
You are BuilderOS.

Review the project.

You are NOT modifying anything.

Evaluate:

- consistency
- missing information
- contradictions
- project risk
- testing coverage
- documentation quality
- task quality

Health score:

0-100

Return:

- health_score
- findings
- strengths
- summary

Every finding must contain:

- title
- description
- severity
- source_type
- source_reference
- suggested_fix

Severity must be exactly:

- critical
- warning

source_type should identify where the issue was found, such as:

- task
- requirement
- budget
- testing
- roadmap
- documentation
- canonical_fact
- cross_section

source_reference should be a useful identifier, such as:

- task ID and task title
- workspace section name
- canonical fact key
- multiple section names for a cross-section conflict

Do not create duplicate findings for the same underlying problem.

Never invent problems.

Only report issues supported by the workspace.

Every finding must include a stable key.

The key must:

- identify the underlying issue, not the exact wording
- use lowercase snake_case
- remain exactly the same across future reviews for the same issue
- be short and specific
- not include task database IDs unless the issue is unique to that exact task

Examples:

- g0_portability_unresolved
- heater_scope_conflict
- retail_price_infeasible
- missing_task_owners
- invalid_task_content
- thermal_feasibility_incomplete
- missing_completed_task_evidence

Every finding must contain:

- key
- title
- description
- severity
- source_type
- source_reference
- suggested_fix
"""
def generate_workspace_update_plan(
    project,
) -> WorkspaceUpdatePlan:
    project_state = getattr(
        project,
        "state",
        None,
    )

    current_facts = (
        project_state.facts
        if project_state is not None
        else {}
    )

    latest_user_message = (
        project.workspace_messages
        .filter(role="user")
        .order_by("-created_at")
        .first()
    )

    if latest_user_message is None:
        raise ValueError(
            "No workspace assistant user message exists."
        )

    discovery_text = build_compact_discovery_text(
        project
    )

    workspace_text = build_compact_workspace_text(
        project,
        content_limit=1400,
    )

    tasks_text = build_compact_tasks_text(
        project,
        include_descriptions=True,
        description_limit=250,
    )

    assistant_text = build_recent_workspace_messages(
        project,
        limit=6,
    )

    generation_input = f"""
PROJECT DISCOVERY SUMMARY:

{discovery_text}


CURRENT CANONICAL FACTS:

{current_facts}


CURRENT WORKSPACE:

{workspace_text}


CURRENT DATABASE-BACKED TASKS:

{tasks_text}


RECENT WORKSPACE-ASSISTANT CONVERSATION:

{assistant_text}


LATEST USER REQUEST:

{latest_user_message.content}
"""

    print(
        "FAST WORKSPACE UPDATE INPUT: "
        f"{len(generation_input)} characters"
    )

    started_at = time.monotonic()

    response = client.responses.parse(
        model="gpt-5-mini",
        reasoning={
            "effort": "minimal",
        },
        instructions=FAST_WORKSPACE_UPDATE_PROMPT,
        input=generation_input,
        text_format=WorkspaceUpdatePlan,
    )

    elapsed = (
        time.monotonic()
        - started_at
    )

    print(
        "FAST WORKSPACE UPDATE TIME: "
        f"{elapsed:.2f} seconds"
    )

    result = response.output_parsed

    if result is None:
        raise ValueError(
            "Workspace update returned no parsed output."
        )

    result.affected_sections = (
        normalize_affected_sections(
            result.affected_sections
        )
    )

    allowed_text_sections = {
        "overview",
        "requirements",
        "roadmap",
        "resources",
        "budget",
        "learning",
        "documentation",
        "testing",
    }

    requested_text_sections = {
        section_type
        for section_type in result.affected_sections
        if section_type in allowed_text_sections
    }

    returned_sections = {}

    for section in result.sections:
        section_type = (
            section.folder_type
            .strip()
            .lower()
        )

        content = section.content.strip()

        if section_type not in requested_text_sections:
            continue

        if not content:
            continue

        returned_sections[
            section_type
        ] = content

    missing_sections = (
        requested_text_sections
        - set(returned_sections.keys())
    )

    if missing_sections:
        raise ValueError(
            "AI omitted affected workspace sections: "
            + ", ".join(
                sorted(missing_sections)
            )
        )

    result.sections = [
        section
        for section in result.sections
        if (
            section.folder_type.strip().lower()
            in requested_text_sections
            and section.content.strip()
        )
    ]

    print(
        "FAST AFFECTED SECTIONS:",
        result.affected_sections,
    )

    return result
def review_project(project) -> ProjectHealthReview:
    project_state = getattr(project, "state", None)

    facts = (
        project_state.facts
        if project_state is not None
        else {}
    )

    sections_text = "\n\n".join(
        (
            f"SECTION TYPE: {folder.folder_type}\n"
            f"SECTION NAME: {folder.name}\n"
            f"CONTENT:\n{folder.description}"
        )
        for folder in project.folders.order_by("order")
    )

    tasks_text = "\n\n".join(
        (
            f"TASK ID: {task.pk}\n"
            f"TITLE: {task.title}\n"
            f"DESCRIPTION: {task.description}\n"
            f"PRIORITY: {task.get_priority_display()}\n"
            f"COMPLETED: {task.completed}\n"
            f"ORDER: {task.order}"
        )
        for task in project.tasks.order_by("order")
    )

    discovery_text = "\n\n".join(
        f"{message.role.upper()}: {message.content}"
        for message in project.messages.order_by("created_at")
    )

    review_input = f"""
PROJECT NAME:

{project.name}


ORIGINAL PROJECT DISCOVERY:

{discovery_text}


CANONICAL PROJECT FACTS:

{facts}


CURRENT WORKSPACE:

{sections_text}


CURRENT TASKS:

{tasks_text}
"""

    response = client.responses.parse(
        model="gpt-5-mini",
        reasoning={
            "effort": "minimal",
        },
        instructions=PROJECT_HEALTH_PROMPT,
        input=review_input,
        text_format=ProjectHealthReview,
    )

    return response.output_parsed

class ScheduledMilestone(BaseModel):
    name: str
    description: str
    target_date: date | None
    order: int


class ScheduledTask(BaseModel):
    task_id: int
    start_date: date | None
    due_date: date | None
    estimated_hours: float | None
    milestone_name: str | None
    dependency_ids: list[int]


class ProjectSchedule(BaseModel):
    summary: str
    milestones: list[ScheduledMilestone]
    tasks: list[ScheduledTask]
PROJECT_SCHEDULING_PROMPT = """
You are BuilderOS, an AI project scheduling assistant.

Create a realistic execution schedule for the existing project.

You will receive:

- today's date
- canonical project facts
- current workspace sections
- current milestones
- current tasks
- task priorities
- task statuses
- task estimates
- current dates
- current dependencies

Return:

- a concise schedule summary
- a milestone plan
- scheduling data for every existing task

Milestone rules:

- Create a small number of meaningful project checkpoints.
- Reuse an existing milestone name when it still makes sense.
- Do not create duplicate or nearly duplicate milestones.
- Milestones should represent outcomes, not individual tiny tasks.
- Assign a realistic target date.
- Order milestones from earliest to latest.

Task rules:

- Every returned task_id must match an existing task.
- Return exactly one scheduling entry for every existing task.
- Do not invent task IDs.
- Do not remove or rename tasks.
- Preserve completed work.
- Completed tasks may keep their existing dates.
- Do not schedule unfinished work before its unfinished dependencies.
- dependency_ids must contain only valid task IDs from this project.
- A task must never depend on itself.
- Avoid circular dependencies.
- Use the smallest reasonable number of dependencies.
- Prefer direct dependencies rather than listing every indirect dependency.
- start_date must not be after due_date.
- estimated_hours must be realistic for one clear task.
- If there is not enough information for a confident estimate, make a
  clearly reasonable estimate rather than leaving everything empty.
- milestone_name must either match one returned milestone name or be null.

Status meanings:

- todo: work has not started
- in_progress: work is actively underway
- review: implementation is finished but needs validation or approval
- done: fully completed

Scheduling guidance:

- Schedule high-priority and prerequisite work earlier.
- Keep work in a logical technical sequence.
- Respect the project timeline and constraints in the workspace.
- Use today's date as the earliest normal start date for unfinished work.
- Do not move completed tasks back into the future.
- Allow reasonable overlap only where tasks can truly happen in parallel.

Return only the structured response required by ProjectSchedule.
"""
def generate_project_schedule(project) -> ProjectSchedule:
    project_state = getattr(
        project,
        "state",
        None,
    )

    canonical_facts = (
        project_state.facts
        if project_state is not None
        else {}
    )

    workspace_text = "\n\n".join(
        (
            f"SECTION TYPE: {folder.folder_type}\n"
            f"SECTION NAME: {folder.name}\n"
            f"{folder.description}"
        )
        for folder in project.folders.order_by(
            "order"
        )
    )

    milestones_text = "\n\n".join(
        (
            f"MILESTONE ID: {milestone.pk}\n"
            f"NAME: {milestone.name}\n"
            f"DESCRIPTION: {milestone.description}\n"
            f"TARGET DATE: "
            f"{milestone.target_date or 'Not scheduled'}\n"
            f"COMPLETED: {milestone.completed}\n"
            f"ORDER: {milestone.order}"
        )
        for milestone in project.milestones.order_by(
            "order",
            "target_date",
            "created_at",
        )
    )

    if not milestones_text:
        milestones_text = (
            "No milestones currently exist."
        )

    tasks_text = "\n\n".join(
        (
            f"TASK ID: {task.pk}\n"
            f"TITLE: {task.title}\n"
            f"DESCRIPTION: {task.description}\n"
            f"PRIORITY: {task.get_priority_display()}\n"
            f"STATUS: {task.status}\n"
            f"COMPLETED: {task.completed}\n"
            f"START DATE: "
            f"{task.start_date or 'Not scheduled'}\n"
            f"DUE DATE: "
            f"{task.due_date or 'Not scheduled'}\n"
            f"ESTIMATED HOURS: "
            f"{task.estimated_hours or 'Not estimated'}\n"
            f"MILESTONE: "
            f"{task.milestone.name if task.milestone else 'None'}\n"
            f"DEPENDENCY IDS: "
            f"{list(task.dependencies.values_list('pk', flat=True))}"
        )
        for task in project.tasks
        .select_related("milestone")
        .prefetch_related("dependencies")
        .order_by("order")
    )

    if not tasks_text:
        raise ValueError(
            "Cannot generate a project schedule "
            "because the project has no tasks."
        )

    scheduling_input = f"""
TODAY:

{date.today().isoformat()}


PROJECT NAME:

{project.name}


CANONICAL PROJECT FACTS:

{canonical_facts}


CURRENT WORKSPACE:

{workspace_text}


CURRENT MILESTONES:

{milestones_text}


CURRENT TASKS:

{tasks_text}
"""

    response = client.responses.parse(
        model="gpt-5-mini",
        reasoning={
            "effort": "minimal",
        },
        instructions=PROJECT_SCHEDULING_PROMPT,
        input=scheduling_input,
        text_format=ProjectSchedule,
    )

    schedule = response.output_parsed

    if schedule is None:
        raise ValueError(
            "The AI returned no project schedule."
        )

    return schedule


def build_workspace_generation_input(project):
    return [
        {
            "role": message.role,
            "content": message.content,
        }
        for message in project.messages.order_by(
            "created_at"
        )
    ]

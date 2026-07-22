from pydantic import BaseModel
from openai import OpenAI
from typing import Literal

client = OpenAI()


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
Create a detailed checklist ordered by what should be done first.
Mention dependencies where useful.

resources:
Recommend initial hardware parts, materials, software, libraries,
frameworks, APIs, services, and tools. Only include categories relevant
to the project. Clearly label recommendations requiring verification.

budget:
Provide an editable preliminary budget. Separate one-time, recurring,
optional, and contingency costs. Clearly label estimates.

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

Also generate a structured task list.

For every task return:

- title: a short, actionable task title
- description: practical details explaining the task
- priority: exactly 1, 2, or 3

Priority meanings:

1 = Low
2 = Medium
3 = High

Generate approximately 8 to 15 useful tasks.

Tasks must:

- be specific to this project
- be ordered from earliest to latest
- begin with an action verb
- be achievable as individual pieces of work
- avoid combining several major activities into one task
- reflect the roadmap and project requirements
"""
class WorkspaceSection(BaseModel):
    folder_type: str
    content: str
class GeneratedTask(BaseModel):
    title: str
    description: str
    priority: int

class GeneratedWorkspace(BaseModel):
    project_name: str
    sections: list[WorkspaceSection]
    tasks: list[GeneratedTask]
def generate_workspace_content(project) -> GeneratedWorkspace:
    conversation = []

    for message in project.messages.order_by("created_at"):
        conversation.append(
            {
                "role": message.role,
                "content": message.content,
            }
        )

    response = client.responses.parse(
        model="gpt-5-mini",
        instructions=WORKSPACE_PROMPT,
        input=conversation,
        text_format=GeneratedWorkspace,
    )

    return response.output_parsed

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
"""
def generate_additional_tasks(project) -> AdditionalTasks:
    conversation_text = "\n\n".join(
        f"{message.role.upper()}: {message.content}"
        for message in project.messages.order_by("created_at")
    )

    workspace_text = "\n\n".join(
        (
            f"SECTION: {folder.name}\n"
            f"{folder.description}"
        )
        for folder in project.folders.order_by("order")
    )

    existing_tasks_text = "\n".join(
        (
            f"- {task.title} | "
            f"Priority: {task.get_priority_display()} | "
            f"Completed: {task.completed}"
        )
        for task in project.tasks.order_by("order")
    )

    generation_input = f"""
PROJECT DISCOVERY:

{conversation_text}

CURRENT WORKSPACE:

{workspace_text}

EXISTING TASKS:

{existing_tasks_text}
"""

    response = client.responses.parse(
        model="gpt-5-mini",
        instructions=MORE_TASKS_PROMPT,
        input=generation_input,
        text_format=AdditionalTasks,
    )

    return response.output_parsed
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
WORKSPACE_CHANGE_PROMPT = """
You are BuilderOS, a dependency-aware AI project manager.

Analyze the user's latest workspace-assistant message.

Your current job is ONLY to understand the requested project change.

Do not rewrite workspace sections yet.
Do not modify tasks yet.
Do not claim that changes have already been applied.

You will receive:

- the original project discovery conversation
- the current structured project facts
- the current workspace sections
- the current tasks
- the workspace assistant conversation
- the latest user message

Determine:

1. The underlying project-level change being requested.
2. Which canonical facts should change.
3. Which workspace sections are affected by that change.
4. A short response acknowledging what BuilderOS understood.

Canonical updates should represent the new source of truth.

Example:

User:
"Switch from Raspberry Pi 4 to Raspberry Pi 5."

Possible canonical updates:

- key: controller
- previous_value: Raspberry Pi 4
- new_value: Raspberry Pi 5
- reason: The user explicitly changed the primary controller.

Affected sections might include:

- requirements
- roadmap
- tasks
- resources
- budget
- documentation
- testing

Only include sections that are meaningfully affected.

The assistant_message should briefly explain the understood change and
list the sections that would need updating.

Do not say the workspace has already been updated.

Return only the structured response required by
WorkspaceChangeAnalysis.

Do not ask follow-up questions unless the user's request is impossible to
interpret.

If information is missing, make clearly labeled reasonable assumptions.

Your job is to understand the requested change, not continue the interview.

5. A concise impact explanation describing why the requested change affects
the selected workspace sections.

The impact_explanation should:

- be 1 to 3 sentences
- explain the most important technical or project consequences
- avoid repeating the list of section names
- avoid claiming the updates have already happened
- not ask follow-up questions
"""
def analyze_workspace_change(project) -> WorkspaceChangeAnalysis:
    project_state = getattr(project, "state", None)

    current_facts = (
        project_state.facts
        if project_state is not None
        else {}
    )

    discovery_text = "\n\n".join(
        f"{message.role.upper()}: {message.content}"
        for message in project.messages.order_by("created_at")
    )

    workspace_text = "\n\n".join(
        (
            f"SECTION TYPE: {folder.folder_type}\n"
            f"SECTION NAME: {folder.name}\n"
            f"{folder.description}"
        )
        for folder in project.folders.order_by("order")
    )

    tasks_text = "\n\n".join(
        (
            f"TITLE: {task.title}\n"
            f"DESCRIPTION: {task.description}\n"
            f"PRIORITY: {task.get_priority_display()}\n"
            f"COMPLETED: {task.completed}"
        )
        for task in project.tasks.order_by("order")
    )

    assistant_conversation = "\n\n".join(
        f"{message.role.upper()}: {message.content}"
        for message in project.workspace_messages.order_by(
            "created_at"
        )
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

    analysis_input = f"""
ORIGINAL PROJECT DISCOVERY:

{discovery_text}


CURRENT CANONICAL PROJECT FACTS:

{current_facts}


CURRENT WORKSPACE:

{workspace_text}


CURRENT TASKS:

{tasks_text}


WORKSPACE ASSISTANT CONVERSATION:

{assistant_conversation}


LATEST USER REQUEST:

{latest_user_message.content}
"""

    response = client.responses.parse(
        model="gpt-5-mini",
        instructions=WORKSPACE_CHANGE_PROMPT,
        input=analysis_input,
        text_format=WorkspaceChangeAnalysis,
    )

    return response.output_parsed

def apply_canonical_updates(
    current_facts: dict,
    analysis: WorkspaceChangeAnalysis,
) -> dict:
    updated_facts = current_facts.copy()

    for update in analysis.canonical_updates:
        updated_facts[update.key] = update.new_value

    return updated_facts
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

def regenerate_affected_workspace_sections(
    project,
    analysis: WorkspaceChangeAnalysis,
    updated_facts: dict,
) -> dict[str, str]:
    dependency_order = [
        "overview",
        "requirements",
        "resources",
        "budget",
        "roadmap",
        "learning",
        "testing",
        "documentation",
    ]

    affected_sections = set(analysis.affected_sections)

    folders = {
        folder.folder_type: folder
        for folder in project.folders.order_by("order")
    }

    # This dictionary acts as an in-memory version of the workspace.
    # Each newly generated section is placed here so later sections can
    # use the updated result.
    working_sections = {
        folder_type: folder.description
        for folder_type, folder in folders.items()
    }

    discovery_text = "\n\n".join(
        f"{message.role.upper()}: {message.content}"
        for message in project.messages.order_by("created_at")
    )

    assistant_conversation = "\n\n".join(
        f"{message.role.upper()}: {message.content}"
        for message in project.workspace_messages.order_by(
            "created_at"
        )
    )

    tasks_text = "\n\n".join(
        (
            f"TITLE: {task.title}\n"
            f"DESCRIPTION: {task.description}\n"
            f"PRIORITY: {task.get_priority_display()}\n"
            f"COMPLETED: {task.completed}"
        )
        for task in project.tasks.order_by("order")
    )

    regenerated_sections = {}

    for section_type in dependency_order:
        if section_type not in affected_sections:
            continue

        folder = folders.get(section_type)

        if folder is None:
            continue

        other_sections_text = "\n\n".join(
            (
                f"SECTION TYPE: {other_type}\n"
                f"{content}"
            )
            for other_type, content in working_sections.items()
            if other_type != section_type
        )

        generation_input = f"""
ORIGINAL PROJECT DISCOVERY:

{discovery_text}


WORKSPACE ASSISTANT CONVERSATION:

{assistant_conversation}


REQUESTED PROJECT CHANGE:

{analysis.summary}


UPDATED CANONICAL PROJECT FACTS:

{updated_facts}


CURRENT TASKS:

{tasks_text}


OTHER WORKSPACE SECTIONS:

{other_sections_text}


SECTION TO REWRITE:

SECTION TYPE: {section_type}
SECTION NAME: {folder.name}

CURRENT CONTENT:

{working_sections.get(section_type, "")}
"""

        response = client.responses.parse(
            model="gpt-5-mini",
            instructions=CASCADE_SECTION_PROMPT,
            input=generation_input,
            text_format=RegeneratedSection,
        )

        result = response.output_parsed

        # Later sections will now see this updated content.
        working_sections[section_type] = result.content
        regenerated_sections[section_type] = result.content

    return regenerated_sections

class TaskToUpdate(BaseModel):
    task_id: int
    new_title: str
    description: str
    priority: int


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

Return only the structured response required by TaskSynchronization.
"""

def generate_task_synchronization(
    project,
    analysis: WorkspaceChangeAnalysis,
    updated_facts: dict,
    regenerated_sections: dict[str, str],
) -> TaskSynchronization:
    existing_tasks_text = "\n\n".join(
        (
            f"TASK ID: {task.pk}\n"
f"TITLE: {task.title}\n"
            f"DESCRIPTION: {task.description}\n"
            f"PRIORITY: {task.get_priority_display()}\n"
            f"COMPLETED: {task.completed}"
        )
        for task in project.tasks.order_by("order")
    )

    updated_sections_text = "\n\n".join(
        (
            f"SECTION TYPE: {section_type}\n"
            f"{content}"
        )
        for section_type, content in regenerated_sections.items()
    )

    generation_input = f"""
REQUESTED PROJECT CHANGE:

{analysis.summary}


UPDATED CANONICAL PROJECT FACTS:

{updated_facts}


UPDATED WORKSPACE SECTIONS:

{updated_sections_text}


EXISTING TASKS:

{existing_tasks_text}
"""

    response = client.responses.parse(
        model="gpt-5-mini",
        instructions=TASK_SYNCHRONIZATION_PROMPT,
        input=generation_input,
        text_format=TaskSynchronization,
    )
    result = response.output_parsed

    return result

class UpdatedWorkspaceSection(BaseModel):
    folder_type: str
    content: str


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
def regenerate_affected_workspace_sections_combined(
    project,
    analysis: WorkspaceChangeAnalysis,
    updated_facts: dict,
) -> dict[str, str]:
    allowed_section_types = {
        "overview",
        "requirements",
        "roadmap",
        "resources",
        "budget",
        "learning",
        "documentation",
        "testing",
        "tasks",
    }

    affected_sections = [
        section_type
        for section_type in analysis.affected_sections
        if section_type in allowed_section_types
    ]

    if not affected_sections:
        return {}

    discovery_text = "\n\n".join(
        f"{message.role.upper()}: {message.content}"
        for message in project.messages.order_by("created_at")
    )

    assistant_conversation = "\n\n".join(
        f"{message.role.upper()}: {message.content}"
        for message in project.workspace_messages.order_by(
            "created_at"
        )
    )

    workspace_text = "\n\n".join(
        (
            f"SECTION TYPE: {folder.folder_type}\n"
            f"SECTION NAME: {folder.name}\n"
            f"CURRENT CONTENT:\n{folder.description}"
        )
        for folder in project.folders.order_by("order")
    )

    tasks_text = "\n\n".join(
    (
        f"TASK ID: {task.pk}\n"
        f"TITLE: {task.title}\n"
        f"DESCRIPTION: {task.description}\n"
        f"PRIORITY: {task.get_priority_display()}\n"
        f"COMPLETED: {task.completed}"
    )
    for task in project.tasks.order_by("order")
)

    sections_to_rewrite_text = "\n".join(
        f"- {section_type}"
        for section_type in affected_sections
    )

    generation_input = f"""
ORIGINAL PROJECT DISCOVERY:

{discovery_text}


WORKSPACE ASSISTANT CONVERSATION:

{assistant_conversation}


REQUESTED PROJECT CHANGE:

{analysis.summary}


UPDATED CANONICAL PROJECT FACTS:

{updated_facts}


CURRENT DATABASE-BACKED TASKS:

{tasks_text}


CURRENT WORKSPACE:

{workspace_text}


SECTIONS TO REWRITE:

{sections_to_rewrite_text}
"""

    response = client.responses.parse(
        model="gpt-5-mini",
        instructions=COMBINED_CASCADE_PROMPT,
        input=generation_input,
        text_format=RegeneratedWorkspaceSections,
    )

    result = response.output_parsed

    returned_sections = {}

    for section in result.sections:
        section_type = section.folder_type.strip().lower()

        if section_type not in affected_sections:
            continue

        content = section.content.strip()

        if not content:
            continue

        returned_sections[section_type] = content

    missing_sections = (
        set(affected_sections)
        - set(returned_sections.keys())
    )

    if missing_sections:
        raise ValueError(
            "AI omitted required workspace sections: "
            + ", ".join(sorted(missing_sections))
        )

    return returned_sections

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
        instructions=PROJECT_HEALTH_PROMPT,
        input=review_input,
        text_format=ProjectHealthReview,
    )

    return response.output_parsed


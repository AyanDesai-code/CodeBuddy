from unittest import result

from django.core.mail import message
from django.http import response
from pydantic import BaseModel, Field
from openai import OpenAI
from typing import Literal
from datetime import date
import time
import json

client = OpenAI()

class GeneratedLearningResource(BaseModel):
    title: str
    topic: str
    url: str
    description: str
    reason_needed: str
    related_task: str
    difficulty: str
    resource_type: str = "documentation"
    is_official: bool = False


class GeneratedDocumentationSection(BaseModel):
    title: str
    content: str

    related_topics: list[str] = Field(
        default_factory=list
    )

    reference_urls: list[str] = Field(
        default_factory=list
    )
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

TASK_GENERATION_RULES = """
TASK GENERATION REQUIREMENTS

Generate a detailed, execution-ready task plan.

TASK GRANULARITY

Every task must represent one clear piece of work that can usually be
completed in approximately 30 minutes to 4 hours of focused effort.

Do not combine multiple independent pieces of work into one task.

Never generate vague tasks such as:

- Build the backend
- Implement the frontend
- Create the prototype
- Test the system
- Research components
- Set up authentication
- Finish documentation
- Deploy the application

Decompose broad work until every task is directly executable.

Bad task:

Build authentication.

Good decomposition:

- Create the Django CustomUser model.
- Create the account registration form.
- Add password validation rules.
- Configure login and logout routes.
- Create authentication templates.
- Test login, logout, and registration using multiple accounts.

TASK WORDING

Every task title must:

- begin with an action verb
- describe one specific action
- be specific to the exact project
- avoid vague words such as build, handle, improve, finish, or work on
  unless followed by a precise deliverable

Every task description must explain:

- what must be done
- the important implementation details
- why the task matters when that is not obvious
- what output or deliverable should exist afterward

COMPLETION CRITERIA

Every task must include objective completion criteria.

Completion criteria must describe observable evidence that the task is
finished.

Examples:

- The Raspberry Pi boots successfully.
- SSH login works from another computer.
- The camera captures and saves an image.
- All unit tests pass.
- The API returns the expected response and status code.
- The component dimensions are recorded in the project documentation.
- The prototype completes ten test runs without failure.

Do not use completion criteria such as:

- The task is complete.
- Everything works.
- The implementation is finished.

ESTIMATED EFFORT

Every task must include an estimated number of hours.

Use realistic estimates based on the work described.

Most tasks should take approximately 0.5 to 4 hours.

Use larger estimates only when the task genuinely cannot be divided
further without becoming unnatural.

LIFECYCLE COVERAGE

The task list must cover every relevant part of the project lifecycle.

Consider all of the following:

- Planning
- Requirements
- Research
- Learning
- Setup
- Procurement
- Environment configuration
- Architecture
- Design
- Implementation
- Integration
- Testing
- Debugging
- Documentation
- Deployment or final delivery
- Maintenance
- Optimization
- Validation
- Risk mitigation
- User testing
- Final review
- Completion

Only omit a lifecycle area when it is genuinely irrelevant to the
project.

PARALLEL WORK

Create independent task branches whenever work can happen concurrently.

Do not make every task depend on the immediately previous task.

Identify tasks that different people could reasonably perform at the
same time.

Use only direct dependencies.

TASK COUNT

The number of tasks should reflect the project's complexity.

Typical ranges:

- Small projects: 20 to 35 tasks
- Medium projects: 35 to 60 tasks
- Large or technically complex projects: 60 to 100 tasks

Err on the side of generating more useful tasks rather than fewer.

Missing meaningful work is worse than including a few extra useful
tasks.

Do not artificially compress independent steps into one task.

Do not generate filler merely to reach a target count.

ORDERING

Order tasks from earliest to latest while preserving parallel branches.

Prerequisites should appear before tasks that depend on them.

Final validation, documentation, deployment, and review tasks should
appear near the end.

Every generated task must contribute meaningfully to completing the
project.
"""
WORKSPACE_PROMPT = f"""
You are Projivo's workspace generator.

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

{TASK_GENERATION_RULES}

TASK REQUIREMENTS
TASK REQUIREMENTS

Generate a comprehensive project plan.

The number of tasks should depend on project complexity.

Typical ranges:

- Small projects:
  20–35 tasks

- Medium projects:
  35–60 tasks

- Large or technically complex projects:
  60–100 tasks

Do not stop generating simply because you reached a round number.

Continue until every meaningful piece of work has been represented.
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

Each description should clearly explain:

- what must be done
- why it is needed
- important implementation details
- expected outcome

Target roughly 50–120 words.

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

Generate a complete and practical project workspace.

LEARNING RESOURCES

Generate a structured learning resource for every
important technology, component, tool, and concept
the user must understand to complete the project.

Cover relevant:

- programming languages
- frameworks
- libraries
- APIs
- development tools
- hardware components
- communication protocols
- electrical and mechanical concepts
- deployment platforms
- testing tools
- safety concepts

Each learning resource must include:

- title
- topic
- URL
- description of what the resource teaches
- why the user needs it for this project
- the related task or project phase
- difficulty level
- resource type
- whether the source is official

Valid resource_type values are:

- documentation
- tutorial
- video
- article
- course
- tool

Use official documentation whenever it exists.

Preferred source order:

1. Official product documentation
2. Official framework or library documentation
3. Manufacturer documentation or datasheets
4. Reputable educational resources
5. High-quality tutorials

Do not invent URLs.

Only return a URL when you are confident that it is
a real and relevant destination.

If a reliable URL is not known, return an empty string.

Avoid duplicate resources.

The Learning Resources output should teach the user
each individual technology or concept required by
their exact project.

DOCUMENTATION

Generate detailed, project-specific documentation.

This must explain how the user's exact project should
be understood, built, configured, tested, operated,
troubleshot, and maintained.

Create documentation sections covering relevant
parts of:

1. Project overview
2. Goals and scope
3. System architecture
4. Major components
5. How components interact
6. Software architecture
7. Repository and folder structure
8. Installation and environment setup
9. Dependencies
10. Hardware wiring and integration
11. Power architecture
12. Configuration
13. Environment variables
14. APIs and communication protocols
15. Database or data model
16. Main workflows
17. Commands used to run the project
18. Testing procedures
19. Calibration procedures
20. Troubleshooting
21. Deployment
22. Maintenance
23. Security considerations
24. Electrical, mechanical, and operational safety

Only include sections that are relevant to the
project, but explain all relevant sections fully.

The documentation must explain the project itself,
not merely provide links.

Explain important terms, components, commands,
decisions, and interactions as though the reader is
learning them for the first time.

Use relevant learning-resource URLs as references
where helpful.

Do not replace detailed explanations with links.
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
    title: str = Field(
        min_length=5,
        max_length=180,
    )

    description: str = Field(
        min_length=30,
    )

    priority: int = Field(
        ge=1,
        le=3,
    )

    status: TaskStatus = "todo"

    estimated_hours: float = Field(
        ge=0.25,
        le=40,
    )

    completion_criteria: list[str] = Field(
        min_length=1,
    )

    dependency_indexes: list[int] = Field(
        default_factory=list,
    )
import time

from pydantic import BaseModel


class GeneratedWorkspace(BaseModel):
    project_name: str
    sections: list[GeneratedSection]
    tasks: list[GeneratedTask]

    learning_resources: list[
        GeneratedLearningResource
    ] = Field(
        default_factory=list
    )

    documentation_sections: list[
        GeneratedDocumentationSection
    ] = Field(
        default_factory=list
    )
def generate_workspace_content(
    project,
) -> GeneratedWorkspace:
    conversation = (
        build_workspace_generation_input(
            project
        )
    )

    started_at = time.monotonic()

    try:
        print(
            "Calling OpenAI for workspace..."
        )

        response = client.responses.parse(
            model="gpt-5-mini",
            reasoning={
                "effort": "medium",
            },
            instructions=WORKSPACE_PROMPT,
            input=conversation,
            text_format=GeneratedWorkspace,
        )

        generated_workspace = (
            response.output_parsed
        )

        if generated_workspace is None:
            print(
                "Workspace raw output:",
                response.output,
            )

            raise ValueError(
                "Workspace generation returned "
                "no parsed output."
            )

        elapsed = (
            time.monotonic()
            - started_at
        )

        print(
            "Workspace parsed successfully."
        )

        print(
            "WORKSPACE GENERATION TIME: "
            f"{elapsed:.2f} seconds"
        )

        return generated_workspace

    except Exception:
        elapsed = (
            time.monotonic()
            - started_at
        )

        print(
            "WORKSPACE GENERATION FAILED "
            f"AFTER: {elapsed:.2f} seconds"
        )

        raise
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
Critical budgeting rules:

1. Respect the user's stated target budget.
2. The required baseline items should fit within the target whenever
   technically reasonable.
3. Do not include the user's own labor in the purchase-cost total.
4. Labor may only be included as an optional item and must be clearly
   described as notional labor value.
5. Mark physical components and initial consumables as one-time costs.
6. Only mark genuine subscriptions or ongoing services as recurring.
7. For recurring items, quantity must normally be 1 and unit_cost must
   represent the monthly price.
8. Do not use quantity to represent the number of subscription months.
9. Optional upgrades must not be necessary for the baseline build.
10. Avoid duplicate or overlapping components.
11. Prefer practical low-cost components appropriate for a prototype.
12. Source URLs must be real URLs or blank. Never invent URLs.
For every budget item include:

- source_name
- source_url

Requirements:

- source_url must be a complete HTTPS URL.
- Prefer official manufacturer pages.
- If unavailable, use a reputable distributor such as:
  - DigiKey
  - Mouser
  - SparkFun
  - Adafruit
  - Pololu
  - McMaster-Carr
  - Raspberry Pi
  - Arduino
  - JLCPCB
  - PCBWay

Do not write generic text like
"Amazon", "electronics suppliers", or "robotics stores".

Provide a real URL whenever possible.
If no reliable URL exists, return an empty string.
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
):
    tasks = (
        project.tasks
        .select_related(
            "assignee",
            "assignee__user",
            "assignee__project_role",
            "milestone",
        )
        .prefetch_related(
            "dependencies",
        )
        .order_by(
            "order",
            "pk",
        )
    )

    task_blocks = []

    for task in tasks:
        assignee_name = "Unassigned"
        membership_id = "None"
        team_role = "None"

        if task.assignee:
            membership_id = task.assignee.pk

            assignee_name = (
                task.assignee.user.username
            )

            if task.assignee.project_role:
                team_role = (
                    task.assignee
                    .project_role
                    .name
                )

        task_blocks.append(
            "\n".join(
                [
                    f"TASK ID: {task.pk}",
                    f"TITLE: {task.title}",
                    (
                        "DESCRIPTION: "
                        f"{task.description}"
                    ),
                    f"STATUS: {task.status}",
                    f"PRIORITY: {task.priority}",
                    (
                        "ESTIMATED HOURS: "
                        f"{task.estimated_hours}"
                    ),
                    (
                        "ASSIGNEE MEMBERSHIP ID: "
                        f"{membership_id}"
                    ),
                    (
                        "ASSIGNEE USERNAME: "
                        f"{assignee_name}"
                    ),
                    (
                        "ASSIGNEE TEAM ROLE: "
                        f"{team_role}"
                    ),
                    (
                        "DEPENDENCY IDS: "
                        f"{list(
                            task.dependencies
                            .values_list(
                                'pk',
                                flat=True,
                            )
                        )}"
                    ),
                ]
            )
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
WORKSPACE_ASSISTANT_INTENT_PROMPT = """
You classify messages sent to a project-management assistant.

Return intent="question" when the user wants to:

- retrieve existing information
- ask what tasks exist
- ask who owns a task
- ask what a person's role is
- ask about budget, requirements, roadmap, resources, testing, or status
- ask for an explanation or summary
- ask for recommendations without requesting that they be applied
- identify blockers, risks, missing information, or workload

Return intent="update" when the user explicitly asks to:

- add, remove, or rewrite project content
- change requirements, budget, scope, timeline, or resources
- add, update, remove, assign, or reassign tasks
- modify a member's responsibilities
- regenerate or improve a workspace section
- apply a recommendation
- change the stored project

Examples:

"What tasks are assigned to Kunal?"
question

"What is Kunal's role?"
question

"Who should own the backend tasks?"
question

"Assign the backend tasks to Kunal."
update

"Explain the testing plan."
question

"Improve the testing plan."
update

"What would happen if we used an ESP32?"
question

"Replace the Raspberry Pi with an ESP32."
update

Return only the structured WorkspaceAssistantIntent response.
"""
WORKSPACE_QUESTION_PROMPT = """
You are Projivo's read-only project assistant.

Answer the user's question using only the supplied project data.

The project data may contain:

- project discovery information
- canonical project facts
- workspace sections
- tasks
- task assignments
- task dependencies
- team members
- permission levels
- named team roles
- role responsibilities
- role skills
- member-specific notes
- active workloads

Important distinctions:

- permission_level controls application access
- team_role describes project responsibility
- Editor and Viewer are not professional team roles

Answer rules:

- Answer the user's actual question directly.
- Do not claim to modify the workspace.
- Do not produce update statistics.
- Do not say that no changes were necessary.
- Do not mention affected workspace sections.
- Do not invent tasks, members, roles, IDs, facts, or assignments.
- Match usernames case-insensitively.
- Treat task assignee fields as authoritative.
- Treat PROJECT TEAM membership IDs as authoritative.
- Clearly say when no matching information exists.
- Keep answers organized and readable.
- Use bullets when listing tasks or project information.
- Include task status, priority, due date, and blocked state when available.
- Distinguish factual answers from recommendations.
- Do not apply recommendations unless the user explicitly requests an update.

When asked who should own a task:

- consider named team roles
- consider responsibilities
- consider skills
- consider member notes
- consider current workload
- explain the recommendation briefly

Return only the structured WorkspaceQuestionAnswer response.
"""
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

TEAM AND ASSIGNMENT AWARENESS

The supplied project team and task records are authoritative.

Each task may contain:

- assignee membership ID
- assignee username
- assignee project role
- assignee permission level

When the user asks about a person's tasks:

- match the username case-insensitively
- use the task assignee fields
- do not claim that assignment data is unavailable when it is supplied
- distinguish assigned tasks from tasks that merely mention the person's name
- do not modify the workspace unless the user explicitly asks for a change
- answer informational questions directly

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
        project
    )

    assistant_text = build_recent_workspace_messages(
        project,
        limit=6,
    )
    team_context = (
        build_project_team_context(
            project
        )
    )

    generation_input = f"""
PROJECT DISCOVERY SUMMARY:

{discovery_text}


CURRENT CANONICAL FACTS:

{current_facts}


PROJECT TEAM:

{json.dumps(
    team_context,
    indent=2,
    default=str,
)}


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
        instructions=(
            FAST_WORKSPACE_UPDATE_PROMPT
            + "\n\n"
            + TEAM_COLLABORATION_RULES
        ),
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
TEAM_COLLABORATION_RULES = """
TEAM AND ROLE RULES

The supplied PROJECT TEAM data is authoritative.

Each collaborator may have:

- membership_id
- username
- permission_level
- team_role
- role_description
- role_responsibilities
- role_skills
- member_notes
- active_tasks
- active_task_count

Permission level and team role are different:

- permission_level controls access to the application
- team_role describes the person's project responsibility

Do not treat Editor or Viewer as a professional team role.

When reasoning about the team:

- use the named team_role, responsibilities, skills, and member notes
- use only membership IDs supplied in PROJECT TEAM
- never invent members or membership IDs
- match usernames case-insensitively
- consider current workload before recommending assignments
- preserve existing task assignments unless a reassignment is justified
- leave a task unassigned when nobody is a reasonable fit
- identify missing skills or roles when appropriate
- never assume that an owner must perform every task
- permission level does not determine technical suitability

When assigning work:

- assign software work to members with relevant software roles or skills
- assign mechanical work to members with relevant mechanical roles or skills
- assign design work to members with relevant design roles or skills
- consider responsibilities and member-specific notes
- avoid concentrating all tasks on one person
- explain important assignment or reassignment decisions
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


class TeamMemberAnalysis(BaseModel):
    membership_id: int
    username: str
    active_task_count: int
    estimated_active_hours: float
    overload_risk: str
    blocked_task_count: int
    recommendations: list[str]


class CollaborationAnalysis(BaseModel):
    workload_balance_score: int
    missing_roles: list[str]
    missing_skills: list[str]
    bottlenecks: list[str]
    overloaded_members: list[int]
    underutilized_members: list[int]
    reassignment_recommendations: list[str]
    sprint_plan_summary: str
def build_project_team_context(
    project,
):
    memberships = (
        project.memberships
        .select_related(
            "user",
            "project_role",
        )
        .prefetch_related(
            "assigned_tasks",
        )
        .order_by(
            "created_at",
        )
    )

    team = []

    for membership in memberships:
        active_tasks = list(
            membership.assigned_tasks
            .exclude(
                status="done",
            )
            .values(
                "id",
                "title",
                "status",
                "priority",
                "estimated_hours",
                "start_date",
                "due_date",
            )
        )

        project_role = (
            membership.project_role
        )

        team.append(
            {
                "membership_id": (
                    membership.pk
                ),
                "username": (
                    membership.user.username
                ),

                # Access control
                "permission_level": (
                    membership.role
                ),

                # Actual project responsibility
                "team_role": (
                    project_role.name
                    if project_role
                    else "Unassigned role"
                ),
                "role_description": (
                    project_role.description
                    if project_role
                    else ""
                ),
                "role_responsibilities": (
                    project_role.responsibilities
                    if project_role
                    else ""
                ),
                "role_skills": (
                    project_role.skills
                    if project_role
                    else ""
                ),

                # Person-specific instructions
                "member_notes": (
                    membership.role_notes
                    or ""
                ),

                "active_tasks": active_tasks,
                "active_task_count": (
                    len(active_tasks)
                ),
            }
        )

    return team
class WorkspaceAssistantIntent(BaseModel):
    intent: Literal[
        "question",
        "update",
    ]

    reason: str = ""


class WorkspaceQuestionAnswer(BaseModel):
    answer: str


def classify_workspace_assistant_intent(
    message: str,
) -> WorkspaceAssistantIntent:
    response = client.responses.parse(
        model="gpt-5-mini",
        reasoning={
            "effort": "minimal",
        },
        instructions=(
            WORKSPACE_ASSISTANT_INTENT_PROMPT
        ),
        input=message,
        text_format=WorkspaceAssistantIntent,
    )

    result = response.output_parsed

    if result is None:
        raise ValueError(
            "Workspace assistant intent "
            "classification returned no result."
        )

    return result
def answer_workspace_question(
    *,
    project,
    question: str,
) -> WorkspaceQuestionAnswer:
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

    discovery_text = (
        build_compact_discovery_text(
            project
        )
    )

    workspace_text = (
        build_compact_workspace_text(
            project,
            content_limit=1800,
        )
    )

    tasks_text = (
        build_compact_tasks_text(
            project
        )
    )

    team_context = (
        build_project_team_context(
            project
        )
    )

    question_input = f"""
PROJECT NAME:

{project.name}


PROJECT DISCOVERY:

{discovery_text}


CANONICAL PROJECT FACTS:

{json.dumps(
    canonical_facts,
    indent=2,
    default=str,
)}


PROJECT TEAM:

{json.dumps(
    team_context,
    indent=2,
    default=str,
)}


CURRENT WORKSPACE:

{workspace_text}


CURRENT DATABASE-BACKED TASKS:

{tasks_text}


USER QUESTION:

{question}
"""

    response = client.responses.parse(
        model="gpt-5-mini",
        reasoning={
            "effort": "minimal",
        },
        instructions=(
            WORKSPACE_QUESTION_PROMPT
            + "\n\n"
            + TEAM_COLLABORATION_RULES
        ),
        input=question_input,
        text_format=WorkspaceQuestionAnswer,
    )

    result = response.output_parsed

    if result is None:
        raise ValueError(
            "Workspace assistant returned "
            "no answer."
        )

    result.answer = result.answer.strip()

    if not result.answer:
        raise ValueError(
            "Workspace assistant returned "
            "an empty answer."
        )

    return result
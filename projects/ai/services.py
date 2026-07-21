from pydantic import BaseModel
from openai import OpenAI


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
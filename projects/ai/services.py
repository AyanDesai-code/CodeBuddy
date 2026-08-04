from pydantic import BaseModel, Field
from openai import OpenAI
from typing import Literal
from datetime import date
import time

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

Using the complete project discovery conversation, generate a complete,
detailed, practical, and editable initial workspace for the project.

The workspace must help a beginner move from the initial idea through
planning, implementation, testing, deployment, and final completion.

RETURN

Return:

- a clear project name
- exactly one section for every required folder type
- a structured task list
- structured learning resources

REQUIRED FOLDER TYPES

Return exactly one section for each of these folder types:

- overview
- requirements
- roadmap
- tasks
- resources
- budget
- learning
- documentation
- testing

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

Do not omit a section.
Do not invent extra folder types.
Do not return duplicate folder types.

GENERAL WORKSPACE FORMATTING

Generate detailed and well-organized Markdown.

Use:

- clear headings
- subheadings
- bullet lists
- numbered procedures
- checklists
- tables when useful
- warnings and notes when relevant
- fenced code blocks for commands or code examples

Avoid walls of text.

Do not return primitive one-paragraph summaries.

Each section must contain enough detail for a beginner to understand the
subject without needing to ask basic follow-up questions.

Use project-specific details rather than generic advice.

Do not repeat the same content across several sections unless the same
information serves a clearly different purpose.

Clearly label:

- assumptions
- estimates
- facts requiring verification
- uncertain compatibility
- safety concerns
- optional recommendations
- future upgrades

Do not claim uncertain prices, compatibility, or technical facts as
guaranteed.

WORKSPACE DETAIL GUIDELINES

Recommended detail ranges:

- overview: 250 to 450 words
- requirements: 500 to 900 words
- roadmap: 600 to 1,000 words
- tasks section summary: 250 to 450 words
- resources: 600 to 1,000 words
- budget: 400 to 700 words
- learning: 700 to 1,200 words
- documentation: 1,000 to 2,000 words
- testing: 700 to 1,200 words

These are guidelines, not strict limits.

Use more detail when project complexity requires it.

Missing important information is worse than including additional useful
detail.

SECTION REQUIREMENTS

OVERVIEW

Create a structured project overview using this organization when
relevant:

## Project Summary

Explain exactly what is being built.

## Intended Users

Describe who will use it and what needs the project solves.

## Main Goal

State the primary outcome the project must achieve.

## Core Features

List the most important capabilities as bullet points.

## Constraints

Cover relevant:

- budget
- timeline
- hardware
- software
- skill level
- compatibility
- deployment
- physical size
- power
- safety
- legal or operational constraints

## Assumptions

Clearly label assumptions requiring verification.

## Success Definition

Explain what a completed and successful project looks like.

Do not return only one broad paragraph.

REQUIREMENTS

Create a detailed requirements specification.

Use this organization where relevant:

## Functional Requirements

Use identifiers such as:

- FR-1
- FR-2
- FR-3

For every functional requirement explain:

- required behavior
- affected user or system
- expected input
- expected output
- relevant edge cases
- acceptance criteria

## Non-Functional Requirements

Cover relevant:

- performance
- reliability
- usability
- maintainability
- security
- safety
- accessibility
- scalability
- compatibility
- power consumption
- environmental tolerance

## Constraints

List fixed limitations and project boundaries.

## Dependencies

List external systems, services, libraries, components, hardware, tools,
suppliers, and people the project depends on.

## Success Criteria

Create measurable completion criteria.

## Out of Scope

State what the current version will not include.

Avoid vague requirements such as:

- The system should work well.
- The interface should be good.
- The device should be reliable.

ROADMAP

Create a detailed phased roadmap from the current state through final
completion.

Use phases appropriate to the exact project, such as:

## Phase 1 — Research and Planning

## Phase 2 — Setup and Procurement

## Phase 3 — Architecture and Design

## Phase 4 — Initial Implementation

## Phase 5 — Integration

## Phase 6 — Testing and Debugging

## Phase 7 — Deployment or Final Assembly

## Phase 8 — Validation and Completion

For every phase include:

- objective
- major activities
- required inputs
- expected outputs
- dependencies
- work that can happen in parallel
- completion checkpoint
- likely risks
- evidence that the phase is finished

Do not force irrelevant phases into the project.

TASKS SECTION

Summarize the major categories of work represented by the structured
task list.

Organize this section into relevant groups such as:

- Planning
- Research
- Setup
- Procurement
- Design
- Implementation
- Integration
- Testing
- Documentation
- Deployment
- Final validation

Explain how the work is ordered and which branches can occur in
parallel.

Do not duplicate the complete structured task list in this section.

RESOURCES

Create a project-specific resource and technology plan.

Use relevant categories such as:

## Hardware

## Mechanical Components

## Electrical Components

## Materials

## Software

## Frameworks and Libraries

## APIs and Services

## Development Tools

## Testing Tools

## Deployment Tools

## Documentation and Datasheets

## Optional Upgrades

For every recommended item explain:

- what it is
- why the project needs it
- where it is used
- whether it is required, recommended, or optional
- important compatibility considerations
- reasonable alternatives
- facts requiring verification

Do not return only a list of names.

Do not invent specific compatibility claims.

BUDGET

Create a detailed preliminary budget explanation.

Use this organization where relevant:

## Budget Assumptions

Explain what the estimate assumes.

## Required One-Time Costs

Group major required purchases.

## Recurring Costs

Include relevant:

- hosting
- APIs
- subscriptions
- maintenance
- consumables
- replacement parts
- cloud storage
- domain or deployment costs

## Optional Costs

List upgrades and convenience purchases separately.

## Contingency

Recommend an appropriate contingency percentage and explain why.

## Cost Risks

Identify prices, quantities, suppliers, usage levels, or exchange rates
that may change.

## Cost-Saving Options

Suggest reasonable alternatives without undermining the core
requirements.

## Items Requiring Verification

Clearly list uncertain prices, quantities, suppliers, and compatibility
questions.

Do not attempt to replace the structured budget records returned
elsewhere.

LEARNING

Create a detailed project-specific learning plan.

Organize the section into learning tracks.

For every important topic include:

- topic name
- why the user needs it
- what must be understood
- prerequisite knowledge
- related project phase
- related tasks
- recommended learning order
- common beginner mistakes
- practical exercise
- completion checkpoint

Cover relevant:

- programming languages
- frameworks
- libraries
- APIs
- development tools
- hardware components
- communication protocols
- electrical concepts
- mechanical concepts
- deployment platforms
- testing tools
- security concepts
- safety concepts

Do not merely list links.

Explain how every learning topic applies to the project.

DOCUMENTATION

Generate detailed, project-specific documentation.

The documentation must explain how the exact project should be
understood, built, configured, tested, operated, troubleshot, deployed,
and maintained.

Use all relevant sections from the following:

## 1. Project Overview

Explain the purpose, intended users, goals, constraints, and scope.

## 2. Goals and Scope

Clarify included features, excluded features, and completion boundaries.

## 3. System Architecture

Explain the complete system at a high level.

## 4. Major Components

Describe every important hardware, software, electrical, mechanical, or
service component.

## 5. Component Interactions

Explain how data, commands, power, signals, materials, and user actions
move through the system.

## 6. Software Architecture

Explain major modules, services, processes, responsibilities, and
control flow.

## 7. Repository and Folder Structure

Describe important directories and files.

## 8. Installation and Environment Setup

Provide ordered setup steps.

## 9. Dependencies

Explain required:

- packages
- versions
- services
- tools
- hardware
- drivers
- libraries

## 10. Hardware Wiring and Integration

Explain relevant:

- connections
- pins
- buses
- interfaces
- voltages
- drivers
- protection components
- physical mounting
- grounding

## 11. Power Architecture

Explain relevant:

- power sources
- voltage rails
- current requirements
- regulation
- grounding
- battery selection
- charging
- power safety

## 12. Configuration

Explain configuration files, settings, calibration values, credentials,
and runtime options.

## 13. Environment Variables

Explain every relevant environment variable, its purpose, expected
format, and whether it contains sensitive data.

## 14. APIs and Communication Protocols

Explain relevant:

- endpoints
- protocols
- messages
- payloads
- responses
- errors
- authentication
- timing
- retries
- connection loss handling

## 15. Database or Data Model

Explain important models, fields, relationships, constraints, and stored
information.

## 16. Main Workflows

Explain the major user and system workflows step by step.

## 17. Commands

Provide commands needed to install, configure, run, test, build, and
deploy the project.

## 18. Testing Procedures

Explain how to test each subsystem and the integrated system.

## 19. Calibration Procedures

Explain relevant sensor, actuator, control, timing, dimensional, or
mechanical calibration.

## 20. Troubleshooting

Use a structured format containing:

- symptom
- likely cause
- diagnostic procedure
- corrective action
- prevention

## 21. Deployment or Final Assembly

Explain how the completed project is put into operation.

## 22. Maintenance

Explain recurring:

- inspections
- updates
- backups
- cleaning
- calibration
- replacement schedules
- dependency updates

## 23. Security Considerations

Explain relevant:

- authentication
- authorization
- secret management
- input validation
- network security
- data protection
- software updates
- logging
- access control

## 24. Safety

Explain relevant:

- electrical safety
- battery safety
- mechanical safety
- thermal safety
- tool safety
- operational safety
- environmental safety
- emergency shutdown procedures

Only include sections relevant to the project, but fully explain every
relevant section.

The documentation must explain the project itself.

Do not replace detailed explanations with links.

TESTING

Create a detailed staged testing and validation plan.

Use this organization where relevant:

## Testing Strategy

Explain the overall testing approach and order.

## Unit or Component Testing

Test individual software modules, hardware components, mechanisms,
services, and interfaces.

## Integration Testing

Test interactions between connected components.

## System Testing

Test the complete system under realistic conditions.

## Failure and Edge-Case Testing

Cover relevant:

- invalid inputs
- empty data
- communication loss
- power interruption
- component failure
- sensor failure
- overload
- timing problems
- network failure
- unexpected user behavior
- unsafe conditions

## Performance Testing

Include relevant:

- response time
- accuracy
- throughput
- battery life
- memory usage
- CPU usage
- mechanical performance
- reliability
- repeatability

## User Testing

Explain:

- who should test
- which scenarios they should perform
- what feedback should be recorded
- how findings should be prioritized

## Safety Testing

Include relevant electrical, mechanical, thermal, operational, battery,
and environmental checks.

## Regression Testing

Explain what must be retested after changes.

## Final Acceptance Checklist

Create measurable pass/fail criteria for project completion.

For every test include:

- test name
- purpose
- prerequisites
- exact procedure
- expected result
- success criteria
- failure response
- evidence to record

{TASK_GENERATION_RULES}

STRUCTURED TASK REQUIREMENTS

Generate a comprehensive project task plan.

The number of tasks should depend on project complexity.

Typical ranges:

- Small projects: 20 to 35 tasks
- Medium projects: 35 to 60 tasks
- Large or technically complex projects: 60 to 100 tasks

Do not stop simply because a round number has been reached.

Continue until every meaningful piece of work is represented.

For every task return:

- title
- description
- priority
- status
- dependency_indexes

If supported by the output schema, also return:

- completion_criteria
- estimated_hours

Task titles must:

- be specific to this project
- begin with an action verb
- represent one clear piece of work
- be ordered from earliest to latest

Each task description must explain:

- what must be done
- why it is needed
- important implementation details
- expected outcome
- observable completion evidence
- estimated effort

Target approximately 50 to 120 words per description unless a shorter
description is sufficient to make the task fully executable.

Priority must be exactly:

1 = Low
2 = Medium
3 = High

Status must be exactly one of:

todo
in_progress
review
done

New tasks should normally use:

todo

Only use another status when the project conversation clearly indicates
that the work is already underway, awaiting review, or completed.

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

Task 4: Implement the application shell
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
- Final integration, validation, or release tasks may depend on multiple
  implementation tasks.

LEARNING RESOURCE RECORDS

Generate a structured learning resource record for every important
technology, component, tool, and concept the user must understand.

Each learning resource must include:

- title
- topic
- URL
- description of what the resource teaches
- why the user needs it for this project
- related task or project phase
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

Only return a URL when confident that it is real and relevant.

If a reliable URL is not known, return an empty string.

Avoid duplicate resources.

The learning resources must collectively teach the important
technologies and concepts required by the exact project.
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



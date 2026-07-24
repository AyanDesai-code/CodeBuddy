# Codebuddy New User Guide

Codebuddy is a Django-based workspace generator and task manager. It helps you turn a rough project idea into a structured plan, AI-generated workspace content, and a task list you can manage over time.

This guide is written for new users who want to get started quickly.

## 1. Install and start the app

From the project folder, run:

```bash
cd /home/ayan/codebuddy
python -m venv venv
source venv/bin/activate
pip install django openai pydantic
```

Set your OpenAI API key:

```bash
export OPENAI_API_KEY="your_openai_api_key"
```

Run the database setup:

```bash
python manage.py migrate
```

Create an account for yourself:

```bash
python manage.py createsuperuser
```

Start the app:

```bash
python manage.py runserver
```

Open the app in your browser:

- http://127.0.0.1:8000/admin/ for the Django admin site
- http://127.0.0.1:8000/projects/ for the main Codebuddy app

## 2. Create your first project

1. Sign in to the app.
2. Go to the Projects page.
3. Click Create or New Project.
4. Give your project a name and describe the idea you want to build.
5. Choose the project type or category if prompted.

## 3. Answer the discovery questions

After creating a project, Codebuddy will guide you through a short setup flow.

Use this step to provide:

- the main problem your project solves
- the audience or users
- the goals of the project
- any important constraints or preferences

Be specific and clear. The better your answers, the better the AI-generated workspace will be.

## 4. Generate the initial workspace

Once you finish the setup questions:

1. Click Generate Workspace.
2. Wait for Codebuddy to build the project structure.
3. Review the generated sections such as Overview, Requirements, Roadmap, Tasks, Resources, Budget, Learning, Documentation, and Testing.

You can treat this generated workspace as a starting point, not a final product. You can always revise it later.

## 5. Explore the workspace

After generation, you can:

- open workspace folders and sections
- read the generated content
- edit sections when needed
- regenerate individual sections if you want a fresh version

Use the workspace view to understand the project structure before you start detailed work.

## 6. Manage tasks

Codebuddy also helps you break the project into tasks.

You can:

- create new tasks
- edit task names and descriptions
- set priorities
- mark tasks as in progress, review, or done
- add due dates and estimated hours
- create dependencies between tasks

A good habit is to update the task list whenever you make progress or discover new work.

## 7. Use the project board and timeline

If your project grows, use the board and timeline views to see progress more clearly.

- The board view is useful for tracking tasks by status.
- The timeline view helps you understand deadlines and milestones.
- The activity view shows recent changes and updates.

## 8. Use the AI assistant

The built-in workspace assistant can help you:

- refine project ideas
- generate additional tasks
- review project health
- suggest improvements
- help resolve project issues

Use the assistant when you want second opinions or help organizing your plan.

## 9. Review project health and conflicts

Codebuddy includes tools to review your project over time.

You can:

- review the project health summary
- inspect conflict reports
- resolve or ignore issues
- review change history if you want to undo recent edits

These features are especially useful when your project becomes more complex.

## 10. Best practices for new users

- Start with one clear project idea.
- Answer setup questions thoughtfully.
- Keep task names short and actionable.
- Update tasks regularly as work progresses.
- Use the AI-generated workspace as a draft, then improve it manually.
- Review your project periodically instead of waiting until the end.

## 11. Common workflow

A typical workflow looks like this:

1. Create a project.
2. Describe your idea.
3. Answer the discovery questions.
4. Generate the workspace.
5. Review the generated content.
6. Create or adjust tasks.
7. Track progress with the board or timeline.
8. Use the assistant and review tools when needed.

## 12. Troubleshooting

If something does not work:

- make sure your virtual environment is active
- confirm your OpenAI API key is set correctly
- run migrations again if the database is out of date
- check that the development server is running
- create a new superuser if you cannot sign in

## 13. Summary

Codebuddy is most useful when you treat it as a planning and workspace-generation tool that helps you move from an idea to a structured project quickly. The fastest path to value is:

1. create a project
2. answer the setup questions
3. generate the workspace
4. refine the tasks and folders
5. track progress over time

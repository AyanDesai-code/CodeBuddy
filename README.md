# Codebuddy

A Django-based project workspace generator and task manager that uses OpenAI to turn high-level project discovery conversations into an editable workspace.

## What this project is

`codebuddy` is a small Django app for authenticated users to:

- create a new project
- answer discovery questions for a project idea
- generate an initial workspace with sections like Overview, Requirements, Roadmap, Tasks, Resources, Budget, Learning, Documentation, and Testing
- manage workspace folders and tasks
- regenerate individual workspace sections

It stores projects, AI conversation messages, workspace folders, and tasks in SQLite.

## Dependencies

- Python 3.12+
- Django 6.0.x
- OpenAI Python SDK
- Pydantic

## Recommended setup

```bash
cd /home/ayan/codebuddy
python -m venv venv
source venv/bin/activate
pip install django openai pydantic
```

If you want to pin versions, use:

```bash
pip install "django>=6.0,<7.0" "openai>=1.0" "pydantic>=2.0"
```

## Required environment variables

The app uses the OpenAI client in `projects/ai/services.py`, so you must set:

```bash
export OPENAI_API_KEY="your_openai_api_key"
```

## Database setup

```bash
python manage.py migrate
```

## Create a user

```bash
python manage.py createsuperuser
```

## Run the development server

```bash
python manage.py runserver
```

Then open your browser at:

- `http://127.0.0.1:8000/admin/` — Django admin interface
- `http://127.0.0.1:8000/projects/` — main app pages after login

## How to use it

1. Log in as a user or admin.
2. Visit `/projects/` and start a new project.
3. Answer the discovery questions in the project setup flow.
4. When the AI is ready, generate the workspace.
5. Explore the generated workspace sections and tasks.
6. Edit folder content or regenerate an individual section if needed.

## Key app structure

- `manage.py` — Django command-line entry point
- `codebuddy/settings.py` — Django settings with SQLite database
- `projects/models.py` — Project, ProjectMessage, WorkspaceFolder, Task
- `projects/views.py` — project setup, workspace generation, folder/task pages
- `projects/urls.py` — app URL routes
- `projects/ai/services.py` — OpenAI integration and workspace generation prompts

## Notes

- This project runs in development mode (`DEBUG = True`).
- The SQLite database file is `db.sqlite3`.
- For production usage, update `SECRET_KEY`, `DEBUG`, and database settings.

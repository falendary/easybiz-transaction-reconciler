---
description: AI agent behaviour rules
alwaysApply: true
---

# Agent Behaviour

## Competence

- You are an expert in Python, Django, and Django REST Framework.
- You understand REST API design, service layer patterns, and LLM integrations.
- Write **English only**: code, comments, docstrings, commit messages, and user-visible strings.

## Working style

- Do only what you are asked. No scope creep.
- Answer to the point: fewer words, more action.
- No summaries of what you just did — the diff speaks for itself.
- No excuses for mistakes — just fix them.
- If you find a bug or smell while working nearby, flag it in one sentence. Do not fix it unless asked.

---

# Project Rules

## Environment

- **Always** use `venv/bin/python` and `venv/bin/pip` — never global Python.
- Run `python manage.py check` before every commit. Zero issues required.
- Secrets live in `.env` only. Never hardcode API keys, secret keys, or passwords.
- `.env` is always in `.gitignore`. `.env.example` documents every variable.

## Django

- Follow the layered architecture: models → services → serializers → views. Keep business logic out of views.
- Every model must have a `__str__` method and a docstring explaining its purpose.
- Every service function must have a docstring with parameters, return value, and exceptions.
- Every ViewSet action must have a docstring describing request format and all possible HTTP responses.
- Register all models in `admin.py` — never leave a model unregistered.
- When Django generates `tests.py` via `startapp`, delete it immediately if a `tests/` package is used instead.

## REST API

- Use DRF `DefaultRouter` for standard CRUD. Use `@action` for custom endpoints.
- Return consistent error shapes: `{"detail": "human-readable message"}`.
- Document every endpoint with `@extend_schema` when drf-spectacular is installed.
- Use `update_or_create` for upsert patterns — never query-then-save.
- Validate file uploads: check both size (reject over 20 MB) and MIME type (not just extension).

## Data integrity

- If two database fields serve different purposes, they must contain different values.
  Example: `raw_response` stores the exact API output; `summary` stores a processed version. Never assign the same value to both.
- OneToOne relationships use `update_or_create`, never a second `create`.

## External APIs (Claude, etc.)

- All calls go through a dedicated service module (e.g. `services/claude_service.py`).
- The service module is the only place that imports `anthropic` (or any external SDK).
- Never call external APIs from views, models, or serializers directly.

---

# Testing

- Every model, serializer, view action, and service function must have at least one test.
- **All** external API calls must be mocked with `unittest.mock.patch`. No real network calls in tests.
- Tests must pass with **both** runners:
  ```
  python manage.py test <app>.tests
  pytest
  ```
- Use `django.test.TestCase` (not pytest fixtures) so both runners work without extra config.
- Fixture files for upload tests (sample.pdf, sample.docx, sample.png) live in `<app>/tests/fixtures/`.
- Test error branches, not just happy paths: missing fields, wrong file type, oversized files, missing profile, Claude API failure (502).

---

# Git

## Commit conventions

Use conventional commits — every message starts with a type:

| Type | When |
|------|------|
| `chore:` | config, tooling, dependencies, no business logic |
| `feat:` | new functionality |
| `fix:` | bug fix |
| `test:` | tests only |
| `docs:` | documentation only |
| `refactor:` | restructuring, no behaviour change |

## Commit discipline

- One logical concern per commit — do not mix model changes with test changes.
- Never commit: `.env`, `db.sqlite3`, `media/`, `venv/`, `__pycache__/`, `.DS_Store`.
- Commit message body (optional) explains *why*, not *what* — the diff shows what.

---

# Python

## Imports

- Use absolute imports for project modules.
- Do not put imports inside methods unless strictly necessary.
- Do not add `from __future__ import annotations` unless the project requires it.

## Strings and formatting

- Double quotes for string literals.
- f-strings over `str.format()` or `%` formatting.
- Max 120 characters per line.

## Typing

- Type annotations on all function parameters and return values.
- Annotate variables when the type is non-obvious.

## Code style

- No extra blank lines inside functions.
- No `.py` files containing only comments (exception: `__init__.py`).
- Every file ends with a single newline.
# Task Manager API

A Django REST Framework API for managing tasks. You can create a task the usual way with JSON, or type it in plain English (for example *"Remind me to pay rent on the 1st of every month"*) and get a structured task back.

Features:

- **CRUD** for tasks, with one level of **subtasks** (deleting a parent deletes its subtasks).
- **Natural-language task creation** behind a swappable function, `parse_task_text`. Version 1 is rule-based; it can later be replaced by an LLM call without changing the view.
- **Automatic breakdown** of a task into subtasks.
- **Validation** with **one consistent error shape** for every 4xx/5xx response.
- **Idempotent creation**: retrying a POST with the same `Idempotency-Key` never creates a duplicate.
- **Filtering, search, ordering and pagination** that can all be combined in one request.
- Hand-written **OpenAPI** spec ([openapi.yaml](openapi.yaml)) and a **Postman collection** ([task_manager_api.postman_collection.json](task_manager_api.postman_collection.json)).

---

## Table of contents

1. [Tech stack](#tech-stack)
2. [Setup](#setup)
3. [Project layout](#project-layout)
4. [Data model](#data-model)
5. [Error shape](#error-shape)
6. [Endpoints](#endpoints)
7. [The swappable AI functions](#the-swappable-ai-functions)
8. [Idempotency](#idempotency)
9. [Testing](#testing)
10. [What the AI-generated checklist missed and what I changed](#what-the-ai-generated-checklist-missed-and-what-i-changed)

---

## Tech stack

| Piece | Version |
|---|---|
| Python | 3.12+ |
| Django | 6.1 |
| Django REST Framework | 3.18 |
| django-filter | 26.x |
| PostgreSQL (Docker) | 16 |
| psycopg2-binary | 2.9 |

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone <your-repo-url> task-manager
cd task-manager

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
```

### 2. Install requirements

```bash
pip install -r requirements.txt
```

### 3. Start Postgres in Docker

```bash
docker run --name taskmanager-db \
  -e POSTGRES_DB=taskmanager \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  -d postgres:16
```

`DATABASES` in [config/settings.py](config/settings.py) must point at this container:

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "taskmanager",
        "USER": "postgres",
        "PASSWORD": "postgres",
        "HOST": "localhost",
        "PORT": "5432",
    }
}
```

Connect a DB client (TablePlus, DBeaver, pgAdmin, or `psql`) with the same host, port, user and password to inspect the `tasks_task` table.

### 4. Set the Django secret key

`settings.py` reads it from the environment (it falls back to an insecure dev-only value if unset):

```bash
export DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')"
```

### 5. Migrate and run

```bash
python manage.py migrate
python manage.py runserver
```

The API is now at `http://127.0.0.1:8000/api/`.

### 6. (Optional) LLM API key

The default parser is rule-based and needs no key. If you switch `parse_task_text` to the optional LLM wrapper, provide the key through the environment. **Never commit it.**

```bash
# .env  (already listed in .gitignore)
LLM_API_KEY=your-key-here
```

```bash
export LLM_API_KEY=your-key-here     # or load .env with your shell / direnv
```

`settings.py` reads it with `os.environ.get("LLM_API_KEY")`. If the key is missing while the LLM parser is enabled, `POST /api/tasks/from-text/` returns **503** in the standard error shape instead of crashing.

---

## Project layout

```
config/            Django project (settings, root urls)
tasks/
  models.py        Task model
  serializers.py   TaskSerializer (all validation lives here)
  views.py         TaskViewSet, error helpers, idempotency store, break_down_task
  ai.py            parse_task_text (rule-based v1, swappable)
  urls.py          DefaultRouter registration
openapi.yaml       Hand-written OpenAPI 3 spec
task_manager_api.postman_collection.json   Hardened request collection
TESTING.md         AI-generated checklist, critique, and manual test steps
```

---

## Data model

`Task`

| Field | Type | Notes |
|---|---|---|
| `id` | integer | Auto |
| `title` | string (≤200) | Required, not blank |
| `description` | text | Required, not blank |
| `completed` | boolean | Default `false`. Must be a real JSON boolean |
| `due_date` | date `YYYY-MM-DD` | Optional. Must be a real calendar date (`2026-02-30` is rejected) |
| `priority` | `low` \| `medium` \| `high` | Default `medium` |
| `parent` | integer \| null | Optional FK to another task, `on_delete=CASCADE`, `related_name="subtasks"`. A subtask cannot itself have subtasks |
| `created_at` | datetime | `auto_now_add` |
| `updated_at` | datetime | `auto_now` |

---

## Error shape

**Every** error response (400, 404, 422, 502, 503) uses exactly this shape. `code` and `message` are always strings; `details` is always a list.

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed",
    "details": [
      { "field": "title", "issue": "must not be empty" }
    ]
  }
}
```

| Status | `code` | When |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Body fails serializer validation |
| 400 | `BAD_REQUEST` | Invalid priority level, or a malformed id |
| 404 | `NOT_FOUND` | Unknown task id, or a page number past the end |
| 422 | `IDEMPOTENCY_CONFLICT` | `Idempotency-Key` reused with a different body |
| 502 | `PARSER_ERROR` | The parser raised an exception, or its output failed validation. Nothing is saved |
| 503 | `LLM_UNAVAILABLE` | LLM parser enabled but `LLM_API_KEY` is not set |

---

## Endpoints

Base URL: `http://127.0.0.1:8000/api`

| Method | URL | Purpose | Success |
|---|---|---|---|
| GET | `/tasks/` | List tasks (filter, search, order, paginate) | 200 |
| POST | `/tasks/` | Create a task (supports `Idempotency-Key`) | 201 |
| GET | `/tasks/{id}/` | Retrieve one task | 200 |
| PUT | `/tasks/{id}/` | Replace a task | 200 |
| PATCH | `/tasks/{id}/` | Partially update a task | 200 |
| DELETE | `/tasks/{id}/` | Delete a task and its subtasks | 200 |
| POST | `/tasks/from-text/` | Create a task from plain English (supports `Idempotency-Key`) | 201 |
| GET | `/tasks/{id}/subtasks/` | List a task's subtasks | 200 |
| POST | `/tasks/{id}/subtasks/` | Create one subtask | 201 |
| POST | `/tasks/{id}/breakdown/` | Auto-split a task into subtasks (supports `Idempotency-Key`) | 201 |
| GET | `/priority/{level}` | List tasks with priority `low`, `medium` or `high` | 200 |

### Create a task: `POST /api/tasks/`

Request:

```http
POST /api/tasks/
Content-Type: application/json
Idempotency-Key: 7f9c2b1e-create-1

{
  "title": "Build task manager",
  "description": "Finish the DRF assignment",
  "due_date": "2026-12-01",
  "priority": "high"
}
```

Response `201 Created`:

```json
{
  "msg": "Task ID: 1 created successfully",
  "task": {
    "id": 1,
    "title": "Build task manager",
    "description": "Finish the DRF assignment",
    "completed": false,
    "due_date": "2026-12-01",
    "priority": "high",
    "parent": null,
    "created_at": "2026-11-24T16:10:02.481Z",
    "updated_at": "2026-11-24T16:10:02.481Z"
  }
}
```

### Validation error example

Request:

```http
POST /api/tasks/
Content-Type: application/json

{ "title": "", "description": "x", "due_date": "2026-02-30", "priority": "urgent", "completed": "yes" }
```

Response `400 Bad Request`:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed",
    "details": [
      { "field": "title", "issue": "must not be empty" },
      { "field": "completed", "issue": "must be a boolean" },
      { "field": "due_date", "issue": "must be a real date in YYYY-MM-DD format" },
      { "field": "priority", "issue": "must be one of low, medium, high" }
    ]
  }
}
```

### List tasks: `GET /api/tasks/`

Query parameters (all optional, all combinable):

| Param | Example | Effect |
|---|---|---|
| `page` | `?page=2` | Page number. Page size is 10 |
| `completed` | `?completed=true` | Filter by completion |
| `priority` | `?priority=high` | Filter by priority |
| `search` | `?search=rent` | Case-insensitive search in `title` and `description` |
| `ordering` | `?ordering=-created_at` | Order by `created_at`, `due_date`, `priority` or `title`; prefix `-` for descending |

Everything together:

```http
GET /api/tasks/?completed=false&priority=high&search=rent&ordering=-created_at&page=1
```

Response `200 OK`:

```json
{
  "count": 12,
  "next": "http://127.0.0.1:8000/api/tasks/?completed=false&ordering=-created_at&page=2&priority=high&search=rent",
  "previous": null,
  "results": [
    {
      "id": 14,
      "title": "Pay rent",
      "description": "Remind me to pay rent on the 1st of every month",
      "completed": false,
      "due_date": "2026-12-01",
      "priority": "high",
      "parent": null,
      "created_at": "2026-11-24T16:20:11.003Z",
      "updated_at": "2026-11-24T16:20:11.003Z"
    }
  ]
}
```

A page past the end (`?page=999`) returns `404` with code `NOT_FOUND`.

### Retrieve: `GET /api/tasks/{id}/`

Response `200 OK`:

```json
{
  "msg": "Task ID: 1 found",
  "task": { "id": 1, "title": "Build task manager", "...": "..." }
}
```

Unknown id, `GET /api/tasks/999/`. Response `404 Not Found`:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Not found",
    "details": [ { "field": "id", "issue": "Task 999 does not exist" } ]
  }
}
```

### Update: `PUT /api/tasks/{id}/` and `PATCH /api/tasks/{id}/`

PUT replaces the whole task, so send every required field:

```http
PUT /api/tasks/1/
Content-Type: application/json

{ "title": "Build task manager v2", "description": "All fields sent", "completed": false, "due_date": "2026-12-05", "priority": "medium" }
```

PATCH changes only what you send:

```http
PATCH /api/tasks/1/
Content-Type: application/json

{ "completed": true }
```

Response `200 OK`:

```json
{
  "msg": "Task ID: 1 partially updated successfully",
  "task": { "id": 1, "completed": true, "...": "..." }
}
```

### Delete: `DELETE /api/tasks/{id}/`

Deletes the task **and all its subtasks** (`on_delete=CASCADE`).

Response `200 OK`:

```json
{ "msg": "Task ID: 1 deleted successfully" }
```

### Natural-language create: `POST /api/tasks/from-text/`

Request:

```http
POST /api/tasks/from-text/
Content-Type: application/json
Idempotency-Key: rent-reminder-1

{ "text": "Remind me to pay rent on the 1st of every month" }
```

Response `201 Created` (assuming today is 2026-11-24):

```json
{
  "msg": "Task ID: 14 created successfully",
  "task": {
    "id": 14,
    "title": "Pay rent",
    "description": "Remind me to pay rent on the 1st of every month",
    "completed": false,
    "due_date": "2026-12-01",
    "priority": "medium",
    "parent": null,
    "recurrence": "monthly",
    "created_at": "2026-11-24T16:20:11.003Z",
    "updated_at": "2026-11-24T16:20:11.003Z"
  }
}
```

Phrases the rule-based parser understands:

| Phrase | Result |
|---|---|
| `today` / `tomorrow` | `due_date` = today / today + 1 day |
| `1st`, `2nd`, `15th`, ... | `due_date` = the next date with that day of the month |
| `every day` / `every week` / `every month` / `every year` | `recurrence` = `daily` / `weekly` / `monthly` / `yearly` |
| leading `remind me to` | removed from the title |

The parser raised an exception (for example `text` is missing or not a string). Response `502`, and **no row is saved**:

```json
{
  "error": {
    "code": "PARSER_ERROR",
    "message": "Parser failed",
    "details": [ { "field": "text", "issue": "'NoneType' object has no attribute 'lower'" } ]
  }
}
```

Parser output failed validation (for example an empty title). Response `502`, and **no row is saved**:

```json
{
  "error": {
    "code": "PARSER_ERROR",
    "message": "Parser returned invalid task data",
    "details": [ { "field": "title", "issue": "must not be empty" } ]
  }
}
```

### Subtasks: `POST` and `GET /api/tasks/{id}/subtasks/`

Create one subtask. `parent` is taken from the URL:

```http
POST /api/tasks/1/subtasks/
Content-Type: application/json

{ "title": "Write models", "description": "Task model with all fields" }
```

Response `201 Created`:

```json
{
  "msg": "Subtask ID: 2 with parent ID: 1 created successfully",
  "task": { "id": 2, "title": "Write models", "parent": 1, "...": "..." }
}
```

List them with `GET /api/tasks/1/subtasks/`. Response `200 OK`:

```json
{
  "msg": "All the subtasks for parent ID: 1",
  "subtasks": [ { "id": 2, "title": "Write models", "parent": 1, "...": "..." } ]
}
```

Adding a subtask to a task that is itself a subtask, `POST /api/tasks/2/subtasks/`. Response `400`:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed",
    "details": [ { "field": "parent", "issue": "a subtask cannot have subtasks" } ]
  }
}
```

### Breakdown: `POST /api/tasks/{id}/breakdown/`

Splits the parent's description on commas and on the whole word "and". Every generated item is validated first: if **any** item is invalid, **none** are saved.

Given task 1 with description `"Buy groceries, clean the kitchen and pay rent"`:

```http
POST /api/tasks/1/breakdown/
Idempotency-Key: breakdown-1-a
```

Response `201 Created`:

```json
{
  "msg": "Created 3 subtasks for parent ID: 1",
  "subtasks": [
    { "id": 5, "title": "Buy groceries",    "description": "Buy groceries",    "parent": 1, "...": "..." },
    { "id": 6, "title": "Clean the kitchen", "description": "Clean the kitchen", "parent": 1, "...": "..." },
    { "id": 7, "title": "Pay rent",         "description": "Pay rent",         "parent": 1, "...": "..." }
  ]
}
```

Breaking down a subtask returns `400 VALIDATION_ERROR`. An unknown id returns `404 NOT_FOUND`.

### Tasks by priority: `GET /api/priority/{level}`

```http
GET /api/priority/high
```

Response `200 OK`: a list of every task with that priority.

```json
[
  { "id": 1, "title": "Build task manager", "priority": "high", "...": "..." }
]
```

An invalid level, `GET /api/priority/urgent`. Response `400`:

```json
{
  "error": {
    "code": "BAD_REQUEST",
    "message": "Bad request",
    "details": [ "BAD REQUEST" ]
  }
}
```

---

## The swappable AI functions

Both live behind plain Python functions, so the view never knows whether a rule-based parser or an LLM produced the data.

### `parse_task_text(text, today)` in `tasks/ai.py`

```python
def parse_task_text(text: str, today: datetime.date) -> dict:
    """
    Turn one plain-English sentence into task fields.

    Args:
        text:  the raw user sentence, e.g. "Remind me to pay rent on the 1st of every month"
        today: the reference date for relative phrases ("tomorrow", "1st").
               Passed in, not read from the clock, so results are testable.

    Returns a dict:
        {
            "title":       str,              # short, non-empty
            "description": str,              # usually the original text
            "due_date":    "YYYY-MM-DD" | None,
            "recurrence":  "daily" | "weekly" | "monthly" | "yearly" | None   # optional
        }

    May raise any exception. The view catches it and returns 502.
    """
```

**Swapping to an LLM.** Write a function with the same signature that sends `text` and `today` to the model, asks for JSON with exactly these keys, and returns the parsed dict. The view does not change, because:

1. The output always goes through `TaskSerializer` exactly like user input ("never trust the output"). Invalid output gives **502**, and nothing is saved.
2. Any exception (network error, bad JSON) gives **502**.
3. A missing `LLM_API_KEY` gives **503**.
4. An idempotent replay returns the stored response **without calling the parser again**, so retries cost no tokens.

### `break_down_task(task)` in `tasks/views.py`

```python
def break_down_task(task: Task) -> list[dict]:
    """Return one dict per subtask: {"title", "description", "due_date", "parent"}.
    Rule-based v1 splits task.description on commas and the whole word "and"."""
```

---

## Idempotency

`POST /api/tasks/`, `POST /api/tasks/from-text/` and `POST /api/tasks/{id}/breakdown/` accept an optional `Idempotency-Key` header.

| Situation | Result |
|---|---|
| New key | Request runs normally. If it succeeds (2xx), `{key: {"body": ..., "response": ...}}` is stored |
| Same key, same body | Stored response is returned. Nothing is created and the parser is not called |
| Same key, different body | `422 IDEMPOTENCY_CONFLICT` |
| Request failed (4xx/5xx) | Nothing is stored, so the client can fix the input and retry with the same key |

The store is a module-level dictionary in `tasks/views.py`. It is in memory, so it is cleared on restart and not shared between worker processes. That is enough for this assignment; production would use Redis or a DB table.

**Proof:** send `POST /api/tasks/` twice with `Idempotency-Key: demo-1` and the same body. Then, in the DB client:

```sql
SELECT id, title, created_at FROM tasks_task WHERE title = 'Idempotency demo';
-- exactly one row
```

---

## Testing

- **Postman:** import [task_manager_api.postman_collection.json](task_manager_api.postman_collection.json) and run it top to bottom with the Collection Runner. It creates its own data and saves ids into collection variables. A collection-level test asserts that **every** 4xx/5xx response uses the error shape.
- **Checklist and manual steps:** [TESTING.md](TESTING.md) has the AI-generated checklist, my critique, and the manual checks (debugger breakpoints, simulating bad parser output, verifying cascade delete and idempotency in the DB client).

---

## What the AI-generated checklist missed and what I changed

I asked an AI assistant for a test checklist and Postman requests. Its first pass covered the happy paths (CRUD, one missing-title case, one invalid-priority case, a basic from-text call, one subtask, one breakdown) but missed most of the edge cases the brief cares about:

| Missed by the AI checklist | Why it matters | What I added |
|---|---|---|
| Whitespace-only title, missing `description` | "Must not be empty" is more than `""` | Requests for `"   "` and a missing field |
| `completed: "yes"` / `completed: 1` | DRF's `BooleanField` silently accepts these | Requests asserting 400 for non-boolean values |
| Impossible dates (`2026-02-30`) and wrong formats (`01-12-2026`) | Must be a *real* `YYYY-MM-DD` date | Both cases |
| Malformed JSON body | DRF's default parse error uses `{"detail": ...}`, not our error shape | Malformed-body request + global shape test |
| Unknown ids on **every** verb (GET, PUT, PATCH, DELETE, subtasks, breakdown) and a non-numeric id | It only tested GET | 404 checks on all of them |
| Repeated idempotency key / same key + different body / retry after a failed request | Core of Step 6 | A full idempotency folder for all three endpoints |
| Bad parser output (empty title, wrong type) and missing `text` | "Never trust the output" means 502 with nothing saved | Missing / empty / non-string `text`; manual 502 simulation in TESTING.md |
| Subtask of a subtask, through `/subtasks/`, `/breakdown/` **and** the plain `parent` field on `POST /tasks/` | Easy to block in one place and forget the others | All three paths |
| "and" inside words (`"Make sandwich"`) | Naive `replace("and", ",")` splits words | Breakdown request asserting no fragments |
| Page past the end, invalid priority level, all list params combined | Step 7 says they must work *together* | Combined-query request, `page=999`, `priority/urgent/` |
| Cascade delete verified after deleting the parent | The brief asks for proof | Delete parent, then GET the subtask (404) |
| Tests asserting the response **shape**, not just the status | A 400 with the wrong body is still a bug | Collection-level script that checks `error.code`, `error.message` (strings) and `error.details` (list) on every error |

I also found that some of the AI's assertions were wrong for this API: it expected the list endpoint to return a bare array (it is paginated), the created id at `body.id` (it is at `body.task.id`), and DELETE to return 204 (this API returns 200 with a message). I fixed those in the collection.

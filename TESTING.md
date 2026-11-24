# Testing: AI checklist, critique, and hardening

This is the Step 8 workflow: get a checklist from an AI assistant, run it, critique it, add what it missed, and save the result as [task_manager_api.postman_collection.json](task_manager_api.postman_collection.json).

---

## 1. First-pass checklist (AI-generated)

Prompt used: *"Generate a test checklist and Postman requests for a Django REST Framework Task Manager API with CRUD, subtasks, a from-text endpoint, breakdown, idempotency and filtering."*

What came back:

- [ ] `GET /api/tasks/` returns 200 and a list
- [ ] `POST /api/tasks/` with title + description returns 201
- [ ] `GET /api/tasks/{id}/` returns the task
- [ ] `PUT /api/tasks/{id}/` updates the title
- [ ] `PATCH /api/tasks/{id}/` marks `completed: true`
- [ ] `DELETE /api/tasks/{id}/` returns 204
- [ ] `POST /api/tasks/` without title returns 400
- [ ] `POST /api/tasks/` with `priority: "urgent"` returns 400
- [ ] `GET /api/tasks/999/` returns 404
- [ ] `POST /api/tasks/from-text/` with "Call mom tomorrow" returns 201 with tomorrow's date
- [ ] `POST /api/tasks/{id}/subtasks/` returns 201
- [ ] `GET /api/tasks/{id}/subtasks/` lists subtasks
- [ ] `POST /api/tasks/{id}/breakdown/` returns 201 with subtasks
- [ ] Sending the same `Idempotency-Key` twice returns the same task
- [ ] `GET /api/tasks/?priority=high` filters
- [ ] `GET /api/tasks/?page=2` paginates

## 2. Critique: what it missed

Checked against the brief's list of cases to look for (empty or invalid input, unknown IDs, a repeated idempotency key, the same key with a different body, impossible dates, bad parser output, and a subtask of a subtask):

| Gap in the AI checklist | Added |
|---|---|
| **Empty input** only as a missing title | Empty title, whitespace-only title, empty/missing description, title over 200 chars |
| **Invalid types** not tested | `completed: "yes"`, `completed: 1` (DRF's `BooleanField` accepts both unless you add strict validation) |
| **Impossible dates** not tested | `2026-02-30`, `2026-13-01`, `01-12-2026`, plus the valid leap day `2028-02-29` as a boundary |
| **Malformed JSON** not tested | Truncated JSON body; DRF's default `{"detail": ...}` does not match our error shape |
| **Error shape** never asserted; only status codes | Collection-level test: every 4xx/5xx must be `{"error": {"code": str, "message": str, "details": list}}`, and each request checks the exact `code` |
| **Unknown IDs** only on GET | PUT, PATCH, DELETE, GET/POST subtasks, breakdown, plus a non-numeric id |
| **Same key with a different body** missing | 422 `IDEMPOTENCY_CONFLICT` on `/tasks/`, `/from-text/` and `/breakdown/` |
| **Failed request + retry with the same key** missing | 400 first, then 201 with the same key (failures must not be cached) |
| **Proof only one row exists** missing | Search for the unique title after the replay and assert `count == 1` |
| **Bad parser output** missing | Missing / empty / whitespace / number / list `text`; very long text; manual empty-title simulation (section 4) |
| **from-text correctness** shallow | "1st" maps to the next 1st of a month, `every month` to `monthly`, title is readable and ≤200 chars |
| **Subtask of a subtask** missing | Blocked through `/subtasks/`, `/breakdown/`, and the plain `parent` field on `POST /tasks/`; a task as its own parent; an unknown parent id |
| **Subtasks list edge cases** missing | Task with **zero** subtasks (200 + `[]`, not 404) and with **two or more** |
| **Breakdown edge cases** missing | Replay doesn't duplicate rows; "and" inside a word (`sandwich`) is not split; a subtask can't be broken down |
| **Filters only tested alone** | Exact counts on seeded data for `completed`, `priority`, `search` (title **and** description), `ordering` (checked sorted), page 1 vs page 2, `page=999` → 404, and **all of them together in one request** |
| **Priority endpoint** missing | `/tasks/priority/high/` (200) and `/tasks/priority/urgent/` (400) |
| **Cascade delete** not verified | Delete parent → parent, manual subtask and breakdown subtask all 404 |
| **Wrong assertions** in the AI's requests | List is paginated (`results`), not a bare array; created id is at `task.id`, not `id`; DELETE returns 200 with a message, not 204 |

## 3. The hardened collection

[task_manager_api.postman_collection.json](task_manager_api.postman_collection.json): 86 requests in run order.

| Folder | Covers |
|---|---|
| 00 Setup | Main task used by later folders |
| 01 CRUD happy path | List, retrieve, PUT, PATCH, valid leap-day boundary |
| 02 Validation errors (400) | Every Step 3 rule, malformed JSON, PUT/PATCH validation |
| 03 Unknown ids (404) | Every verb and detail route |
| 04 Natural language | from-text correctness and bad `text` input |
| 05 Subtasks | Create/list, zero and many children, subtask-of-subtask on every path |
| 06 Breakdown | Split, replay, word-boundary "and", breakdown of a subtask |
| 07 Idempotency | Replay, one-row proof, 422 conflict, retry after failure, on all three POSTs |
| 08 Filter, search, ordering, pagination | Seeds 12 tagged tasks, exact counts, combined query, priority endpoint |
| 09 Cascade delete | Parent and all children gone |

### Running it

**Postman:** Import → Collection Runner → Run. Start the server first (`python manage.py runserver`). `baseUrl` defaults to `http://127.0.0.1:8000/api`.

**CLI (newman):**

```bash
npx newman run task_manager_api.postman_collection.json
# different host/port:
npx newman run task_manager_api.postman_collection.json --env-var baseUrl=http://127.0.0.1:8001/api
```

Each run uses a fresh `runId`, so it can be re-run against the same database.

## 4. Manual checks

### 4.1 Breakpoints on the parser and breakdown (debug mode)

VS Code `.vscode/launch.json` configuration:

```json
{
  "name": "Django runserver (debug)",
  "type": "debugpy",
  "request": "launch",
  "program": "${workspaceFolder}/manage.py",
  "args": ["runserver", "--noreload"],
  "django": true,
  "justMyCode": true
}
```

1. Put breakpoints on the first line of `parse_task_text` in `tasks/ai.py`, and on the line in `from_text` that builds `TaskSerializer(data=...)`.
2. Put a breakpoint on the `TaskSerializer(data=break_down_task(task), many=True)` line in `breakdown`.
3. Send "Rent on the 1st of every month" and "Breakdown main task" from the collection.
4. Inspect: the dict returned by the parser (`title`, `due_date`, `recurrence`), `serializer.is_valid()`, `serializer.errors`, and the list returned by `break_down_task`.

### 4.2 Simulate bad model output (expect 502, nothing saved)

1. Note the row count: `SELECT COUNT(*) FROM tasks_task;`
2. **Temporarily** make `parse_task_text` return an empty title (and, as a second run, a wrong type such as `"due_date": 12345`).
3. Send `POST /api/tasks/from-text/` with any text.
4. Expect **502** with `error.code == "PARSER_ERROR"` and the field in `details`.
5. Run the count again; it must be unchanged.
6. Also make `parse_task_text` `raise RuntimeError("boom")`: expect **502**, not 500.
7. **Revert the change.**

### 4.3 Cascade delete in the DB client

```sql
-- before deleting parent 1
SELECT id, title, parent_id FROM tasks_task WHERE id = 1 OR parent_id = 1;
-- DELETE /api/tasks/1/
SELECT id, title, parent_id FROM tasks_task WHERE id = 1 OR parent_id = 1;   -- 0 rows
```

### 4.4 Idempotency in the DB client

Send the same `POST /api/tasks/` twice with `Idempotency-Key: demo-1`, then:

```sql
SELECT id, title FROM tasks_task WHERE title = 'Idempotency demo';   -- exactly 1 row
```

Take screenshots of 4.3 and 4.4 for the submission.

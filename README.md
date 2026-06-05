# Project Dashboard

Standalone dashboard for Dee's local projects.

Public URL:

```text
https://projects.dees-workbench.com/
```

The public URL is protected by Cloudflare Access. The old public dashboard URL, `https://home.dees-workbench.com/`, now serves Dee's employer-facing personal site.

## Operational Rule

Do not edit `data/projects.json` directly to add, update, hide, show, or delete projects. It is now a sentinel file that should make database/API failures obvious. Use `project-dashboard-ingest` instead so updates are validated, written atomically, backed up, and stored in SQLite.

If `project-dashboard-ingest` cannot run, repair `data/projects.sqlite3` or restore from `data/backups/`; do not rebuild the live dashboard by expanding `data/projects.json`.

## Files

- `index.html` - dashboard shell.
- `manual.html` - operator manual for dashboard features, data flow, APIs, and daily automation.
- `assets/styles.css` - dashboard styling.
- `assets/app.js` - browser-side rendering and filters.
- `assets/project-mark.svg` - local visual mark.
- `data/projects.sqlite3` - SQLite project database and current source of truth after migration.
- `data/projects.json` - diagnostic sentinel only. The browser no longer reads this file as a runtime fallback.
- `bin/project-dashboard-ingest` - validates and installs dashboard data updates.
- `bin/server-ingest` - compatibility wrapper for the old command name.

## Source

The data snapshot was built from `/srv/cloud-mirror/workspaces` handoff/status files and the existing Prepper Disk site state.

Serve from this folder with:

```bash
python3 -m http.server 8090 --bind 0.0.0.0
```

## Data Ingest

Use `project-dashboard-ingest` to update dashboard data from JSON:

```bash
project-dashboard-ingest /path/to/project-update.json
project-dashboard-ingest /path/to/project-update.json --apply
```

Write operations default to dry-run. Use `--apply` only after the preview looks right. The ingest tool validates data, writes approved updates into SQLite, and refreshes `data/projects.json` as a small sentinel file. Use:

```bash
project-dashboard-ingest migrate-db
project-dashboard-ingest migrate-db --apply
```

to initialize or refresh `data/projects.sqlite3` from the current dashboard data.

Migration rule: do not let `data/projects.json` become a historical archive. SQLite owns history. The JSON file is only a diagnostic sentinel for humans and old tooling.

The server exposes the current dashboard shape from SQLite at:

```text
GET /api/dashboard
```

If SQLite is missing, empty, or unreadable, the endpoint returns HTTP 503 with:

```text
Database/API unavailable. Dashboard is not using fallback project data.
```

The browser does not read stale project data from `data/projects.json`.

That endpoint returns:

```json
{
  "ok": true,
  "dashboard": {
    "generated_at": "...",
    "source_root": "...",
    "projects": [],
    "recent_activity": []
  }
}
```

Health check:

```text
GET /api/health
```

That endpoint returns database availability, project count, schema version, and the last dashboard `generated_at` timestamp. It returns HTTP 503 when the SQLite-backed dashboard is unavailable.

Accepted input shapes:

- A full dashboard snapshot with `projects` and `recent_activity`.
- A list of project objects.
- A single project object.
- A partial project object for an existing project, as long as it includes `id`.

Supported project states:

```text
Active
On Hold
Complete
Staged
Reference
```

Optional AI resume metadata:

```json
{
  "ai_context": {
    "last_machine": "dees-workbench",
    "conversation_name": "Project dashboard state filters and AI resume metadata"
  }
}
```

Use `last_machine` values like `SBE-Mac`, `SBE-Lenovo`, or `dees-workbench`. This metadata is not displayed on the dashboard; it is kept in project data so AI sessions can resume with better context.

The selected-project panel includes AI resume launch helpers:

- `ChatGPT` opens ChatGPT and copies a project resume packet to the clipboard.
- `Codex` opens the Codex surface in ChatGPT and copies the same resume packet.
- `Terminal` copies a shell-ready resume command/comment block for the selected project.

Browsers do not reliably allow a normal website to inject text directly into ChatGPT, Codex, or a local terminal. These helpers use clipboard handoff as the safe fallback.

The copied packet includes project name, state, path, resume file, summary, next actions, blockers, tags, and hidden `ai_context`.

Optional hidden time metadata:

```json
{
  "time_tracking": {
    "approx_minutes_total": 90,
    "confidence": "medium",
    "notes": "Totals are rough.",
    "sessions": [
      {
        "date": "2026-06-05",
        "machine": "dees-workbench",
        "conversation_name": "Project dashboard resume launchers and time tracking",
        "approx_minutes": 90,
        "summary": "Added hidden resume and time metadata."
      }
    ]
  }
}
```

This is intentionally not rendered on the dashboard. It exists so future AI handoffs can see approximate effort by project. Prefer adding short session entries when project work is meaningful; use rough 5- or 15-minute increments rather than trying to be exact.

Optional hidden AI API spend metadata:

```json
{
  "ai_spend": {
    "estimated_usd_total": 0,
    "last_sync_estimated_usd": 0,
    "currency": "USD",
    "notes": "No API-backed sync runs recorded yet.",
    "sessions": [
      {
        "date": "2026-06-05",
        "machine": "dees-workbench",
        "conversation_name": "Project status sync",
        "model": "gpt-5-mini",
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_usd": 0,
        "summary": "Server-side sync run."
      }
    ]
  }
}
```

API-backed sync runs server-side only. Do not put an OpenAI API key in browser JavaScript. Store the key in the server environment, perform the sync on `dees-workbench`, and update only the project currently selected in the dashboard. Each run writes the estimated spend back into that project's `ai_spend` metadata.

The dashboard uses as few API calls as possible:

- Loading the dashboard makes zero OpenAI API calls.
- The AI Budget card reads local `ai_spend` metadata plus `/api/ai-budget`; it does not call OpenAI.
- Browser users can update only the selected project's state. AI sync writes are internal automation only.

Server environment variables:

```bash
OPENAI_API_KEY=sk-...
PROJECT_DASHBOARD_AI_MODEL=gpt-5-mini
PROJECT_DASHBOARD_AI_BUDGET_USD=1.00
PROJECT_DASHBOARD_AI_DAILY_BUDGET_USD=0.02
PROJECT_DASHBOARD_AI_MONTHLY_BUDGET_USD=0.25
PROJECT_DASHBOARD_AI_PER_RUN_MAX_USD=0.005
PROJECT_DASHBOARD_AI_MAX_SYNC_CALLS_PER_DAY=5
PROJECT_DASHBOARD_AI_SYNC_COOLDOWN_SECONDS=120
PROJECT_DASHBOARD_AI_SYNC_ENABLED=true
PROJECT_DASHBOARD_AI_INPUT_USD_PER_1M=0.25
PROJECT_DASHBOARD_AI_OUTPUT_USD_PER_1M=2.00
PROJECT_DASHBOARD_AI_MAX_OUTPUT_TOKENS=500
PROJECT_DASHBOARD_GET_AUTH_ENABLED=true
PROJECT_DASHBOARD_WRITE_AUTH_ENABLED=true
PROJECT_DASHBOARD_WRITE_ALLOWED_EMAILS=deannaelder8@gmail.com,selder65@gmail.com
PROJECT_DASHBOARD_WRITE_TOKEN=<server-only random token>
```

The dashboard budget is intentionally small because the OpenAI API budget is shared with other projects. The sync route also requires an explicit selected-project user action, enforces a per-sync cap, daily cap, monthly cap, daily call count, and cooldown before any OpenAI call is made. The default model and pricing values match `gpt-5-mini` standard text-token pricing as checked on 2026-06-05. Update the env vars if the model or pricing changes.

All `/api/*` GET routes require either an allowed Cloudflare Access user email header or the server-only `X-Project-Dashboard-Write-Token` header. Browser/user writes go through `POST /api/project-state`, which has the same auth requirement and can change only project state. `POST /api/sync-selected-project` is internal-token-only for local automation. Browser JavaScript does not contain the token.

State-change history is available through:

```text
GET /api/state-audit?limit=50
```

State changes also store hidden `ai_context.last_state_change` metadata on the project for future AI handoff packets.

## Daily Activity Agent

The server has a user-level systemd timer that runs once per day at midnight UTC:

```bash
systemctl --user status project-dashboard-daily-agent.timer --no-pager
systemctl --user list-timers --all --no-pager | grep project-dashboard-daily-agent
```

Timer and service files:

```text
/home/dee/.config/systemd/user/project-dashboard-daily-agent.timer
/home/dee/.config/systemd/user/project-dashboard-daily-agent.service
```

Script:

```text
/srv/cloud-mirror/project-dashboard/bin/project-dashboard-daily-agent
```

The agent scans recent file activity under `/srv/cloud-mirror`, maps touched files to the closest known dashboard project, adds newly active project folders with conservative `Staged` metadata, and then syncs only the touched projects through `/api/sync-selected-project`.

It does not have a separate OpenAI path. It reuses the selected-project API endpoint, so the existing guardrails still apply: total budget, daily budget, monthly budget, per-run estimate cap, max sync calls per day, and cooldown.

Additional daily-agent caps are set on the systemd service:

```text
PROJECT_DASHBOARD_DAILY_LOOKBACK_HOURS=24
PROJECT_DASHBOARD_DAILY_MAX_SYNCS=5
PROJECT_DASHBOARD_DAILY_MAX_NEW_PROJECTS=3
PROJECT_DASHBOARD_DAILY_MAX_FILES=1500
PROJECT_DASHBOARD_DAILY_MAX_WAIT_SECONDS=900
```

Dry run:

```bash
/srv/cloud-mirror/project-dashboard/bin/project-dashboard-daily-agent --dry-run
```

Useful options:

```bash
project-dashboard-ingest data/examples/project-update.json
project-dashboard-ingest data/examples/project-update.json --mode merge --apply
project-dashboard-ingest /path/to/projects.json --mode replace --apply
project-dashboard-ingest list
project-dashboard-ingest hide ingest-test-1 --apply
project-dashboard-ingest show ingest-test-1 --apply
project-dashboard-ingest delete ingest-test-1 --apply
project-dashboard-ingest /path/to/project-update.json --host dee@dees-workbench.local --apply
project-dashboard-ingest /path/to/project-update.json -dees-workbench.local --apply
```

`server-ingest` remains as a compatibility alias, but new notes and automation should use `project-dashboard-ingest`.

Local write operations create timestamped JSON and SQLite backups under `data/backups/` before updating SQLite and refreshing the sentinel `data/projects.json`. After each write, the tool verifies SQLite integrity, project count, and dashboard schema. If verification fails, it restores the SQLite backup and sentinel backup when available.

Ingest attempts are audited in two places:

```text
data/projects.sqlite3 table ingest_audit
data/ingest-audit.jsonl
```

The JSONL audit file is the fallback record if SQLite is unavailable.

Validation rejects malformed project IDs, invalid states, invalid dates, oversized payloads, huge arrays, negative time/spend values, unsafe links, path traversal, and obvious secret-looking values in visible fields. Path prefixes are portable by default; set `PROJECT_DASHBOARD_ALLOWED_PATH_PREFIXES` to an `os.pathsep`-separated allowlist only when a specific installation needs stricter local path boundaries.

`list` shows every project with its current state and visibility. `hide` keeps a project in SQLite with `hidden: true`, but removes it from dashboard counts and cards. `show` sets the project back to visible. `delete` removes the project entry from SQLite.

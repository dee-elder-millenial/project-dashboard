# Project Dashboard Agent Rules

## Data Updates

Do not edit `data/projects.json` by hand for project additions, status changes, hides, shows, or deletes. It is a diagnostic sentinel, not the dashboard data store.

Use `bin/project-dashboard-ingest` or the `project-dashboard-ingest` shell command instead:

```bash
project-dashboard-ingest /path/to/project-update.json
project-dashboard-ingest /path/to/project-update.json --apply
project-dashboard-ingest list
project-dashboard-ingest hide project-id --apply
project-dashboard-ingest show project-id --apply
project-dashboard-ingest delete project-id --apply
```

Write operations default to dry-run. Use `--apply` only after the preview looks right.

The ingest command validates dashboard data, writes SQLite, verifies the database, refreshes the sentinel JSON, creates timestamped backups under `data/backups/`, and audits attempts.

Direct edits to `data/projects.json` are only acceptable when repairing the diagnostic sentinel. Repair project data through SQLite backups or ingest.

## Site Code

Only edit site code for actual dashboard UI or behavior changes. Do not edit site code merely to update project content.

Browser/user writes are limited to project state changes through `POST /api/project-state`. AI sync is internal-token-only through local automation.

## Resume Logging

At the start of every Codex session running on `dees-workbench`, create or update a resume entry in:

`/srv/cloud-mirror/temp/codex-dees-workbench-resume/resume-commands.md`

Prefer using the helper:

```bash
codex-log-current-session "short task summary"
```

Use the current Codex thread id from `CODEX_THREAD_ID` when available. The resume command must be:

```bash
codex resume <CODEX_THREAD_ID>
```

Each entry should include date/time UTC, machine, working directory, exact resume command, current task, important touched files or services, and recovery steps. Keep older entries unless the user explicitly asks to remove them.

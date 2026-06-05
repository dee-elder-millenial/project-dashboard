# Project Dashboard Handoff

## Status

Project Dashboard is active and now has a polished command-center interface for tracking local projects, handoffs, blockers, next actions, paths, and recent continuity activity.

Important rule for future Codex/ChatGPT sessions:

```text
Do not edit data/projects.json directly to add, update, hide, show, or delete projects. It is now a sentinel file, not the dashboard data store. Use project-dashboard-ingest instead.
```

If `project-dashboard-ingest` cannot run, repair `data/projects.sqlite3` or restore from `data/backups/`; do not rebuild the live dashboard by expanding `data/projects.json`.

The project lives at:

```text
/srv/cloud-mirror/project-dashboard
```

LAN dashboard URL:

```text
http://dees-workbench.local:8090/
```

Public dashboard URL:

```text
https://projects.dees-workbench.com/
```

Public access state as of 2026-06-04:

- `projects.dees-workbench.com` is protected by Cloudflare Access.
- Unauthenticated requests redirect to the Cloudflare Access login.
- Intended allowlist is `deannaelder8@gmail.com` and `selder65@gmail.com`, deny everyone else by default.
- `home.dees-workbench.com` is no longer the dashboard URL; it is Dee's public employer-facing personal site.

GitHub repository:

```text
git@github.com:dee-elder-millenial/project-dashboard.git
```

Latest known pushed commit:

```text
ecd14a0 Fill overview card row
```

## What changed this session

- 2026-06-04 wrap-up:
  - Public URL moved to `https://projects.dees-workbench.com/`.
  - Project Dashboard is now behind Cloudflare Access.
  - `home.dees-workbench.com` now serves Dee's employer-facing personal site from the Workbench/Home root.
  - Dashboard data should include the new Personal Home Site project entry.
  - Dashboard now supports `Complete` and `On Hold` states in the ingest validator, desktop filters/bars, mobile filters, and state-pill styling.
  - State filters are visibility toggles now, so individual states can be shown or hidden without switching to a single-state filter.
  - Project records can include hidden `ai_context.last_machine` and `ai_context.conversation_name` metadata so AI sessions know which machine and conversation last touched the work.
  - Selected projects now have `ChatGPT`, `Codex`, and `Terminal` resume helpers. They open the relevant web surface where possible and copy a project-specific resume packet or shell command to the clipboard.
  - All project records now include hidden `time_tracking` metadata. It is approximate, not displayed on the dashboard, and is included in AI resume packets.
  - The old sync-as-state filter was removed. Sync status should be an operational action, not a portfolio state.
  - All project records now include hidden `ai_spend` metadata initialized at `$0.00` for API-backed sync-agent runs. The sync flow updates only the currently selected dashboard project, logs that run's estimated cost on that project's metadata, and makes no OpenAI calls during normal page load.
  - Added `/api/ai-budget` and `/api/sync-selected-project` to `host_router.py`. AI sync runs server-side for the selected project only and requires either an allowed Cloudflare Access user or the internal token plus explicit selected-project user-action checks.
  - Added server-side AI spend guardrails because the API budget is shared with other projects: explicit selected-project user-action header/body, browser confirmation, per-run cap, daily cap, monthly cap, max calls per day, and cooldown before another sync can run.
  - Current dashboard-specific API caps are intentionally conservative: `$1.00` total, `$0.02` daily, `$0.25` monthly, `$0.005` per sync, 5 syncs/day, 120-second cooldown, and 500 max output tokens.
  - Current tracked dashboard API spend is `$0.004901` from two successful selected-project sync calls on 2026-06-05. Both preserved project metadata via fallback because structured response parsing still needs tightening.
  - The local router runs through the user service `project-dashboard.service` and reads `/home/dee/.config/project-dashboard.env`; root/system service setup is still optional if reboot-before-login availability matters.
  - ChatGPT, Codex, and Terminal resume launchers now copy shell-ready commands instead of opening/copying raw packets. ChatGPT command opens ChatGPT and places the resume packet on the system clipboard, Codex copies an `ssh -t dee@dees-workbench ... codex resume <session id>` command for the latest matching project session in `/srv/cloud-mirror/temp/codex-dees-workbench-resume/resume-commands.md`, and Terminal copies an `ssh -t dee@dees-workbench ...` command that logs into the server and opens an interactive shell in the selected project directory.
  - Added `project-dashboard-daily-agent`, a midnight UTC user systemd timer that scans recent `/srv/cloud-mirror` file activity, adds newly active project folders with conservative `Staged` metadata, and syncs only touched projects through the existing guarded selected-project API endpoint.
  - Daily agent guardrails are layered: the script caps lookback, max new projects, max syncs, scanned files, and cooldown wait time; the API endpoint still enforces total budget, daily/monthly budget, per-sync cap, max calls/day, and cooldown before any OpenAI call.
  - Added `manual.html`, a dashboard-styled operator manual with block diagrams for request/data flow, AI sync guardrails, daily automation, command references, API routes, and important files.
  - About Dee Homepage was split into its own dashboard project and marked `Complete`.
  - Added desktop and mobile Work Calendar sections driven by hidden `time_tracking.sessions`, with month navigation, selected-day session details, and project drill-in from calendar entries.
  - Reconstructed project time-tracking dates from local evidence so the Work Calendar reflects actual observed work dates instead of stamping every historical estimate on 2026-06-05. Evidence used: git commit dates, file modification dates, handoff/status timestamps, dashboard backups, and known session notes.
  - Made the desktop Work Calendar compact and placed it beside the Current Workload card so it reads as a quick workload companion instead of a full-width section.
  - Constrained the Work Calendar Selected Day details list with its own scrollbar so busy days do not stretch the calendar panel down the page.
  - Moved the mobile project card list above the Work Calendar and selected-project detail so project cards are visible immediately after search/filter controls on small screens.
  - Started the SQLite migration. Added `project_store.py`, initialized `data/projects.sqlite3`, changed ingest to write SQLite plus a small sentinel `data/projects.json`, and added `GET /api/dashboard` to return the current dashboard shape from the server.
  - Migration decision: keep `data/projects.json` only as a temporary sentinel while the SQLite/API path proves stable. Do not turn it into a historical archive; SQLite owns growing history.
  - Tightened the SQLite failure path: `/api/dashboard`, `/api/ai-budget`, project resume lookup, and selected-project sync now require a populated SQLite database and return HTTP 503 with a clear "Database/API unavailable" message instead of rendering fallback JSON. Added `GET /api/health` for database availability, project count, schema version, and last generated timestamp. Removed the browser runtime fallback to `data/projects.json`.
  - Added the first ingest safety guardrails: stronger schema/data validation, payload and array limits, secret-looking visible-field detection, portable optional path-prefix enforcement via `PROJECT_DASHBOARD_ALLOWED_PATH_PREFIXES`, and dry-run-first writes that require `--apply`. Updated the daily agent to read SQLite directly and pass `--apply` when it intentionally creates detected project records.
  - Added API authorization: all `/api/*` GET routes require an allowed Cloudflare Access email or server-only write token; `POST /api/project-state` allows the same auth and can change only project state; `POST /api/sync-selected-project` allows an allowed Cloudflare Access user or the internal token, then enforces explicit user-action and budget guardrails.
  - Restored the selected-project Sync button after confirming unauthenticated and unauthorized sync attempts are rejected before any OpenAI call.
  - Added state-change history at `GET /api/state-audit?limit=50` and hidden `ai_context.last_state_change` metadata for future AI handoff packets.
  - Added `/srv/cloud-mirror/AI Agent Discovery Test/` with handoff/agent/status files as an intentionally untracked discovery seed. It is not in SQLite yet; the daily agent should discover it on the next scheduled scan if the scan rules match it.
  - Removed the top-level `Blocked` overview card from desktop and mobile, then widened the remaining overview cards so the row fills cleanly.
- Reworked the visual design from a rough dark-purple dashboard into a polished dark command-center layout.
- Added stronger hierarchy, cleaner cards, tighter spacing, improved state colors, and better responsive behavior.
- Converted the selected-project sidebar into a more useful Command Center panel.
- Added blocker-aware styling for the selected project.
- Updated date formatting so dashboard cards do not wrap awkwardly.
- Initialized the project as a Git repository.
- Pushed the first commit to GitHub under `dee-elder-millenial/project-dashboard`.

## Latest data refresh: 2026-06-03

- Scanned `/srv/cloud-mirror` for handoff files.
- Refreshed `data/projects.json` from the current project handoffs.
- Added dashboard entries for Dees Workbench Server, Uber Driving Analytics, GNS3 Network Lab, NASA Connections, Workspace Projects Staging, and Workspace Archive.
- Updated Sci Fi Story to show the current partial `Voyager Pics` blocker.
- Pointed dashboard resume files at the canonical `HANDOFF.md`, `status.md`, or start-here handoff for each project.
- Left sensitive details out of dashboard summaries; continue treating live dashboard data as local/LAN-oriented.
- Follow-up pass added `Network Upgrades and Security` from `/srv/cloud-mirror/Network Upgrades and Security/HANDOFF.md`.

## Key files

```text
index.html
manual.html
assets/styles.css
assets/app.js
data/projects.json
data/projects.sqlite3
data/examples/project-update.json
bin/project-dashboard-ingest
bin/server-ingest
assets/project-mark.svg
README.md
handoff.md
```

## How to run / view

The dashboard is served by `host_router.py`. The browser fetches live dashboard data from:

```text
/api/dashboard
```

`data/projects.json` is only a diagnostic sentinel. The browser no longer reads it as a runtime fallback.

Database health is available at:

```text
/api/health
```

It returns HTTP 200 when SQLite is readable and populated, or HTTP 503 when the dashboard database is missing, empty, or unreadable.

The served LAN page is:

```text
http://dees-workbench.local:8090/
```

The public Cloudflare Tunnel page is:

```text
https://projects.dees-workbench.com/
```

The public URL is Access-protected; use a permitted email identity to open it from outside the LAN.

If the dashboard server is not already running, serve the folder directly:

```bash
cd /srv/cloud-mirror/project-dashboard
python3 -m http.server 8090 --bind 0.0.0.0
```

## How to update project data

Use the ingest command:

```bash
project-dashboard-ingest /path/to/project-update.json
project-dashboard-ingest /path/to/project-update.json --apply
```

Write operations default to dry-run. Use `--apply` only after the preview looks right.

The command accepts:

- A full dashboard snapshot with `projects` and `recent_activity`.
- A list of project objects.
- A single project object.
- A partial project object for an existing project, as long as it includes `id`.

Examples:

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

Local write operations validate the result, create timestamped JSON and SQLite backups under `data/backups/` unless `--no-backup` is passed, write `data/projects.sqlite3`, verify SQLite integrity/project count/schema, and refresh `data/projects.json` atomically as a sentinel. If verification fails, the tool restores the SQLite backup and sentinel backup when available.

Ingest attempts are audited in `data/projects.sqlite3` table `ingest_audit` and in fallback JSONL form at `data/ingest-audit.jsonl`.

Validation rejects malformed project IDs, invalid states, invalid dates, oversized payloads, huge arrays, negative time/spend values, unsafe links, path traversal, and obvious secret-looking values in visible fields. Path prefixes are portable by default; set `PROJECT_DASHBOARD_ALLOWED_PATH_PREFIXES` to an `os.pathsep`-separated allowlist only when a specific installation needs stricter local path boundaries.

`list` shows every project with its current state and visibility. `hide` keeps a project in SQLite with `hidden: true`, but removes it from dashboard counts and cards. `show` sets the project back to visible. `delete` removes the project entry entirely.

When updating the dashboard from another project, create a small source payload in that project's ignored local state folder and ingest it from here. Example from AI Band:

```powershell
python H:\project-dashboard\bin\project-dashboard-ingest "\\dees-workbench\cloud-mirror\ai-band\state\dashboard-ai-band-update.json" --dashboard-root H:\project-dashboard --dry-run
python H:\project-dashboard\bin\project-dashboard-ingest "\\dees-workbench\cloud-mirror\ai-band\state\dashboard-ai-band-update.json" --dashboard-root H:\project-dashboard
```

This keeps project-specific status close to the project, lets the dashboard tool validate and back up the merge, and avoids brittle manual edits to `data/projects.json`.

Then hard refresh the browser with `Cmd + Shift + R`.

## Git workflow

From the project folder:

```bash
cd /srv/cloud-mirror/project-dashboard
git status
git add .
git commit -m "Describe the dashboard update"
git push
```

The local `main` branch tracks `origin/main`.

## Current next actions

1. Check the dashboard through Cloudflare Access and verify API reads include the expected Access identity headers.
2. Keep the SQLite database current as project statuses and handoffs change.
3. Expand the projects database to support project edit forms in the web UI, history/querying, sync-run records, time/session tables, and cleaner AI spend reporting.
4. Decide whether to build a generator that reads local handoff/status files and automatically rebuilds dashboard data.
5. Consider adding GitHub links to project cards later.
6. Keep secrets and private credentials out of dashboard-visible data.
7. Keep Cloudflare Access in front of the public dashboard hostname.
8. Use the dashboard in daily work before doing more visual tweaks.
9. Review the first `project-dashboard-daily-agent` run after midnight UTC and decide whether automatically detected `Staged` folders should remain, be renamed, or be hidden.

## Future ideas

- Consider a local-first cloud mirror later: keep `dees-workbench` as the source of truth so the dashboard remains available on the LAN if the internet is down, then publish a read-only/static mirror through Cloudflare Pages/R2 with Cloudflare Access. AWS or Azure can stay on the table if the dashboard grows into heavier cloud workloads, but do not move AI sync/write APIs off the local server until there is a clear need.
- Decision as of 2026-06-05: hold off on using the Cloudflare free R2/Pages capacity for now. Revisit if a read-only emergency mirror, small artifact archive, or sanitized dashboard snapshot becomes useful.

## Design notes

Current design direction:

- Dark command-center style
- Compact but readable cards
- Neon accents used sparingly
- State pills for Active, On Hold, Complete, Staged, and Reference
- Selected project panel focused on next actions and blockers
- Paths hidden under expandable details to reduce visual clutter

Avoid over-tweaking the theme unless daily use reveals a real usability issue.

## Safety notes

This dashboard exposes local paths and project summaries. Keep the public hostname behind Cloudflare Access unless sensitive paths and private project notes are removed.

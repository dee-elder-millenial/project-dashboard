from __future__ import annotations

import datetime as dt
import importlib.util
import json
import math
import os
import posixpath
import shutil
import hmac
import threading
import urllib.error
import urllib.request
from importlib.machinery import SourceFileLoader
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from typing import Any

import project_store


HOST = "0.0.0.0"
PORT = 8090

DASHBOARD_ROOT = Path("/srv/cloud-mirror/project-dashboard").resolve()
HOME_ROOT = Path("/srv/cloud-mirror/About Dee Homepage/site").resolve()
DATA_PATH = DASHBOARD_ROOT / "data" / "projects.json"
DB_PATH = DASHBOARD_ROOT / "data" / "projects.sqlite3"
BACKUP_ROOT = DASHBOARD_ROOT / "data" / "backups"
INGEST_PATH = DASHBOARD_ROOT / "bin" / "project-dashboard-ingest"
RESUME_LOG_PATH = Path("/srv/cloud-mirror/temp/codex-dees-workbench-resume/resume-commands.log")
RESUME_MARKDOWN_ARCHIVE_PATH = Path("/srv/cloud-mirror/temp/codex-dees-workbench-resume/resume-commands.md")
ALLOWED_CONTEXT_ROOTS = (
    Path("/srv/cloud-mirror").resolve(),
    Path("/cloud-mirror").resolve(),
    Path("/home/dee").resolve(),
)

DEFAULT_AI_MODEL = "gpt-5-mini"
DEFAULT_INPUT_USD_PER_1M = 0.25
DEFAULT_OUTPUT_USD_PER_1M = 2.00
DEFAULT_AI_BUDGET_USD = 1.00
DEFAULT_AI_DAILY_BUDGET_USD = 0.02
DEFAULT_AI_MONTHLY_BUDGET_USD = 0.25
DEFAULT_AI_PER_RUN_MAX_USD = 0.005
DEFAULT_AI_MAX_SYNC_CALLS_PER_DAY = 5
DEFAULT_AI_SYNC_COOLDOWN_SECONDS = 120
DEFAULT_MAX_OUTPUT_TOKENS = 500
PROJECT_STATES = ("Active", "On Hold", "Complete", "Staged", "Reference")

DATA_LOCK = threading.Lock()

PROJECT_SYNC_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "state": {
            "type": "string",
            "enum": ["Active", "On Hold", "Staged", "Reference", "Complete"],
        },
        "summary": {
            "type": "string",
            "description": "A concise dashboard summary under 220 characters.",
            "maxLength": 220,
        },
        "next_actions": {
            "type": "array",
            "maxItems": 6,
            "items": {"type": "string"},
        },
        "blockers": {
            "type": "array",
            "maxItems": 6,
            "items": {"type": "string"},
        },
        "tags": {
            "type": "array",
            "maxItems": 10,
            "items": {"type": "string"},
        },
        "sync_note": {
            "type": "string",
            "description": "One short note describing what changed or what was confirmed.",
            "maxLength": 180,
        },
    },
    "required": ["state", "summary", "next_actions", "blockers", "tags", "sync_note"],
}

HOME_HOSTS = {
    "home.dees-workbench.com",
}

DASHBOARD_HOSTS = {
    "projects.dees-workbench.com",
}


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_response(handler: SimpleHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(encoded)


def read_request_json(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON request body: {error}") from None
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    return payload


def load_dashboard() -> dict[str, Any]:
    return project_store.load_dashboard_from_db_required(DB_PATH)


def database_unavailable_payload(error: Exception | None = None) -> dict[str, Any]:
    payload = {
        "ok": False,
        "error": "Database/API unavailable. Dashboard is not using fallback project data.",
        "database": str(DB_PATH),
    }
    if error:
        payload["detail"] = str(error)
    return payload


def write_dashboard(data: dict[str, Any]) -> dict[str, str]:
    validator = load_ingest_validator()
    validator.validate_dashboard(data)

    backup_path = project_store.backup_json(DATA_PATH, BACKUP_ROOT)
    database_backup_path = project_store.backup_database(DB_PATH, BACKUP_ROOT)
    try:
        project_store.replace_dashboard(DB_PATH, data)
        project_store.verify_dashboard_database(DB_PATH, len(data.get("projects", [])))
        loaded = project_store.load_dashboard_from_db_required(DB_PATH)
        validator.validate_dashboard(loaded)
        project_store.write_fallback_sentinel(DATA_PATH, DB_PATH)
    except Exception:
        if database_backup_path:
            project_store.restore_database(database_backup_path, DB_PATH)
        if backup_path:
            shutil.copy2(backup_path, DATA_PATH)
        raise
    return {
        "json_backup": str(backup_path) if backup_path else "",
        "database_backup": str(database_backup_path) if database_backup_path else "",
    }


def load_ingest_validator() -> Any:
    loader = SourceFileLoader("project_dashboard_ingest", str(INGEST_PATH))
    spec = importlib.util.spec_from_loader("project_dashboard_ingest", loader)
    if not spec or not spec.loader:
        raise RuntimeError("could not load project-dashboard-ingest validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def find_project(data: dict[str, Any], project_id: str) -> dict[str, Any] | None:
    for project in data.get("projects", []):
        if project.get("id") == project_id:
            return project
    return None


def env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str) -> set[str]:
    value = os.environ.get(name, "")
    return {
        item.strip().lower()
        for item in value.replace(";", ",").split(",")
        if item.strip()
    }


def api_auth_config() -> dict[str, Any]:
    return {
        "write_enabled": env_bool("PROJECT_DASHBOARD_WRITE_AUTH_ENABLED", True),
        "get_enabled": env_bool("PROJECT_DASHBOARD_GET_AUTH_ENABLED", True),
        "allowed_emails": env_list("PROJECT_DASHBOARD_WRITE_ALLOWED_EMAILS"),
        "write_token": os.environ.get("PROJECT_DASHBOARD_WRITE_TOKEN", ""),
    }


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def ai_config() -> dict[str, Any]:
    return {
        "model": os.environ.get("PROJECT_DASHBOARD_AI_MODEL", DEFAULT_AI_MODEL),
        "budget_usd": env_float("PROJECT_DASHBOARD_AI_BUDGET_USD", DEFAULT_AI_BUDGET_USD),
        "daily_budget_usd": env_float("PROJECT_DASHBOARD_AI_DAILY_BUDGET_USD", DEFAULT_AI_DAILY_BUDGET_USD),
        "monthly_budget_usd": env_float("PROJECT_DASHBOARD_AI_MONTHLY_BUDGET_USD", DEFAULT_AI_MONTHLY_BUDGET_USD),
        "per_run_max_usd": env_float("PROJECT_DASHBOARD_AI_PER_RUN_MAX_USD", DEFAULT_AI_PER_RUN_MAX_USD),
        "max_sync_calls_per_day": env_int("PROJECT_DASHBOARD_AI_MAX_SYNC_CALLS_PER_DAY", DEFAULT_AI_MAX_SYNC_CALLS_PER_DAY),
        "sync_cooldown_seconds": env_int("PROJECT_DASHBOARD_AI_SYNC_COOLDOWN_SECONDS", DEFAULT_AI_SYNC_COOLDOWN_SECONDS),
        "input_usd_per_1m": env_float("PROJECT_DASHBOARD_AI_INPUT_USD_PER_1M", DEFAULT_INPUT_USD_PER_1M),
        "output_usd_per_1m": env_float("PROJECT_DASHBOARD_AI_OUTPUT_USD_PER_1M", DEFAULT_OUTPUT_USD_PER_1M),
        "max_output_tokens": env_int("PROJECT_DASHBOARD_AI_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS),
        "sync_enabled": env_bool("PROJECT_DASHBOARD_AI_SYNC_ENABLED", True),
        "api_enabled": bool(os.environ.get("OPENAI_API_KEY")),
    }


def total_ai_spend(data: dict[str, Any]) -> float:
    total = 0.0
    for project in data.get("projects", []):
        spend = project.get("ai_spend") or {}
        value = spend.get("estimated_usd_total", 0)
        if isinstance(value, (int, float)):
            total += float(value)
    return round(total, 6)


def usage_tokens(response: dict[str, Any]) -> tuple[int, int]:
    usage = response.get("usage") or {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0))
    return int(input_tokens or 0), int(output_tokens or 0)


def estimate_spend(input_tokens: int, output_tokens: int, config: dict[str, Any]) -> float:
    input_cost = (input_tokens / 1_000_000) * float(config["input_usd_per_1m"])
    output_cost = (output_tokens / 1_000_000) * float(config["output_usd_per_1m"])
    return round(input_cost + output_cost, 6)


def parse_session_datetime(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = dt.datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=dt.UTC)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def ai_spend_sessions(data: dict[str, Any]) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for project in data.get("projects", []):
        spend = project.get("ai_spend") or {}
        project_sessions = spend.get("sessions") or []
        if not isinstance(project_sessions, list):
            continue
        for session in project_sessions:
            if isinstance(session, dict):
                sessions.append(session)
    return sessions


def session_spend_since(data: dict[str, Any], since: dt.datetime) -> float:
    total = 0.0
    for session in ai_spend_sessions(data):
        when = parse_session_datetime(session.get("date"))
        if when is None or when < since:
            continue
        value = session.get("estimated_usd", 0)
        if isinstance(value, (int, float)):
            total += float(value)
    return round(total, 6)


def session_count_since(data: dict[str, Any], since: dt.datetime) -> int:
    count = 0
    for session in ai_spend_sessions(data):
        when = parse_session_datetime(session.get("date"))
        if when is not None and when >= since:
            count += 1
    return count


def latest_sync_session_at(data: dict[str, Any]) -> dt.datetime | None:
    latest: dt.datetime | None = None
    for session in ai_spend_sessions(data):
        when = parse_session_datetime(session.get("date"))
        if when is not None and (latest is None or when > latest):
            latest = when
    return latest


def estimate_preflight_spend(project: dict[str, Any], config: dict[str, Any]) -> dict[str, int | float]:
    context = project_context(project)
    input_tokens = max(1, math.ceil(len(context) / 4) + 500)
    output_tokens = int(config["max_output_tokens"])
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_usd": estimate_spend(input_tokens, output_tokens, config),
    }


def guardrail_state(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    now = dt.datetime.now(dt.UTC)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    latest = latest_sync_session_at(data)
    cooldown_remaining = 0
    if latest is not None:
        elapsed = max(0, int((now - latest).total_seconds()))
        cooldown_remaining = max(0, int(config["sync_cooldown_seconds"]) - elapsed)
    return {
        "daily_total_usd": session_spend_since(data, day_start),
        "monthly_total_usd": session_spend_since(data, month_start),
        "calls_today": session_count_since(data, day_start),
        "cooldown_remaining_seconds": cooldown_remaining,
    }


def enforce_sync_guardrails(data: dict[str, Any], project: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    state = guardrail_state(data, config)
    total = total_ai_spend(data)
    preflight = estimate_preflight_spend(project, config)
    projected_total = round(total + float(preflight["estimated_usd"]), 6)
    projected_day = round(float(state["daily_total_usd"]) + float(preflight["estimated_usd"]), 6)
    projected_month = round(float(state["monthly_total_usd"]) + float(preflight["estimated_usd"]), 6)

    if not config["sync_enabled"]:
        raise PermissionError("AI sync is disabled. Set PROJECT_DASHBOARD_AI_SYNC_ENABLED=true to enable it.")
    if state["cooldown_remaining_seconds"] > 0:
        raise PermissionError(f"AI sync cooldown active. Try again in {state['cooldown_remaining_seconds']} seconds.")
    if state["calls_today"] >= int(config["max_sync_calls_per_day"]):
        raise PermissionError("Daily AI sync call limit reached.")
    if float(preflight["estimated_usd"]) > float(config["per_run_max_usd"]):
        raise PermissionError(
            f"Preflight estimate ${preflight['estimated_usd']:.6f} exceeds per-run cap ${float(config['per_run_max_usd']):.6f}."
        )
    if projected_total > float(config["budget_usd"]):
        raise PermissionError("AI budget cap would be exceeded by this sync.")
    if projected_day > float(config["daily_budget_usd"]):
        raise PermissionError("Daily AI budget cap would be exceeded by this sync.")
    if projected_month > float(config["monthly_budget_usd"]):
        raise PermissionError("Monthly AI budget cap would be exceeded by this sync.")
    return preflight


def is_allowed_context_path(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in ALLOWED_CONTEXT_ROOTS:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def read_context_file(path_value: str, *, max_chars: int = 12000) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    if not path.is_absolute() or not is_allowed_context_path(path):
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > max_chars:
        return text[-max_chars:]
    return text


def project_context(project: dict[str, Any]) -> str:
    resume_text = read_context_file(str(project.get("resume_file") or ""))
    visible_project = {
        key: project.get(key)
        for key in (
            "id",
            "name",
            "state",
            "updated_at",
            "path",
            "resume_file",
            "summary",
            "next_actions",
            "blockers",
            "tags",
            "links",
            "ai_context",
            "time_tracking",
            "ai_spend",
        )
    }
    return "\n\n".join(
        [
            "Current dashboard project JSON:",
            json.dumps(visible_project, indent=2),
            "Resume/handoff file excerpt:",
            resume_text or "No readable resume file was found.",
        ]
    )


def extract_response_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]

    chunks: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks)


def parse_model_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("model did not return a JSON object") from None
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("model response must be a JSON object")
    return payload


def clean_string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:limit]


def fallback_project_update(project: dict[str, Any], error: Exception) -> dict[str, Any]:
    state = project.get("state")
    if state not in {"Active", "On Hold", "Staged", "Reference", "Complete"}:
        state = "Active"
    return {
        "state": state,
        "summary": str(project.get("summary") or "No summary recorded."),
        "next_actions": clean_string_list(project.get("next_actions"), limit=6),
        "blockers": clean_string_list(project.get("blockers"), limit=6),
        "tags": clean_string_list(project.get("tags"), limit=10),
        "sync_note": f"AI response could not be parsed; preserved existing metadata and recorded spend. {error}"[:240],
    }


def apply_project_update(project: dict[str, Any], update: dict[str, Any], config: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    allowed_states = {"Active", "On Hold", "Staged", "Reference", "Complete"}
    if isinstance(update.get("summary"), str) and update["summary"].strip():
        project["summary"] = update["summary"].strip()

    if update.get("state") in allowed_states:
        project["state"] = update["state"]

    next_actions = clean_string_list(update.get("next_actions"), limit=6)
    blockers = clean_string_list(update.get("blockers"), limit=6)
    tags = clean_string_list(update.get("tags"), limit=10)
    if next_actions:
        project["next_actions"] = next_actions
    if isinstance(update.get("blockers"), list):
        project["blockers"] = blockers
    if tags:
        project["tags"] = tags

    now = utc_now()
    input_tokens, output_tokens = usage_tokens(response)
    estimated_usd = estimate_spend(input_tokens, output_tokens, config)

    project["updated_at"] = now
    project["ai_context"] = {
        **(project.get("ai_context") or {}),
        "last_machine": os.uname().nodename,
        "conversation_name": "Dashboard Sync Selected Project",
    }

    spend = project.setdefault("ai_spend", {})
    sessions = spend.setdefault("sessions", [])
    if not isinstance(sessions, list):
        sessions = []
        spend["sessions"] = sessions
    previous_total = float(spend.get("estimated_usd_total") or 0)
    spend["estimated_usd_total"] = round(previous_total + estimated_usd, 6)
    spend["last_sync_estimated_usd"] = estimated_usd
    spend["currency"] = "USD"
    spend["notes"] = "Estimated from OpenAI API token usage returned by selected-project dashboard sync runs."
    sessions.append(
        {
            "date": now,
            "machine": os.uname().nodename,
            "conversation_name": "Dashboard Sync Selected Project",
            "model": str(config["model"]),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_usd": estimated_usd,
            "summary": str(update.get("sync_note") or "Selected-project status sync run."),
        }
    )
    spend["sessions"] = sessions[-20:]
    return {
        "estimated_usd": estimated_usd,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "updated_at": now,
    }


def call_openai_project_sync(project: dict[str, Any], config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set on the dashboard server")

    instructions = (
        "You update a personal project dashboard from local handoff context. "
        "Return only compact JSON with these keys: state, summary, next_actions, blockers, tags, sync_note. "
        "Use state only from: Active, On Hold, Staged, Reference, Complete. "
        "Keep summary under 220 characters. Use concise next_actions and blockers lists. "
        "Do not invent finished work; preserve uncertainty when the handoff is stale."
    )
    payload = {
        "model": config["model"],
        "input": [
            {"role": "developer", "content": instructions},
            {"role": "user", "content": project_context(project)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "project_dashboard_sync",
                "description": "Validated selected-project dashboard status update.",
                "strict": True,
                "schema": PROJECT_SYNC_RESPONSE_SCHEMA,
            }
        },
        "max_output_tokens": int(config["max_output_tokens"]),
    }
    encoded = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=encoded,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API returned HTTP {error.code}: {detail[:500]}") from None
    except urllib.error.URLError as error:
        raise RuntimeError(f"OpenAI API request failed: {error.reason}") from None

    text = extract_response_text(response_payload)
    try:
        update = parse_model_json(text)
    except ValueError as error:
        preview = text[:220].replace("\n", " ")
        update = fallback_project_update(project, ValueError(f"{error}; response preview: {preview}"))
    return update, response_payload


def budget_payload(data: dict[str, Any]) -> dict[str, Any]:
    config = ai_config()
    total = total_ai_spend(data)
    guardrails = guardrail_state(data, config)
    return {
        "total_usd": total,
        "budget_usd": config["budget_usd"],
        "remaining_usd": round(max(float(config["budget_usd"]) - total, 0), 6),
        "currency": "USD",
        "model": config["model"],
        "api_enabled": config["api_enabled"],
        "sync_enabled": config["sync_enabled"],
        "daily_total_usd": guardrails["daily_total_usd"],
        "daily_budget_usd": config["daily_budget_usd"],
        "monthly_total_usd": guardrails["monthly_total_usd"],
        "monthly_budget_usd": config["monthly_budget_usd"],
        "calls_today": guardrails["calls_today"],
        "max_sync_calls_per_day": config["max_sync_calls_per_day"],
        "per_run_max_usd": config["per_run_max_usd"],
        "sync_cooldown_seconds": config["sync_cooldown_seconds"],
        "cooldown_remaining_seconds": guardrails["cooldown_remaining_seconds"],
        "input_usd_per_1m": config["input_usd_per_1m"],
        "output_usd_per_1m": config["output_usd_per_1m"],
    }


def strip_markdown_code(value: str) -> str:
    return value.strip().strip("`").strip()


def codex_resume_entries() -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    if RESUME_LOG_PATH.exists():
        current: dict[str, str] | None = None
        for line in RESUME_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.rstrip("\n")
            if line == "--- codex-resume-entry ---":
                current = {}
                continue
            if line == "--- end ---":
                if current is None:
                    continue
                command = current.get("resume_command", "")
                if command.startswith("codex resume "):
                    entries.append(
                        {
                            "date": current.get("date_utc", ""),
                            "machine": current.get("machine", ""),
                            "working_dir": current.get("working_dir", ""),
                            "command": command,
                            "notes": current.get("task", ""),
                        }
                    )
                current = None
                continue
            if current is not None and "=" in line:
                key, value = line.split("=", 1)
                current[key.strip()] = value.strip()
    if not RESUME_MARKDOWN_ARCHIVE_PATH.exists():
        return entries

    for line in RESUME_MARKDOWN_ARCHIVE_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        if "codex resume " not in line or not line.lstrip().startswith("|"):
            continue
        parts = [strip_markdown_code(part) for part in line.strip().strip("|").split("|")]
        if len(parts) < 5 or parts[0].lower().startswith("date"):
            continue
        command_field = parts[3]
        if not command_field.startswith("codex resume "):
            command_field = parts[4] if len(parts) > 4 else ""
        if command_field.startswith("codex resume "):
            entries.append(
                {
                    "date": parts[0],
                    "machine": parts[1] if len(parts) > 1 else "",
                    "working_dir": parts[2] if len(parts) > 2 else "",
                    "command": command_field,
                    "notes": parts[4] if len(parts) > 4 else "",
                }
            )
    return entries


def normalize_dashboard_path(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip()
    if normalized.startswith("\\\\dees-workbench\\cloud-mirror\\"):
        normalized = "/srv/cloud-mirror/" + normalized.split("\\cloud-mirror\\", 1)[1].replace("\\", "/")
    return normalized.rstrip("/")


def codex_resume_command_for_project(project: dict[str, Any]) -> dict[str, str]:
    project_path = normalize_dashboard_path(project.get("path"))
    resume_file = normalize_dashboard_path(project.get("resume_file"))
    entries = codex_resume_entries()
    if not entries:
        raise FileNotFoundError("no Codex resume entries found")

    for entry in entries:
        working_dir = normalize_dashboard_path(entry.get("working_dir"))
        if not working_dir:
            continue
        if working_dir in {project_path, resume_file}:
            return entry
        if project_path and (working_dir.startswith(project_path + "/") or project_path.startswith(working_dir + "/")):
            return entry

    raise LookupError(f"no Codex resume command found for {project.get('name', 'selected project')}")


class HostRoutingHandler(SimpleHTTPRequestHandler):
    def root_for_request(self) -> Path:
        host = self.headers.get("Host", "").split(":", 1)[0].lower()
        if host in HOME_HOSTS:
            return HOME_ROOT
        return DASHBOARD_ROOT

    def api_allowed_for_request(self) -> bool:
        host = self.headers.get("Host", "").split(":", 1)[0].lower()
        return host in DASHBOARD_HOSTS or host in {"127.0.0.1", "localhost", "0.0.0.0", ""}

    def api_authorization(self, *, write: bool, allow_cloudflare_user: bool) -> tuple[bool, int, dict[str, Any]]:
        config = api_auth_config()
        if write and not config["write_enabled"]:
            return True, 200, {"ok": True, "auth": "disabled"}
        if not write and not config["get_enabled"]:
            return True, 200, {"ok": True, "auth": "disabled"}

        provided_token = self.headers.get("X-Project-Dashboard-Write-Token", "")
        expected_token = config["write_token"]
        if expected_token and provided_token and hmac.compare_digest(provided_token, expected_token):
            return True, 200, {"ok": True, "auth": "internal-token"}

        email = (
            self.headers.get("Cf-Access-Authenticated-User-Email")
            or self.headers.get("CF-Access-Authenticated-User-Email")
            or self.headers.get("X-Forwarded-Email")
            or ""
        ).strip().lower()
        if allow_cloudflare_user and email and email in config["allowed_emails"]:
            return True, 200, {"ok": True, "auth": "cloudflare-access", "email": email}

        supplied_credential = bool(provided_token or email)
        if not write:
            allowed_message = "API access requires the internal token or an allowed Cloudflare Access user."
        elif allow_cloudflare_user:
            allowed_message = "Write API requires an internal write token or an allowed Cloudflare Access user."
        else:
            allowed_message = "This API is internal-only and requires the server write token."
        return (
            False,
            403 if supplied_credential else 401,
            {
                "ok": False,
                "error": allowed_message,
            },
        )

    def do_GET(self) -> None:
        split = urlsplit(self.path)
        request_path = split.path
        if request_path.startswith("/api/") and not self.api_allowed_for_request():
            json_response(self, 404, {"ok": False, "error": "unknown API route"})
            return
        if request_path.startswith("/api/"):
            authorized, status, auth_payload = self.api_authorization(write=False, allow_cloudflare_user=True)
            if not authorized:
                json_response(self, status, auth_payload)
                return
        if request_path == "/api/dashboard":
            try:
                with DATA_LOCK:
                    data = load_dashboard()
                json_response(self, 200, {"ok": True, "dashboard": data})
            except project_store.DashboardDatabaseUnavailable as error:
                json_response(self, 503, database_unavailable_payload(error))
            except Exception as error:  # noqa: BLE001
                json_response(self, 500, {"ok": False, "error": str(error)})
            return
        if request_path == "/api/health":
            try:
                with DATA_LOCK:
                    database = project_store.database_status(DB_PATH)
                status = 200 if database["ok"] else 503
                json_response(
                    self,
                    status,
                    {
                        "ok": database["ok"],
                        "service": "project-dashboard",
                        "database": database,
                        "generated_at": utc_now(),
                    },
                )
            except Exception as error:  # noqa: BLE001
                json_response(self, 500, {"ok": False, "error": str(error)})
            return
        if request_path == "/api/ai-budget":
            try:
                with DATA_LOCK:
                    data = load_dashboard()
                json_response(self, 200, {"ok": True, "budget": budget_payload(data)})
            except project_store.DashboardDatabaseUnavailable as error:
                json_response(self, 503, database_unavailable_payload(error))
            except Exception as error:  # noqa: BLE001
                json_response(self, 500, {"ok": False, "error": str(error)})
            return
        if request_path == "/api/state-audit":
            try:
                limit_value = (parse_qs(split.query).get("limit") or ["50"])[0]
                try:
                    limit = int(limit_value)
                except ValueError:
                    raise ValueError("limit must be an integer") from None
                with DATA_LOCK:
                    entries = project_store.load_state_audit(DB_PATH, limit=limit)
                json_response(self, 200, {"ok": True, "entries": entries})
            except ValueError as error:
                json_response(self, 400, {"ok": False, "error": str(error)})
            except Exception as error:  # noqa: BLE001
                json_response(self, 500, {"ok": False, "error": str(error)})
            return
        if request_path == "/api/codex-resume-command":
            try:
                project_id = (parse_qs(split.query).get("project_id") or [""])[0].strip()
                if not project_id:
                    raise ValueError("project_id is required")
                with DATA_LOCK:
                    data = load_dashboard()
                    project = find_project(data, project_id)
                if not project:
                    json_response(self, 404, {"ok": False, "error": f"project not found: {project_id}"})
                    return
                entry = codex_resume_command_for_project(project)
                json_response(self, 200, {"ok": True, "command": entry["command"], "entry": entry})
            except ValueError as error:
                json_response(self, 400, {"ok": False, "error": str(error)})
            except (FileNotFoundError, LookupError) as error:
                json_response(self, 404, {"ok": False, "error": str(error)})
            except project_store.DashboardDatabaseUnavailable as error:
                json_response(self, 503, database_unavailable_payload(error))
            except Exception as error:  # noqa: BLE001
                json_response(self, 500, {"ok": False, "error": str(error)})
            return
        super().do_GET()

    def handle_project_state_update(self, auth_payload: dict[str, Any]) -> None:
        try:
            user_action = self.headers.get("X-Project-Dashboard-User-Action", "")
            if user_action != "update-project-state":
                json_response(
                    self,
                    428,
                    {
                        "ok": False,
                        "error": "State updates require an explicit project-state user action header.",
                    },
                )
                return

            payload = read_request_json(self)
            if payload.get("user_action") != "update-project-state":
                raise ValueError("state update requires user_action=update-project-state")

            project_id = str(payload.get("project_id") or "").strip()
            requested_state = str(payload.get("state") or "").strip()
            if not project_id:
                raise ValueError("project_id is required")
            if requested_state not in PROJECT_STATES:
                raise ValueError(f"state must be one of {', '.join(PROJECT_STATES)}")

            with DATA_LOCK:
                data = load_dashboard()
                project = find_project(data, project_id)
                if not project:
                    json_response(self, 404, {"ok": False, "error": f"project not found: {project_id}"})
                    return

                previous_state = project.get("state")
                changed = previous_state != requested_state
                now = utc_now()
                if changed:
                    project["state"] = requested_state
                    project["updated_at"] = now
                    ai_context = dict(project.get("ai_context") or {})
                    ai_context["last_state_change"] = {
                        "changed_at": now,
                        "changed_by": auth_payload.get("email") or auth_payload.get("auth") or "unknown",
                        "previous_state": previous_state,
                        "state": requested_state,
                    }
                    project["ai_context"] = ai_context
                    data["generated_at"] = now
                    activity = {
                        "updated_at": now,
                        "title": f"Moved {project['name']} to {requested_state}",
                        "summary": "Project state changed from the dashboard.",
                    }
                    recent = data.setdefault("recent_activity", [])
                    if isinstance(recent, list):
                        data["recent_activity"] = [activity, *recent][:12]
                    else:
                        data["recent_activity"] = [activity]
                    backup = write_dashboard(data)
                    project_store.log_ingest_audit(
                        DB_PATH,
                        {
                            "created_at": now,
                            "actor": auth_payload.get("email") or auth_payload.get("auth") or "unknown",
                            "operation": "project-state",
                            "mode": "state",
                            "source": "api",
                            "target": str(DB_PATH),
                            "dry_run": False,
                            "applied": True,
                            "success": True,
                            "project_count": len(data.get("projects", [])),
                            "changed": 1,
                            "backup_path": backup.get("json_backup", ""),
                            "database_backup_path": backup.get("database_backup", ""),
                            "details": {
                                "project_id": project_id,
                                "previous_state": previous_state,
                                "state": requested_state,
                            },
                        },
                    )
                else:
                    backup = {"json_backup": "", "database_backup": ""}

            json_response(
                self,
                200,
                {
                    "ok": True,
                    "project_id": project_id,
                    "previous_state": previous_state,
                    "state": requested_state,
                    "changed": changed,
                    "auth": auth_payload.get("auth", ""),
                    "backup": backup,
                    "dashboard": data,
                },
            )
        except project_store.DashboardDatabaseUnavailable as error:
            json_response(self, 503, database_unavailable_payload(error))
        except ValueError as error:
            json_response(self, 400, {"ok": False, "error": str(error)})
        except Exception as error:  # noqa: BLE001
            json_response(self, 500, {"ok": False, "error": str(error)})

    def do_POST(self) -> None:
        request_path = urlsplit(self.path).path
        if request_path.startswith("/api/") and not self.api_allowed_for_request():
            json_response(self, 404, {"ok": False, "error": "unknown API route"})
            return
        if request_path not in {"/api/sync-selected-project", "/api/project-state"}:
            json_response(self, 404, {"ok": False, "error": "unknown API route"})
            return

        authorized, status, auth_payload = self.api_authorization(
            write=True,
            allow_cloudflare_user=request_path in {"/api/project-state", "/api/sync-selected-project"},
        )
        if not authorized:
            json_response(self, status, auth_payload)
            return

        if request_path == "/api/project-state":
            self.handle_project_state_update(auth_payload)
            return

        try:
            user_action = self.headers.get("X-Project-Dashboard-User-Action", "")
            if user_action != "sync-selected":
                json_response(
                    self,
                    428,
                    {
                        "ok": False,
                        "error": "Sync requires an explicit selected-project user action header.",
                    },
                )
                return

            payload = read_request_json(self)
            if payload.get("user_action") != "sync-selected":
                raise ValueError("sync requires user_action=sync-selected")

            project_id = str(payload.get("project_id") or "").strip()
            if not project_id:
                raise ValueError("project_id is required")

            with DATA_LOCK:
                data = load_dashboard()
                config = ai_config()
                if not config["api_enabled"]:
                    json_response(
                        self,
                        503,
                        {
                            "ok": False,
                            "error": "OPENAI_API_KEY is not set on the dashboard server.",
                            "budget": budget_payload(data),
                        },
                    )
                    return

                budget = budget_payload(data)
                if budget["total_usd"] >= budget["budget_usd"]:
                    json_response(
                        self,
                        402,
                        {
                            "ok": False,
                            "error": "AI budget cap reached. Increase PROJECT_DASHBOARD_AI_BUDGET_USD to run more syncs.",
                            "budget": budget,
                        },
                    )
                    return

                project = find_project(data, project_id)
                if not project:
                    json_response(self, 404, {"ok": False, "error": f"project not found: {project_id}"})
                    return

                preflight = enforce_sync_guardrails(data, project, config)
                update, api_response = call_openai_project_sync(project, config)
                run = apply_project_update(project, update, config, api_response)
                run["preflight_estimated_usd"] = preflight["estimated_usd"]
                data["generated_at"] = run["updated_at"]
                activity = {
                    "updated_at": run["updated_at"],
                    "title": f"Synced {project['name']}",
                    "summary": "AI selected-project sync refreshed status.",
                }
                recent = data.setdefault("recent_activity", [])
                if isinstance(recent, list):
                    data["recent_activity"] = [activity, *recent][:12]
                else:
                    data["recent_activity"] = [activity]
                backup = write_dashboard(data)
                fresh_budget = budget_payload(data)

            json_response(
                self,
                200,
                {
                    "ok": True,
                    "project_id": project_id,
                    "run": run,
                    "backup": backup,
                    "budget": fresh_budget,
                    "dashboard": data,
                },
            )
        except PermissionError as error:
            try:
                with DATA_LOCK:
                    data = load_dashboard()
                budget = budget_payload(data)
            except Exception:  # noqa: BLE001
                budget = {}
            json_response(self, 429, {"ok": False, "error": str(error), "budget": budget})
        except project_store.DashboardDatabaseUnavailable as error:
            json_response(self, 503, database_unavailable_payload(error))
        except ValueError as error:
            json_response(self, 400, {"ok": False, "error": str(error)})
        except Exception as error:  # noqa: BLE001
            json_response(self, 500, {"ok": False, "error": str(error)})

    def translate_path(self, path: str) -> str:
        root = self.root_for_request()
        split = urlsplit(path)
        clean_path = posixpath.normpath(unquote(split.path))
        parts = [
            part
            for part in clean_path.split("/")
            if part and part not in {".", ".."} and "/" not in part
        ]

        resolved = root.joinpath(*parts).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            return str(root / "index.html")
        return str(resolved)

    def end_headers(self) -> None:
        self.send_header("X-Workbench-Route", str(self.root_for_request()))
        if self.root_for_request() == DASHBOARD_ROOT:
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        host = self.headers.get("Host", "-")
        super().log_message("[%s] " + format, host, *args)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), HostRoutingHandler)
    print(f"Serving host router on http://{HOST}:{PORT}/")
    print(f"  home.dees-workbench.com -> {HOME_ROOT}")
    print(f"  default/projects -> {DASHBOARD_ROOT}")
    server.serve_forever()


if __name__ == "__main__":
    main()

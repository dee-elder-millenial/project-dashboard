from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


class DashboardDatabaseUnavailable(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_timestamp() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")


def default_db_path(dashboard_root: Path) -> Path:
    return dashboard_root / "data" / "projects.sqlite3"


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def load_json_text(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS dashboard_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS projects (
          id TEXT PRIMARY KEY,
          display_order INTEGER NOT NULL,
          name TEXT NOT NULL,
          state TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          path TEXT NOT NULL,
          resume_file TEXT NOT NULL,
          summary TEXT NOT NULL,
          links_json TEXT NOT NULL,
          next_actions_json TEXT NOT NULL,
          blockers_json TEXT NOT NULL,
          tags_json TEXT NOT NULL,
          ai_context_json TEXT NOT NULL,
          time_tracking_json TEXT NOT NULL,
          ai_spend_json TEXT NOT NULL,
          hidden INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS recent_activity (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          display_order INTEGER NOT NULL,
          updated_at TEXT NOT NULL,
          title TEXT NOT NULL,
          summary TEXT NOT NULL,
          payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS time_sessions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          display_order INTEGER NOT NULL,
          session_date TEXT NOT NULL,
          machine TEXT NOT NULL,
          conversation_name TEXT NOT NULL,
          approx_minutes INTEGER NOT NULL DEFAULT 0,
          summary TEXT NOT NULL,
          payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ai_spend_sessions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          display_order INTEGER NOT NULL,
          session_date TEXT NOT NULL,
          machine TEXT NOT NULL,
          conversation_name TEXT NOT NULL,
          model TEXT NOT NULL,
          input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          estimated_usd REAL NOT NULL DEFAULT 0,
          summary TEXT NOT NULL,
          payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ingest_audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT NOT NULL,
          actor TEXT NOT NULL,
          operation TEXT NOT NULL,
          mode TEXT NOT NULL,
          source TEXT NOT NULL,
          target TEXT NOT NULL,
          dry_run INTEGER NOT NULL,
          applied INTEGER NOT NULL,
          success INTEGER NOT NULL,
          project_count INTEGER NOT NULL DEFAULT 0,
          added INTEGER NOT NULL DEFAULT 0,
          updated INTEGER NOT NULL DEFAULT 0,
          changed INTEGER NOT NULL DEFAULT 0,
          backup_path TEXT NOT NULL,
          database_backup_path TEXT NOT NULL,
          error TEXT NOT NULL,
          details_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_projects_order ON projects(display_order);
        CREATE INDEX IF NOT EXISTS idx_time_sessions_project_order ON time_sessions(project_id, display_order);
        CREATE INDEX IF NOT EXISTS idx_time_sessions_date ON time_sessions(session_date);
        CREATE INDEX IF NOT EXISTS idx_ai_spend_sessions_project_order ON ai_spend_sessions(project_id, display_order);
        CREATE INDEX IF NOT EXISTS idx_ai_spend_sessions_date ON ai_spend_sessions(session_date);
        CREATE INDEX IF NOT EXISTS idx_recent_activity_order ON recent_activity(display_order);
        CREATE INDEX IF NOT EXISTS idx_ingest_audit_created_at ON ingest_audit(created_at);
        """
    )
    connection.execute(
        "INSERT OR REPLACE INTO dashboard_meta(key, value) VALUES(?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )


def db_has_projects(db_path: Path) -> bool:
    if not db_path.exists():
        return False
    try:
        with connect(db_path) as connection:
            init_db(connection)
            row = connection.execute("SELECT COUNT(*) AS count FROM projects").fetchone()
            return bool(row and row["count"])
    except sqlite3.DatabaseError:
        return False


def database_status(db_path: Path) -> dict[str, Any]:
    status: dict[str, Any] = {
        "ok": False,
        "database": str(db_path),
        "exists": db_path.exists(),
        "project_count": 0,
        "generated_at": "",
        "schema_version": str(SCHEMA_VERSION),
    }
    if not db_path.exists():
        status["error"] = "SQLite database is missing."
        return status

    try:
        with connect(db_path) as connection:
            init_db(connection)
            row = connection.execute("SELECT COUNT(*) AS count FROM projects").fetchone()
            project_count = int(row["count"] if row else 0)
            generated_row = connection.execute(
                "SELECT value FROM dashboard_meta WHERE key = ?",
                ("generated_at",),
            ).fetchone()
            status["project_count"] = project_count
            status["generated_at"] = generated_row["value"] if generated_row else ""
            status["ok"] = project_count > 0
            if not status["ok"]:
                status["error"] = "SQLite database has no projects."
    except sqlite3.DatabaseError as error:
        status["error"] = f"SQLite database error: {error}"

    return status


def require_database(db_path: Path) -> dict[str, Any]:
    status = database_status(db_path)
    if not status["ok"]:
        raise DashboardDatabaseUnavailable(str(status.get("error") or "SQLite database is unavailable."))
    return status


def replace_dashboard(db_path: Path, dashboard: dict[str, Any]) -> None:
    with connect(db_path) as connection:
        init_db(connection)
        with connection:
            connection.execute("DELETE FROM ai_spend_sessions")
            connection.execute("DELETE FROM time_sessions")
            connection.execute("DELETE FROM recent_activity")
            connection.execute("DELETE FROM projects")
            connection.execute(
                "INSERT OR REPLACE INTO dashboard_meta(key, value) VALUES(?, ?)",
                ("generated_at", str(dashboard.get("generated_at") or utc_now())),
            )
            connection.execute(
                "INSERT OR REPLACE INTO dashboard_meta(key, value) VALUES(?, ?)",
                ("source_root", str(dashboard.get("source_root") or "")),
            )

            for order, project in enumerate(dashboard.get("projects", [])):
                time_tracking = dict(project.get("time_tracking") or {})
                ai_spend = dict(project.get("ai_spend") or {})
                time_sessions = list(time_tracking.get("sessions") or [])
                ai_sessions = list(ai_spend.get("sessions") or [])
                time_tracking["sessions"] = []
                ai_spend["sessions"] = []

                connection.execute(
                    """
                    INSERT INTO projects(
                      id, display_order, name, state, updated_at, path, resume_file, summary,
                      links_json, next_actions_json, blockers_json, tags_json, ai_context_json,
                      time_tracking_json, ai_spend_json, hidden
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project["id"],
                        order,
                        project["name"],
                        project["state"],
                        project["updated_at"],
                        project["path"],
                        project["resume_file"],
                        project["summary"],
                        json_text(project.get("links") or {}),
                        json_text(project.get("next_actions") or []),
                        json_text(project.get("blockers") or []),
                        json_text(project.get("tags") or []),
                        json_text(project.get("ai_context") or {}),
                        json_text(time_tracking),
                        json_text(ai_spend),
                        1 if project.get("hidden") else 0,
                    ),
                )

                for session_order, session in enumerate(time_sessions):
                    connection.execute(
                        """
                        INSERT INTO time_sessions(
                          project_id, display_order, session_date, machine, conversation_name,
                          approx_minutes, summary, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            project["id"],
                            session_order,
                            str(session.get("date") or ""),
                            str(session.get("machine") or ""),
                            str(session.get("conversation_name") or ""),
                            int(session.get("approx_minutes") or 0),
                            str(session.get("summary") or ""),
                            json_text(session),
                        ),
                    )

                for session_order, session in enumerate(ai_sessions):
                    connection.execute(
                        """
                        INSERT INTO ai_spend_sessions(
                          project_id, display_order, session_date, machine, conversation_name,
                          model, input_tokens, output_tokens, estimated_usd, summary, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            project["id"],
                            session_order,
                            str(session.get("date") or ""),
                            str(session.get("machine") or ""),
                            str(session.get("conversation_name") or ""),
                            str(session.get("model") or ""),
                            int(session.get("input_tokens") or 0),
                            int(session.get("output_tokens") or 0),
                            float(session.get("estimated_usd") or 0),
                            str(session.get("summary") or ""),
                            json_text(session),
                        ),
                    )

            for order, activity in enumerate(dashboard.get("recent_activity", [])):
                connection.execute(
                    """
                    INSERT INTO recent_activity(display_order, updated_at, title, summary, payload_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        order,
                        str(activity.get("updated_at") or ""),
                        str(activity.get("title") or ""),
                        str(activity.get("summary") or ""),
                        json_text(activity),
                    ),
                )


def load_dashboard_from_db(db_path: Path) -> dict[str, Any]:
    with connect(db_path) as connection:
        init_db(connection)
        meta = {
            row["key"]: row["value"]
            for row in connection.execute("SELECT key, value FROM dashboard_meta")
        }
        projects: list[dict[str, Any]] = []
        for row in connection.execute("SELECT * FROM projects ORDER BY display_order, name"):
            project = {
                "id": row["id"],
                "name": row["name"],
                "state": row["state"],
                "updated_at": row["updated_at"],
                "path": row["path"],
                "resume_file": row["resume_file"],
                "summary": row["summary"],
                "next_actions": load_json_text(row["next_actions_json"], []),
                "blockers": load_json_text(row["blockers_json"], []),
                "tags": load_json_text(row["tags_json"], []),
                "links": load_json_text(row["links_json"], {}),
            }
            if row["hidden"]:
                project["hidden"] = True

            ai_context = load_json_text(row["ai_context_json"], {})
            if ai_context:
                project["ai_context"] = ai_context

            time_tracking = load_json_text(row["time_tracking_json"], {})
            time_tracking["sessions"] = [
                load_json_text(session_row["payload_json"], {})
                for session_row in connection.execute(
                    "SELECT payload_json FROM time_sessions WHERE project_id = ? ORDER BY display_order, id",
                    (row["id"],),
                )
            ]
            if time_tracking:
                project["time_tracking"] = time_tracking

            ai_spend = load_json_text(row["ai_spend_json"], {})
            ai_spend["sessions"] = [
                load_json_text(session_row["payload_json"], {})
                for session_row in connection.execute(
                    "SELECT payload_json FROM ai_spend_sessions WHERE project_id = ? ORDER BY display_order, id",
                    (row["id"],),
                )
            ]
            if ai_spend:
                project["ai_spend"] = ai_spend

            projects.append(project)

        recent_activity = [
            load_json_text(row["payload_json"], {})
            for row in connection.execute(
                "SELECT payload_json FROM recent_activity ORDER BY display_order, id"
            )
        ]

    return {
        "generated_at": meta.get("generated_at") or utc_now(),
        "source_root": meta.get("source_root") or "",
        "projects": projects,
        "recent_activity": recent_activity,
    }


def load_dashboard_from_db_required(db_path: Path) -> dict[str, Any]:
    require_database(db_path)
    return load_dashboard_from_db(db_path)


def backup_database(db_path: Path, backup_root: Path) -> Path | None:
    if not db_path.exists():
        return None
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_path = backup_root / f"{db_path.stem}.{file_timestamp()}.sqlite3"
    with sqlite3.connect(db_path) as source:
        with sqlite3.connect(backup_path) as destination:
            source.backup(destination)
    return backup_path


def restore_database(backup_path: Path, db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    shutil.copy2(backup_path, db_path)


def verify_dashboard_database(db_path: Path, expected_project_count: int) -> None:
    with connect(db_path) as connection:
        init_db(connection)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity[0] if integrity else 'no result'}")
        row = connection.execute("SELECT COUNT(*) AS count FROM projects").fetchone()
        project_count = int(row["count"] if row else 0)
        if project_count != expected_project_count:
            raise RuntimeError(
                f"SQLite project count mismatch after write: expected {expected_project_count}, got {project_count}"
            )


def log_ingest_audit(db_path: Path, entry: dict[str, Any]) -> None:
    with connect(db_path) as connection:
        init_db(connection)
        with connection:
            connection.execute(
                """
                INSERT INTO ingest_audit(
                  created_at, actor, operation, mode, source, target, dry_run, applied, success,
                  project_count, added, updated, changed, backup_path, database_backup_path,
                  error, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(entry.get("created_at") or utc_now()),
                    str(entry.get("actor") or ""),
                    str(entry.get("operation") or ""),
                    str(entry.get("mode") or ""),
                    str(entry.get("source") or ""),
                    str(entry.get("target") or ""),
                    1 if entry.get("dry_run") else 0,
                    1 if entry.get("applied") else 0,
                    1 if entry.get("success") else 0,
                    int(entry.get("project_count") or 0),
                    int(entry.get("added") or 0),
                    int(entry.get("updated") or 0),
                    int(entry.get("changed") or 0),
                    str(entry.get("backup_path") or ""),
                    str(entry.get("database_backup_path") or ""),
                    str(entry.get("error") or ""),
                    json_text(entry.get("details") or {}),
                ),
            )


def load_state_audit(db_path: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 50), 200))
    with connect(db_path) as connection:
        init_db(connection)
        rows = connection.execute(
            """
            SELECT id, created_at, actor, success, backup_path, database_backup_path, details_json
            FROM ingest_audit
            WHERE operation = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            ("project-state", limit),
        ).fetchall()

    entries: list[dict[str, Any]] = []
    for row in rows:
        details = load_json_text(row["details_json"], {})
        entries.append(
            {
                "id": row["id"],
                "changed_at": row["created_at"],
                "changed_by": row["actor"],
                "success": bool(row["success"]),
                "project_id": details.get("project_id", ""),
                "previous_state": details.get("previous_state", ""),
                "state": details.get("state", ""),
                "backup_path": row["backup_path"],
                "database_backup_path": row["database_backup_path"],
            }
        )
    return entries


def write_json_snapshot(path: Path, dashboard: dict[str, Any], *, pretty: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temp_path = Path(handle.name)
        if pretty:
            json.dump(dashboard, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        else:
            json.dump(dashboard, handle, separators=(",", ":"), ensure_ascii=False)
            handle.write("\n")
    os.replace(temp_path, path)


def write_fallback_sentinel(path: Path, db_path: Path) -> None:
    payload = {
        "ok": False,
        "error": "Project Dashboard runtime data now comes from /api/dashboard backed by SQLite. If you are seeing this file, the database/API path is unavailable.",
        "database": str(db_path),
        "generated_at": utc_now(),
    }
    write_json_snapshot(path, payload, pretty=True)


def backup_json(path: Path, backup_root: Path) -> Path | None:
    if not path.exists():
        return None
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_path = backup_root / f"{path.stem}.{file_timestamp()}{path.suffix}"
    shutil.copy2(path, backup_path)
    return backup_path


def load_dashboard(dashboard_root: Path, json_path: Path | None = None) -> dict[str, Any]:
    db_path = default_db_path(dashboard_root)
    if db_has_projects(db_path):
        return load_dashboard_from_db(db_path)
    path = json_path or dashboard_root / "data" / "projects.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "generated_at": utc_now(),
        "source_root": str(dashboard_root),
        "projects": [],
        "recent_activity": [],
    }

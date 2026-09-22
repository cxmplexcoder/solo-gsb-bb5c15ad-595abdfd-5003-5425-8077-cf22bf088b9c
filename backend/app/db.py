"""SQLite persistence (stdlib sqlite3, one file under DATA_DIR)."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

_DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(_DATA_DIR, "annotation.db")

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def init() -> None:
    global _conn
    os.makedirs(_DATA_DIR, exist_ok=True)
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA foreign_keys=ON")
    _conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            document    TEXT NOT NULL DEFAULT '{"segments":[],"annotations":[]}',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rules (
            id          TEXT PRIMARY KEY,
            project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            config      TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rule_runs (
            id          TEXT PRIMARY KEY,
            rule_id     TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
            applied_at  TEXT NOT NULL,
            count       INTEGER NOT NULL DEFAULT 0,
            summary     TEXT NOT NULL DEFAULT '{}',
            undone_at   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_rules_project ON rules(project_id);
        CREATE INDEX IF NOT EXISTS idx_rule_runs_rule ON rule_runs(rule_id, applied_at);
        """
    )
    # migration: older databases predate the undone_at column
    cols = {r[1] for r in _conn.execute("PRAGMA table_info(rule_runs)")}
    if "rule_runs" in {
        r[0] for r in _conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
    } and "undone_at" not in cols:
        _conn.execute("ALTER TABLE rule_runs ADD COLUMN undone_at TEXT")
    _conn.commit()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "document": json.loads(row["document"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def list_projects() -> list[dict]:
    with _lock:
        rows = _conn.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_project(project_id: str) -> dict | None:
    with _lock:
        row = _conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def create_project(name: str, document: dict | None = None) -> dict:
    pid = new_id("proj")
    now = _now()
    doc = document if document is not None else {"segments": [], "annotations": []}
    with _lock:
        _conn.execute(
            "INSERT INTO projects (id, name, document, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (pid, name, json.dumps(doc, ensure_ascii=False), now, now),
        )
        _conn.commit()
    return get_project(pid)


def update_project(project_id: str, name: str | None, document: dict) -> dict | None:
    now = _now()
    with _lock:
        if name is not None:
            _conn.execute(
                "UPDATE projects SET name = ?, document = ?, updated_at = ?"
                " WHERE id = ?",
                (name, json.dumps(document, ensure_ascii=False), now, project_id),
            )
        else:
            _conn.execute(
                "UPDATE projects SET document = ?, updated_at = ? WHERE id = ?",
                (json.dumps(document, ensure_ascii=False), now, project_id),
            )
        _conn.commit()
    return get_project(project_id)


def delete_project(project_id: str) -> bool:
    with _lock:
        cur = _conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        _conn.commit()
    return cur.rowcount > 0


# ---------- batch rules ----------

_LAST_RUN_SQL = (
    "SELECT * FROM rule_runs WHERE rule_id = ? AND undone_at IS NULL"
    " ORDER BY applied_at DESC, rowid DESC LIMIT 1"
)


def _run_to_dict(row: sqlite3.Row, include_summary: bool = True) -> dict:
    run = {
        "id": row["id"],
        "ruleId": row["rule_id"],
        "appliedAt": row["applied_at"],
        "count": row["count"],
        "undone": row["undone_at"] is not None,
    }
    if include_summary:
        run["summary"] = json.loads(row["summary"])
    return run


def _rule_to_dict(row: sqlite3.Row, last_run: sqlite3.Row | None = None) -> dict:
    rule = {
        "id": row["id"],
        "projectId": row["project_id"],
        "name": row["name"],
        "config": json.loads(row["config"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "lastRun": None,
    }
    if last_run is not None:
        rule["lastRun"] = _run_to_dict(last_run, include_summary=False)
    return rule


def list_rules(project_id: str) -> list[dict]:
    with _lock:
        rows = _conn.execute(
            "SELECT * FROM rules WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        out = []
        for r in rows:
            last = _conn.execute(_LAST_RUN_SQL, (r["id"],)).fetchone()
            out.append(_rule_to_dict(r, last))
    return out


def get_rule(rule_id: str) -> dict | None:
    with _lock:
        r = _conn.execute("SELECT * FROM rules WHERE id = ?",
                          (rule_id,)).fetchone()
        if r is None:
            return None
        last = _conn.execute(_LAST_RUN_SQL, (rule_id,)).fetchone()
    return _rule_to_dict(r, last)


def create_rule(project_id: str, config: dict) -> dict:
    rid = new_id("rule")
    now = _now()
    with _lock:
        _conn.execute(
            "INSERT INTO rules (id, project_id, name, config, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (rid, project_id, config["name"],
             json.dumps(config, ensure_ascii=False), now, now),
        )
        _conn.commit()
    return get_rule(rid)


def update_rule(rule_id: str, config: dict) -> dict | None:
    now = _now()
    with _lock:
        cur = _conn.execute(
            "UPDATE rules SET name = ?, config = ?, updated_at = ? WHERE id = ?",
            (config["name"], json.dumps(config, ensure_ascii=False), now, rule_id),
        )
        _conn.commit()
    return get_rule(rule_id) if cur.rowcount else None


def delete_rule(rule_id: str) -> bool:
    with _lock:
        cur = _conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
        _conn.commit()
    return cur.rowcount > 0


def add_rule_run(rule_id: str, count: int, summary: dict,
                 run_id: str | None = None) -> dict:
    run_id = run_id or new_id("run")
    now = _now()
    with _lock:
        _conn.execute(
            "INSERT INTO rule_runs (id, rule_id, applied_at, count, summary)"
            " VALUES (?, ?, ?, ?, ?)",
            (run_id, rule_id, now, count,
             json.dumps(summary, ensure_ascii=False)),
        )
        _conn.commit()
        row = _conn.execute("SELECT * FROM rule_runs WHERE id = ?",
                            (run_id,)).fetchone()
    return _run_to_dict(row)


def get_rule_run(run_id: str) -> dict | None:
    with _lock:
        row = _conn.execute("SELECT * FROM rule_runs WHERE id = ?",
                            (run_id,)).fetchone()
    return _run_to_dict(row) if row else None


def mark_run_undone(run_id: str) -> bool:
    """Flag a run as undone so it stops being the rule's latest baseline."""
    with _lock:
        cur = _conn.execute(
            "UPDATE rule_runs SET undone_at = ?"
            " WHERE id = ? AND undone_at IS NULL",
            (_now(), run_id),
        )
        _conn.commit()
    return cur.rowcount > 0

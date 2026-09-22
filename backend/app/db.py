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
        """
    )
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

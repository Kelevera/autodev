"""Thread-safe SQLite state store for autodev jobs and metrics."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'pending',
    type TEXT NOT NULL,
    target_file TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    branch_name TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    result TEXT,
    diff_summary TEXT
);
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    complexity REAL,
    coverage REAL,
    lines_of_code INTEGER,
    timestamp TEXT NOT NULL
);
"""

_JOB_FIELDS = {
    "status",
    "type",
    "target_file",
    "description",
    "branch_name",
    "completed_at",
    "result",
    "diff_summary",
}


def utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


class Store:
    """SQLite-backed store; every access is serialized through a lock."""

    def __init__(self, db_path: str | Path = "autodev.db") -> None:
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        with self._lock:
            self._conn.close()

    # -- jobs ---------------------------------------------------------------

    def create_job(
        self,
        job_type: str,
        target_file: str,
        description: str = "",
        branch_name: str | None = None,
    ) -> int:
        """Insert a pending job and return its id."""
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO jobs (status, type, target_file, description, branch_name,"
                " created_at) VALUES ('pending', ?, ?, ?, ?, ?)",
                (job_type, target_file, description, branch_name, utcnow()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def update_job(self, job_id: int, **fields: Any) -> None:
        """Update whitelisted columns of a job."""
        unknown = set(fields) - _JOB_FIELDS
        if unknown:
            raise ValueError(f"unknown job fields: {sorted(unknown)}")
        if not fields:
            return
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with self._lock:
            self._conn.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",
                (*fields.values(), job_id),
            )
            self._conn.commit()

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        """Return a single job as a dict, or None if it does not exist."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def get_pending_jobs(self) -> list[dict[str, Any]]:
        """Return pending jobs, oldest first (FIFO execution order)."""
        return self._select_jobs("status = 'pending'", order="id ASC")

    def get_completed_jobs(self) -> list[dict[str, Any]]:
        """Return completed jobs, newest first."""
        return self._select_jobs("status = 'completed'")

    def get_all_jobs(self) -> list[dict[str, Any]]:
        """Return every job, newest first."""
        return self._select_jobs("1 = 1")

    def has_open_job_for(self, target_file: str) -> bool:
        """True if a pending or running job already targets this file."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM jobs WHERE target_file = ? AND status IN ('pending', 'running')"
                " LIMIT 1",
                (target_file,),
            ).fetchone()
        return row is not None

    def _select_jobs(self, where: str, order: str = "id DESC") -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM jobs WHERE {where} ORDER BY {order}"
            ).fetchall()
        return [dict(row) for row in rows]

    # -- metrics ------------------------------------------------------------

    def store_metrics(
        self,
        file_path: str,
        complexity: float | None,
        coverage: float | None,
        lines_of_code: int,
    ) -> int:
        """Insert a metrics snapshot for a file and return its id."""
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO metrics (file_path, complexity, coverage, lines_of_code,"
                " timestamp) VALUES (?, ?, ?, ?, ?)",
                (file_path, complexity, coverage, lines_of_code, utcnow()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def get_metrics_history(self, file_path: str | None = None) -> list[dict[str, Any]]:
        """Return metric snapshots (optionally for one file), oldest first."""
        query = "SELECT * FROM metrics"
        params: tuple[Any, ...] = ()
        if file_path is not None:
            query += " WHERE file_path = ?"
            params = (file_path,)
        query += " ORDER BY id ASC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_latest_metrics_for_file(self, file_path: str) -> dict[str, Any] | None:
        """Return the most recent metrics snapshot for a file, if any."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM metrics WHERE file_path = ? ORDER BY id DESC LIMIT 1",
                (file_path,),
            ).fetchone()
        return dict(row) if row else None

    def get_latest_metrics(self) -> list[dict[str, Any]]:
        """Return the newest metrics snapshot per file, sorted by path."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT m.* FROM metrics m JOIN (SELECT file_path, MAX(id) AS max_id"
                " FROM metrics GROUP BY file_path) latest ON m.id = latest.max_id"
                " ORDER BY m.file_path"
            ).fetchall()
        return [dict(row) for row in rows]

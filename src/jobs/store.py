from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from agent_messaging.jobs.models import JobDefinition, JobRunSummary


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._initialize()

    def register_jobs(self, jobs: Iterable[JobDefinition]) -> None:
        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO jobs (job_id, agent_id, enabled, schedule_kind, schedule_expr, schedule_timezone, skill_id, source_path, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                  agent_id=excluded.agent_id,
                  enabled=excluded.enabled,
                  schedule_kind=excluded.schedule_kind,
                  schedule_expr=excluded.schedule_expr,
                  schedule_timezone=excluded.schedule_timezone,
                  skill_id=excluded.skill_id,
                  source_path=excluded.source_path,
                  updated_at=excluded.updated_at
                """,
                [
                    (
                        job.id,
                        job.agent_id,
                        1 if job.enabled else 0,
                        job.schedule.kind,
                        job.schedule.expr,
                        job.schedule.timezone,
                        job.skill_id,
                        str(job.source_path) if job.source_path else None,
                        _utc_now().isoformat(),
                    )
                    for job in jobs
                ],
            )
            conn.commit()

    def has_run_for_slot(self, job_id: str, scheduled_for: datetime) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM job_runs WHERE job_id = ? AND scheduled_for = ? LIMIT 1",
                (job_id, scheduled_for.isoformat()),
            ).fetchone()
            return row is not None

    def start_run(self, job_id: str, scheduled_for: datetime | None, trigger: str) -> JobRunSummary:
        started_at = _utc_now()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO job_runs (job_id, started_at, status, scheduled_for, trigger)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    started_at.isoformat(),
                    "running",
                    scheduled_for.isoformat() if scheduled_for else None,
                    trigger,
                ),
            )
            conn.commit()
            run_id = int(cursor.lastrowid)
        return JobRunSummary(
            job_id=job_id,
            run_id=run_id,
            status="running",
            started_at=started_at,
            finished_at=None,
            scheduled_for=scheduled_for,
        )

    def finish_run(self, run_id: int, *, status: str, message: str = "") -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE job_runs
                SET status = ?, finished_at = ?, message = ?
                WHERE run_id = ?
                """,
                (status, _utc_now().isoformat(), message, run_id),
            )
            conn.commit()

    def write_artifact(self, run_id: int, job_id: str, name: str, payload: object) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO job_artifacts (run_id, job_id, name, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, job_id, name, json.dumps(payload, ensure_ascii=False), _utc_now().isoformat()),
            )
            conn.commit()

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    schedule_kind TEXT NOT NULL,
                    schedule_expr TEXT NOT NULL,
                    schedule_timezone TEXT NOT NULL,
                    skill_id TEXT,
                    source_path TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    scheduled_for TEXT,
                    trigger TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS job_artifacts (
                    artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    job_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

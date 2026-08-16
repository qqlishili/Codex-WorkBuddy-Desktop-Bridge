from __future__ import annotations

import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from workbuddy_bridge.acp import WorkBuddyError
from workbuddy_bridge.config import config_dir


DEFAULT_BUSY_TIMEOUT_MS = 5_000
DEFAULT_REGISTRATION_WAIT_SECONDS = 5.0


__all__ = [
    "workbuddy_database_path",
    "wait_for_task_registration",
    "register_completed_session",
]


def workbuddy_database_path() -> Path:
    """返回当前 WorkBuddy profile 使用的桌面历史数据库。"""
    return config_dir() / "workbuddy.db"


def _current_user_id(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        """
        SELECT user_id
        FROM sessions
        WHERE user_id IS NOT NULL AND user_id <> ''
        ORDER BY updated_at DESC
        LIMIT 1
        """
    ).fetchone()
    return str(row[0]) if row else ""


def wait_for_task_registration(
    session_id: str,
    *,
    database_path: str | Path | None = None,
    timeout_seconds: float = DEFAULT_REGISTRATION_WAIT_SECONDS,
) -> bool:
    """等待 WorkBuddy 通过原生任务路径持久化 session。"""
    db_path = Path(database_path) if database_path else workbuddy_database_path()
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        try:
            with closing(sqlite3.connect(db_path, timeout=1.0)) as connection:
                row = connection.execute(
                    "SELECT is_playground, deleted_at FROM sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
            if row and int(row[0] or 0) == 1 and row[1] is None:
                return True
        except sqlite3.Error:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def register_completed_session(
    session_id: str,
    cwd: str,
    *,
    generated_title: str = "",
    database_path: str | Path | None = None,
    timestamp_ms: int | None = None,
) -> Path:
    """把 ACP 对话记录加入 WorkBuddy 任务历史，但不激活其窗口。

    DEPRECATED: 改用 bridge_registry.register_bridge_session 解耦 WorkBuddy SQLite schema。
    保留此函数仅为向后兼容；新代码应调用 register_bridge_session。
    """
    db_path = Path(database_path) if database_path else workbuddy_database_path()
    if not db_path.is_file():
        raise WorkBuddyError(f"WorkBuddy history database was not found: {db_path}")

    now = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
    canonical_cwd = str(Path(cwd).resolve())
    workbuddy_title = generated_title.strip() or None

    try:
        with closing(
            sqlite3.connect(db_path, timeout=DEFAULT_BUSY_TIMEOUT_MS / 1000)
        ) as connection:
            with connection:
                connection.execute(f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}")
                user_id = _current_user_id(connection)
                connection.execute(
                    """
                    INSERT INTO sessions (
                        id, cwd, user_id, title, custom_title, status,
                        created_at, updated_at, last_activity_at, deleted_at,
                        is_playground, source_mode, is_background_automation
                    ) VALUES (?, ?, ?, ?, NULL, 'completed', ?, ?, ?, NULL, 1, 'working', NULL)
                    ON CONFLICT(id) DO UPDATE SET
                        cwd = CASE
                            WHEN sessions.cwd IS NULL OR sessions.cwd = '' THEN excluded.cwd
                            ELSE sessions.cwd
                        END,
                        user_id = CASE
                            WHEN excluded.user_id <> '' THEN excluded.user_id
                            ELSE sessions.user_id
                        END,
                        title = COALESCE(sessions.title, excluded.title),
                        status = CASE
                            WHEN LOWER(sessions.status) = 'archived' THEN sessions.status
                            ELSE 'completed'
                        END,
                        updated_at = excluded.updated_at,
                        last_activity_at = excluded.last_activity_at,
                        deleted_at = NULL,
                        is_playground = 1,
                        is_background_automation = NULL
                    """,
                    (session_id, canonical_cwd, user_id, workbuddy_title, now, now, now),
                )
    except sqlite3.Error as exc:
        raise WorkBuddyError(f"Could not register WorkBuddy desktop history: {exc}") from exc
    return db_path

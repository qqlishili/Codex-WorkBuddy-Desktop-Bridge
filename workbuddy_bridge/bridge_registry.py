"""桥接器自己的 session registry，解耦 WorkBuddy SQLite schema。

不直接 INSERT WorkBuddy sessions 表（避免 schema 变化破坏桥接器）。
完成 session 登记到 config_dir/bridge-sessions.json。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from workbuddy_bridge.config import config_dir

REGISTRY_FILENAME = "bridge-sessions.json"
_REGISTRY_LOCK = threading.Lock()


def registry_path() -> Path:
    """返回 bridge-sessions.json 的绝对路径。"""
    return config_dir() / REGISTRY_FILENAME


def _load_registry_unlocked() -> dict[str, Any]:
    """读取现有 registry；不存在或损坏返回空骨架。"""
    path = registry_path()
    if not path.exists():
        return {"version": 1, "sessions": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "sessions": {}}
    if not isinstance(data, dict) or not isinstance(data.get("sessions"), dict):
        return {"version": 1, "sessions": {}}
    return data


def _write_registry_unlocked(data: dict[str, Any]) -> None:
    """原子写入 registry（.tmp + replace，与 review_sessions.py 一致）。"""
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def register_bridge_session(
    session_id: str,
    cwd: str,
    *,
    title: str = "",
    status: str = "completed",
    timestamp_ms: int | None = None,
) -> Path:
    """登记一个完成的 bridge session 到 bridge-sessions.json。

    Args:
        session_id: ACP session ID
        cwd: 任务工作目录绝对路径
        title: WorkBuddy 生成的会话标题（可为空）
        status: 任务状态（默认 "completed"）
        timestamp_ms: 时间戳（毫秒）；省略则用当前时间

    Returns:
        写入的 registry 文件路径
    """
    now = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
    canonical_cwd = str(Path(cwd).resolve())
    canonical_title = title.strip() or None

    with _REGISTRY_LOCK:
        data = _load_registry_unlocked()
        sessions = data["sessions"]
        existing = sessions.get(session_id)
        if existing:
            # 复用 created_at，只更新 changed 字段
            created_at = existing.get("created_at", now)
        else:
            created_at = now
        sessions[session_id] = {
            "cwd": canonical_cwd,
            "title": canonical_title,
            "status": status,
            "created_at": created_at,
            "updated_at": now,
        }
        _write_registry_unlocked(data)
    return registry_path()


def list_bridge_sessions() -> dict[str, Any]:
    """读取所有 bridge sessions（只读，用于测试和诊断）。"""
    with _REGISTRY_LOCK:
        data = _load_registry_unlocked()
    return data["sessions"]

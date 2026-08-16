"""公开的 ACP 工具函数（从 acp.py 提取，便于其他模块引用而不依赖 acp.py 内部实现）。"""
from __future__ import annotations

from typing import Any


def event_session_id(event: dict[str, Any]) -> str:
    """从 ACP 事件提取 sessionId（params.sessionId 或 params.session_id）。"""
    params = event.get("params") or {}
    if not isinstance(params, dict):
        return ""
    return str(params.get("sessionId") or params.get("session_id") or "")


def message_text(update: dict[str, Any]) -> str:
    """从 ACP agent_message_chunk / agent_message / assistant_message / message_chunk 提取文本。"""
    params = update.get("params") or {}
    body = params.get("update") if isinstance(params, dict) else None
    if not isinstance(body, dict):
        body = params if isinstance(params, dict) else {}
    kind = str(body.get("sessionUpdate", body.get("type", ""))).lower()
    if "agent_message" not in kind and kind not in {"assistant_message", "message_chunk"}:
        return ""
    content = body.get("content")
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        return content["text"]
    if isinstance(body.get("text"), str):
        return body["text"]
    return ""


def session_title(events: list[dict[str, Any]]) -> str:
    """从 events 中找 WorkBuddy 生成的最终 session 标题（session_info_update 事件）。"""
    for event in reversed(events):
        params = event.get("params") or {}
        update = params.get("update") if isinstance(params, dict) else None
        if not isinstance(update, dict):
            continue
        if update.get("sessionUpdate") != "session_info_update":
            continue
        title = update.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    return ""


__all__ = ["event_session_id", "message_text", "session_title"]
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from workbuddy_bridge.acp import WorkBuddyError
from workbuddy_bridge.acp_utils import (
    event_session_id,
    message_text,
    session_title,
)


EventCallback = Callable[[dict[str, Any]], None]


__all__ = [
    "EventCallback",
    "SessionEventChannel",
    "_session_end_reason",
    "_is_prompt_activity",
]


def _session_end_reason(event: dict[str, Any]) -> str:
    params = event.get("params") or {}
    update = params.get("update") if isinstance(params, dict) else None
    if not isinstance(update, dict) or update.get("sessionUpdate") != "session_end":
        return ""
    return str(update.get("stopReason") or "")


def _is_prompt_activity(event: dict[str, Any]) -> bool:
    params = event.get("params") or {}
    update = params.get("update") if isinstance(params, dict) else None
    if not isinstance(update, dict):
        return False
    return str(update.get("sessionUpdate") or "") in {
        "user_message_chunk",
        "agent_thought_chunk",
        "agent_message_chunk",
        "tool_call",
        "session_end",
    }


@dataclass
class SessionEventChannel:
    session_id: str
    event_callback: EventCallback | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""
    observer_error: str = ""
    condition: threading.Condition = field(default_factory=threading.Condition)

    def feed(self, event: dict[str, Any]) -> None:
        if event_session_id(event) != self.session_id:
            return
        callback = self.event_callback
        with self.condition:
            self.events.append(event)
            reason = _session_end_reason(event)
            if reason:
                self.stop_reason = reason
            self.condition.notify_all()
        if callback:
            callback(event)

    def fail(self, message: str) -> None:
        with self.condition:
            self.observer_error = message
            self.condition.notify_all()

    def wait_for_end(self, timeout_seconds: float) -> str:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        with self.condition:
            while not self.stop_reason and not self.observer_error:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.condition.wait(remaining)
            if self.observer_error:
                raise WorkBuddyError(self.observer_error)
            return self.stop_reason

    def wait_for_prompt_start(self, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        with self.condition:
            while not any(_is_prompt_activity(event) for event in self.events):
                if self.observer_error:
                    raise WorkBuddyError(self.observer_error)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self.condition.wait(remaining)
            return True

    def wait_for_title(self, timeout_seconds: float = 2.0) -> str:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        with self.condition:
            while True:
                title = session_title(self.events)
                if title:
                    return title
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return ""
                self.condition.wait(remaining)

    def answer(self) -> str:
        with self.condition:
            events = list(self.events)
        return "".join(filter(None, (message_text(event) for event in events))).strip()


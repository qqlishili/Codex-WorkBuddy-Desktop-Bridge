from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from workbuddy_bridge.activity_log import ActivityLogger
from workbuddy_bridge.acp import (
    AcpClient,
    WorkBuddyError,
    discover_desktop_server,
    kill_isolated_server,
    spawn_isolated_server,
    task_prompt,
)
from workbuddy_bridge.bridge_registry import register_bridge_session
from workbuddy_bridge.errors import ERROR_KEYS, err
from workbuddy_bridge.history import wait_for_task_registration
from workbuddy_bridge.identities import compose_identity_prompt, normalize_identity
from workbuddy_bridge.multiplexer import SessionEventChannel
from workbuddy_bridge.review_sessions import (
    REVIEW_IDENTITIES,
    DOC_REVIEW_IDENTITIES,
    ALL_REVIEW_IDENTITIES,
    bind_review_session,
    build_rereview_prompt,
    find_review_session,
    normalize_review_target,
    normalize_session_id,
    prepare_review_resume,
    target_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "work" / "workbuddy-logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

mcp = FastMCP(
    "workbuddy_worker",
    instructions="Delegate bounded tasks to the currently running WorkBuddy desktop agent.",
    log_level="WARNING",
)

__all__ = [
    "mcp",
    "TaskState",
    "TASKS",
    "TASKS_MAX_KEEP",
    "TASK_ACTIVE_TIMEOUT_SECONDS",
    "MAX_CONCURRENT_TASKS",
    "PROMPTTransport",
    "_dispatch_prompt",
    "_gc_tasks",
    "_public",
    "workbuddy_status",
    "workbuddy_start",
    "workbuddy_wait",
    "workbuddy_cancel",
    "workbuddy_list",
]


@dataclass
class TaskState:
    task_id: str
    prompt: str
    cwd: str
    identity: str = ""
    model: str = ""
    reasoning_effort: str = ""
    resume_session_id: str = ""
    review_target: str = ""
    resume_review: bool = False
    resumed: bool = False
    previous_sha256: str | None = None
    current_sha256: str | None = None
    state: str = "queued"
    session_id: str | None = None
    answer: str = ""
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    cancel_requested: bool = False
    client: AcpClient | None = None
    channel: SessionEventChannel | None = None
    # Condition 显式 RLock；workbuddy_wait 的 wait 与 _run 的 notify_all 共享此 lock。
    condition: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.RLock())
    )


TASKS: dict[str, TaskState] = {}
TASKS_MAX_KEEP = 64  # 保留最近 N 个 terminal state task；超出部分清理
TASK_ACTIVE_TIMEOUT_SECONDS = 3600  # active task 最长存活；超龄标记 failed 并清理
MAX_CONCURRENT_TASKS = 4  # workbuddy_status 报告的最大并发任务数；未来可改运行时探测（需 WorkBuddy API 支持）
TASKS_LOCK = threading.Lock()
PROMPT_DISPATCH_INTERVAL_SECONDS = 1.0
PROMPT_DISPATCH_LOCK = threading.Lock()  # 只保护 new_session/load_session 的 ACP Host 串行化
LAST_PROMPT_DISPATCH_AT = 0.0
_DISPATCH_THROTTLE_LOCK = threading.Lock()  # 保护节流逻辑（LAST_PROMPT_DISPATCH_AT 更新），不阻塞 session 创建
CONTINUATION_SESSION_LOCKS: dict[str, threading.Lock] = {}
CONTINUATION_SESSION_LOCKS_LOCK = threading.Lock()


@dataclass
class PromptTransport:
    done: threading.Event = field(default_factory=threading.Event)
    response: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str = ""
    thread: threading.Thread | None = None


def _dispatch_prompt(
    task: TaskState,
    client: AcpClient,
    event_callback: Any,
    prompt: str,
) -> PromptTransport:
    """在 PROMPT_DISPATCH_LOCK 下创建一个 ACP session，然后 configure、节流、
    等待 prompt 启动均在锁外执行，使并发任务互不阻塞。"""
    global LAST_PROMPT_DISPATCH_AT
    transport = PromptTransport()

    def send() -> None:
        try:
            response = client.prompt(
                prompt,
                session_id=task.session_id,
                event_callback=task.channel.feed,
            )
            transport.response = response
            transport.result = response["result"]
        except Exception as exc:
            transport.error = str(exc)
        finally:
            transport.done.set()

    # 1. 锁内：只保护 new_session/load_session（ACP Host 串行化）
    with PROMPT_DISPATCH_LOCK:
        if task.resume_session_id:
            task.session_id = client.load_session(
                task.resume_session_id,
                task.cwd,
            )
        else:
            task.session_id = client.new_session(task.cwd)

    # 2. 锁外：创建 channel（session_id 已确定）
    task.channel = SessionEventChannel(
        task.session_id,
        event_callback=event_callback,
    )

    # 3. 锁外：configure_session（session_id 已确定，无需串行化）
    client.configure_session(
        model=task.model,
        reasoning_effort=task.reasoning_effort,
        permission_mode="fullAccess",
        session_id=task.session_id,
    )

    # 4. 节流：相邻 prompt 间隔 ≥1 秒（单独锁，不阻塞其他任务的 session 创建）
    with _DISPATCH_THROTTLE_LOCK:
        now = time.monotonic()
        delay = PROMPT_DISPATCH_INTERVAL_SECONDS - (now - LAST_PROMPT_DISPATCH_AT)
        if delay > 0:
            time.sleep(delay)
        LAST_PROMPT_DISPATCH_AT = time.monotonic()

    # 5. 启动 prompt 发送线程
    task.state = "running"
    task.started_at = time.time()
    transport.thread = threading.Thread(
        target=send,
        name=f"workbuddy-prompt-{task.task_id}",
        daemon=True,
    )
    transport.thread.start()

    # 6. 锁外：等待 prompt 启动确认（不阻塞其他任务的 session 创建）
    if not task.channel.wait_for_prompt_start(15.0):
        raise WorkBuddyError(
            ERROR_KEYS["WorkBuddy启动prompt超时"].format(
                session_id=task.session_id
            )
        )
    return transport


def _public(task: TaskState) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "state": task.state,
        "session_id": task.session_id,
        "cwd": task.cwd,
        "identity": task.identity or None,
        "model": task.model or None,
        "reasoning_effort": task.reasoning_effort or None,
        "resumed": task.resumed,
        "review_target": task.review_target or None,
        "resume_review": task.resume_review,
        "previous_sha256": task.previous_sha256,
        "current_sha256": task.current_sha256,
        "answer": task.answer if task.state == "completed" else "",
        "result": task.result if task.state == "completed" else None,
        "error": task.error,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }


def _gc_tasks() -> int:
    """回收 terminal 状态且超龄的 task + 超龄 active task。线程安全。返回清理数。

    保留策略：
    - terminal（completed/failed/cancelled）：按 finished_at 倒序，保留前 TASKS_MAX_KEEP 个，其余删除。
    - active（queued/connecting/running/observing/cancelling）：created_at 超 TASK_ACTIVE_TIMEOUT_SECONDS 的
      标记 failed 并删除，避免 _run 线程异常退出导致的内存泄漏。
    """
    active_states = {"queued", "connecting", "running", "observing", "cancelling"}
    now = time.time()
    with TASKS_LOCK:
        # 1. 清理超龄 active task（_run 线程异常退出未设 state 的泄漏）
        stale_active = [
            tid
            for tid, t in TASKS.items()
            if t.state in active_states
            and now - t.created_at > TASK_ACTIVE_TIMEOUT_SECONDS
        ]
        for tid in stale_active:
            t = TASKS[tid]
            t.state = "failed"
            t.error = "任务超时清理"
            t.finished_at = now
            del TASKS[tid]
        # 2. 清理超龄 terminal task（保留前 TASKS_MAX_KEEP）
        terminal: list[tuple[str, float]] = []
        for tid, t in TASKS.items():
            if t.state in {"completed", "failed", "cancelled"}:
                finished = t.finished_at or 0.0
                terminal.append((tid, finished))
        terminal.sort(key=lambda item: item[1], reverse=True)
        evict = [tid for tid, _ in terminal[TASKS_MAX_KEEP:]]
        for tid in evict:
            del TASKS[tid]
        return len(stale_active) + len(evict)


def _run(task: TaskState, timeout_seconds: float) -> None:
    log_path = LOG_DIR / f"{task.task_id}.jsonl"
    activity_logger = ActivityLogger(log_path, task.cwd, task_id=task.task_id)

    def log_event(event: dict[str, Any]) -> None:
        activity_logger.feed(event)
        task.updated_at = time.time()

    client: AcpClient | None = None
    runtime = None
    continuation_session_lock: threading.Lock | None = None
    try:
        task.state = "connecting"
        activity_logger.record(
            {
                "activity": "任务已开始",
                "status": "connecting",
            }
        )
        prompt_body = compose_identity_prompt(task.identity, task.prompt)
        if task.resume_session_id:
            with CONTINUATION_SESSION_LOCKS_LOCK:
                continuation_session_lock = CONTINUATION_SESSION_LOCKS.setdefault(
                    task.resume_session_id,
                    threading.Lock(),
                )
            if not continuation_session_lock.acquire(blocking=False):
                raise WorkBuddyError(
                    f"旧会话 {task.resume_session_id} 正在执行另一轮续接任务"
                )
            task.resumed = True
            review_resume = prepare_review_resume(
                session_id=task.resume_session_id,
                identity=task.identity,
                cwd=task.cwd,
                target=task.review_target,
            )
            task.previous_sha256 = review_resume.previous_sha256
            task.current_sha256 = review_resume.current_sha256
            prompt_body = build_rereview_prompt(review_resume, task.prompt)
        elif task.review_target:
            task.current_sha256 = target_sha256(task.review_target)

        desktop = discover_desktop_server()
        runtime = spawn_isolated_server(
            desktop,
            task.cwd,
            model=task.model or "deepseek-v4-flash",
            session_id=task.resume_session_id,
        )
        client = AcpClient(runtime, timeout_seconds=timeout_seconds)
        client.connect()
        task.client = client
        transport = _dispatch_prompt(
            task,
            client,
            log_event,
            task_prompt(prompt_body, task.cwd),
        )
        deadline = time.monotonic() + timeout_seconds

        task.state = "observing"
        stop_reason = ""
        while time.monotonic() < deadline:
            stop_reason = task.channel.wait_for_end(
                min(0.25, max(0.0, deadline - time.monotonic()))
            )
            if stop_reason:
                break
            if transport.done.is_set():
                if transport.error:
                    raise WorkBuddyError(transport.error)
                transport_stop_reason = str(
                    (transport.result or {}).get("stopReason") or ""
                )
                if transport_stop_reason:
                    stop_reason = transport_stop_reason
                    break
        if not stop_reason:
            raise WorkBuddyError(
                ERROR_KEYS["WorkBuddy会话超时"].format(
                    session_id=task.session_id
                )
            )
        if stop_reason == "cancelled":
            task.state = "cancelled"
            task.error = ERROR_KEYS["WorkBuddy会话已取消"]
            return
        if stop_reason != "end_turn":
            raise WorkBuddyError(
                ERROR_KEYS["WorkBuddy会话异常结束"].format(
                    stop_reason=stop_reason
                )
            )

        transport.done.wait(5.0)
        task.result = transport.result or {"transportError": transport.error}
        transport_stop_reason = str((task.result or {}).get("stopReason") or "")
        task.result = {
            **(task.result or {}),
            "stopReason": stop_reason,
            "transportStopReason": transport_stop_reason or None,
            "transportError": transport.error or None,
        }

        title = task.channel.wait_for_title() or str(
            (transport.response or {}).get("title") or ""
        )
        if not wait_for_task_registration(task.session_id):
            register_bridge_session(
                task.session_id,
                task.cwd,
                title=title,
            )
        task.answer = task.channel.answer() or str(
            (transport.response or {}).get("answer") or ""
        )
        if task.review_target and task.identity in REVIEW_IDENTITIES:
            bind_review_session(
                session_id=task.session_id,
                identity=task.identity,
                cwd=task.cwd,
                target=task.review_target,
                baseline_sha256=task.current_sha256
                or target_sha256(task.review_target),
            )
        task.state = "completed"
    except Exception as exc:
        task.state = "failed"
        task.error = str(exc)
        # traceback 记到 activity log（不进 task.error，避免泄露内部细节给调用方）
        activity_logger.record(
            {
                "activity": "异常详情",
                "status": type(exc).__name__,
                "session_id": task.session_id,
                "detail": traceback.format_exc(),
            }
        )
        activity_logger.terminal(
            "任务执行失败",
            status=type(exc).__name__,
            session_id=task.session_id,
        )
    finally:
        if client:
            client.close()
        if runtime:
            try:
                kill_isolated_server(runtime)
            except Exception:
                pass
        if continuation_session_lock and continuation_session_lock.locked():
            continuation_session_lock.release()
        activity_logger.close()
        task.client = None
        task.channel = None
        task.updated_at = time.time()
        task.finished_at = task.updated_at
        with task.condition:
            task.condition.notify_all()
        _gc_tasks()


@mcp.tool()
def workbuddy_status(task_id: str = "") -> dict[str, Any]:
    """检查 WorkBuddy 桌面连通性，或查看某个已派发任务的状态。"""
    if task_id:
        with TASKS_LOCK:
            task = TASKS.get(task_id)
        if not task:
            return err("未知任务ID", task_id=task_id)
        return {"ok": True, **_public(task)}
    try:
        server = discover_desktop_server()
        return {
            "ok": True,
            "connected": True,
            "endpoint": server.acp_endpoint,
            "sidecar_pid": server.sidecar_pid,
            "host_session_id": server.session_host_id,
            "max_concurrent_tasks": MAX_CONCURRENT_TASKS,
            "event_routing": "isolated_runtime_per_task",
        }
    except Exception as exc:
        return {"ok": False, "connected": False, "error": str(exc)}


@mcp.tool()
def workbuddy_start(
    prompt: str,
    cwd: str = "",
    timeout_seconds: int = 300,
    model: str = "",
    reasoning_effort: str = "",
    identity: str = "",
    resume_session_id: str = "",
    review_target: str = "",
    resume_review: bool = False,
) -> dict[str, Any]:
    """排队一个任务，或复用某个已绑定的 S1/S2/S3 审查会话。"""
    working_dir = Path(cwd or Path.cwd()).resolve()
    if not working_dir.is_dir():
        return err("无效工作目录", path=str(working_dir))
    if not prompt.strip():
        return err("空提示词")
    try:
        canonical_identity = normalize_identity(identity)
        canonical_resume_session_id = (
            normalize_session_id(resume_session_id)
            if resume_session_id.strip()
            else ""
        )
        canonical_review_target = (
            normalize_review_target(review_target, str(working_dir))
            if review_target.strip()
            else ""
        )
        if resume_review and canonical_identity not in REVIEW_IDENTITIES:
            raise ValueError(f"resume_review 只能与 {', '.join(sorted(ALL_REVIEW_IDENTITIES))} 审查身份一起使用")
        if resume_review and not canonical_resume_session_id:
            if not canonical_review_target:
                raise ValueError("自动复审时必须提供 review_target（caller 未传入）")
            canonical_resume_session_id = find_review_session(
                canonical_identity,
                str(working_dir),
                canonical_review_target,
            )
    except ValueError as exc:
        return err("无效参数", message=str(exc))
    if canonical_resume_session_id:
        if canonical_identity not in REVIEW_IDENTITIES:
            return err(
                "审查会话不支持",
                identities=", ".join(sorted(REVIEW_IDENTITIES)),
            )
        if not canonical_review_target:
            return err("复审缺少审查目标")
    if canonical_review_target and canonical_identity not in ALL_REVIEW_IDENTITIES:
        return err(
            "审查目标身份不支持",
            identities=", ".join(sorted(ALL_REVIEW_IDENTITIES)),
        )
    if canonical_identity == "docs-reviewer" and not canonical_review_target.strip():
        return err("缺少审查目标")
    task_id = f"wb-{uuid.uuid4().hex[:12]}"
    task = TaskState(
        task_id=task_id,
        prompt=prompt,
        cwd=str(working_dir),
        identity=canonical_identity,
        model=model.strip(),
        reasoning_effort=reasoning_effort.strip(),
        resume_session_id=canonical_resume_session_id,
        review_target=canonical_review_target,
        resume_review=bool(
            canonical_resume_session_id
            and canonical_identity in REVIEW_IDENTITIES
        ),
    )
    with TASKS_LOCK:
        TASKS[task_id] = task
    thread = threading.Thread(target=_run, args=(task, float(timeout_seconds)), daemon=True)
    thread.start()
    return {
        "ok": True,
        "task_id": task_id,
        "state": task.state,
        "cwd": task.cwd,
        "identity": canonical_identity or None,
        "resume_session_id": task.resume_session_id or None,
        "review_target": task.review_target or None,
        "resume_review": task.resume_review,
        "model": task.model or None,
        "reasoning_effort": task.reasoning_effort or None,
    }


@mcp.tool()
def workbuddy_wait(task_id: str, timeout_seconds: int = 55) -> dict[str, Any]:
    """短暂等待 WorkBuddy 任务；超时返回当前状态。"""
    with TASKS_LOCK:
        task = TASKS.get(task_id)
    if not task:
        return err("未知任务ID", task_id=task_id)
    if task.state not in {"completed", "failed", "cancelled", "cancelling"}:
        with task.condition:
            task.condition.wait(timeout=max(0, min(timeout_seconds, 55)))
    return {"ok": True, **_public(task)}


@mcp.tool()
def workbuddy_cancel(task_id: str) -> dict[str, Any]:
    """请求取消一个正在运行的 WorkBuddy 任务。"""
    with TASKS_LOCK:
        task = TASKS.get(task_id)
    if not task:
        return err("未知任务ID", task_id=task_id)
    client = task.client
    if not client or not task.session_id:
        return err("任务不可取消")
    try:
        client.notify("session/cancel", {"sessionId": task.session_id})
        task.cancel_requested = True
        task.state = "cancelling"
        task.updated_at = time.time()
        return {"ok": True, **_public(task)}
    except WorkBuddyError as exc:
        return {"ok": False, "state": task.state, "error": str(exc)}


@mcp.tool()
def workbuddy_list() -> dict[str, Any]:
    """列出桥接器进程内已知的任务。"""
    with TASKS_LOCK:
        tasks = list(TASKS.values())
    return {"ok": True, "tasks": [_public(task) for task in tasks]}


if __name__ == "__main__":
    mcp.run(transport="stdio")

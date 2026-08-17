from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from workbuddy_bridge.server import TaskState, _dispatch_prompt


class DispatchPromptConcurrencyTests(unittest.TestCase):
    """验证 _dispatch_prompt 的 PROMPT_DISPATCH_LOCK 只保护 new_session/load_session，
    不阻塞并发任务的 session 创建。"""

    def test_second_session_creation_not_blocked_by_first_wait_for_prompt_start(
        self,
    ) -> None:
        """两个并发 _dispatch_prompt：第二个 new_session 不被第一个 wait_for_prompt_start 阻塞 15s。

        重构前：wait_for_prompt_start 在 PROMPT_DISPATCH_LOCK 内，第二个 new_session 要等 15s。
        重构后：wait_for_prompt_start 在锁外，第二个 new_session 立即调用。
        """
        new_session_times: list[float] = []
        new_session_lock = threading.Lock()
        session_counter = [0]

        def mock_new_session(cwd: str) -> str:
            with new_session_lock:
                session_counter[0] += 1
                new_session_times.append(time.monotonic())
                return f"session-{session_counter[0]}"

        mock_client = MagicMock()
        mock_client.new_session = mock_new_session
        mock_client.configure_session = MagicMock()
        mock_client.prompt = MagicMock(return_value={"result": {"stopReason": "end_turn"}})

        # 第一个 channel 的 wait_for_prompt_start 阻塞 3s 模拟慢启动
        # 如果锁内，第二个 new_session 要等 3s+；锁外则立即
        call_count = [0]

        def make_channel(session_id: str, event_callback=None) -> MagicMock:
            channel = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                # 第一个任务：wait_for_prompt_start 阻塞 3s
                channel.wait_for_prompt_start = MagicMock(side_effect=lambda t: time.sleep(3) or True)
            else:
                channel.wait_for_prompt_start = MagicMock(return_value=True)
            channel.feed = MagicMock()
            return channel

        task1 = TaskState(task_id="t1", prompt="p", cwd=".", identity="S1")
        task2 = TaskState(task_id="t2", prompt="p", cwd=".", identity="S1")

        barrier = threading.Barrier(2)
        results: list[str | None] = [None, None]

        def run_dispatch(task: TaskState, idx: int) -> None:
            try:
                barrier.wait(timeout=5)
            except threading.BrokenBarrierError:
                results[idx] = "barrier_broken"
                return
            try:
                _dispatch_prompt(task, mock_client, MagicMock(), "prompt")
                results[idx] = "ok"
            except Exception as exc:
                results[idx] = f"error: {exc}"

        with patch("workbuddy_bridge.server.SessionEventChannel", make_channel):
            t1 = threading.Thread(target=run_dispatch, args=(task1, 0))
            t2 = threading.Thread(target=run_dispatch, args=(task2, 1))
            t1.start()
            t2.start()
            t1.join(timeout=30)
            t2.join(timeout=30)

        # 两个 new_session 都应被调用
        self.assertEqual(len(new_session_times), 2, f"Expected 2 new_session calls, got {len(new_session_times)}")
        # 两个 new_session 时间差应 < 2s（如果锁内阻塞 3s，差会 > 3s）
        time_diff = abs(new_session_times[1] - new_session_times[0])
        self.assertLess(
            time_diff,
            2.0,
            f"new_session calls {time_diff:.2f}s apart; expected <2s (wait_for_prompt_start should not block lock)",
        )
        # 两个任务都应成功
        self.assertEqual(results[0], "ok", f"task1 result: {results[0]}")
        self.assertEqual(results[1], "ok", f"task2 result: {results[1]}")


class GcTasksTests(unittest.TestCase):
    """验证 _gc_tasks 的驱逐边界：不误杀长任务，正确清理超龄泄漏。"""

    def tearDown(self) -> None:
        from workbuddy_bridge.server import TASKS, TASKS_LOCK

        with TASKS_LOCK:
            TASKS.clear()

    def test_does_not_evict_long_running_task(self) -> None:
        """timeout_seconds=7200 的 active 任务运行 1 小时（3600s），不应被驱逐（P1-6 回归）。"""
        from workbuddy_bridge.server import (
            TASKS,
            TASKS_LOCK,
            TASK_ACTIVE_TIMEOUT_SECONDS,
            _gc_tasks,
        )

        task = TaskState(task_id="long", prompt="p", cwd=".", timeout_seconds=7200.0)
        task.state = "running"
        task.created_at = time.time() - TASK_ACTIVE_TIMEOUT_SECONDS  # 运行恰好 3600s
        with TASKS_LOCK:
            TASKS["long"] = task
        _gc_tasks()
        with TASKS_LOCK:
            self.assertIn("long", TASKS, "长任务不应被 3600s 兜底误杀")

    def test_evicts_stale_active_task(self) -> None:
        """timeout_seconds=300 的 active 任务超龄（>3600+600），应被驱逐。"""
        from workbuddy_bridge.server import (
            TASKS,
            TASKS_LOCK,
            TASK_ACTIVE_GRACE_SECONDS,
            TASK_ACTIVE_TIMEOUT_SECONDS,
            _gc_tasks,
        )

        task = TaskState(task_id="stale", prompt="p", cwd=".", timeout_seconds=300.0)
        task.state = "running"
        task.created_at = time.time() - (
            TASK_ACTIVE_TIMEOUT_SECONDS + TASK_ACTIVE_GRACE_SECONDS + 1
        )
        with TASKS_LOCK:
            TASKS["stale"] = task
        _gc_tasks()
        with TASKS_LOCK:
            self.assertNotIn("stale", TASKS, "超龄 active 任务应被清理")


if __name__ == "__main__":
    unittest.main()

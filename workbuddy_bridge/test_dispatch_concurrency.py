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


if __name__ == "__main__":
    unittest.main()

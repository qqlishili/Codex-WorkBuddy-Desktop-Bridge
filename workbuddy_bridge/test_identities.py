from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from workbuddy_bridge.acp import DesktopServer
from workbuddy_bridge.identities import (
    IDENTITIES,
    compose_identity_prompt,
    normalize_identity,
)
from workbuddy_bridge.server import workbuddy_start


class IdentityTests(unittest.TestCase):
    def test_normalizes_supported_identity_aliases(self) -> None:
        self.assertEqual(normalize_identity("online_search"), "online-search")
        self.assertEqual(normalize_identity("s1"), "S1")
        self.assertEqual(normalize_identity("S2"), "S2")
        self.assertEqual(normalize_identity(" s3 "), "S3")
        self.assertEqual(normalize_identity("env-intel"), "env-intel")
        self.assertEqual(normalize_identity("s0"), "env-intel")
        self.assertEqual(normalize_identity("env_intel"), "env-intel")
        self.assertEqual(normalize_identity("docs-reviewer"), "docs-reviewer")
        self.assertEqual(normalize_identity("docs_reviewer"), "docs-reviewer")
        self.assertEqual(normalize_identity("doc-reviewer"), "docs-reviewer")
        self.assertEqual(normalize_identity("doc_reviewer"), "docs-reviewer")
        self.assertEqual(normalize_identity("文档审查员"), "docs-reviewer")

    def test_rejects_unknown_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "identity 必须是以下之一"):
            normalize_identity("reviewer")

    def test_composes_registered_identity_with_task_once(self) -> None:
        task = "检查 requirements.txt 的依赖风险。"
        prompt = compose_identity_prompt("S2", task)

        self.assertEqual(prompt.count(IDENTITIES["S2"]), 1)
        self.assertEqual(prompt.count(task), 1)
        self.assertTrue(prompt.endswith(task))

    def test_empty_identity_preserves_legacy_prompt(self) -> None:
        self.assertEqual(compose_identity_prompt("", "legacy task"), "legacy task")

    def test_start_rejects_unknown_identity_without_dispatching(self) -> None:
        self.assertEqual(
            workbuddy_start("task", identity="reviewer"),
            {
                "ok": False,
                "错误码": "无效参数",
                "error": "参数无效: identity 必须是以下之一: online-search, S1, S2, S3, env-intel, docs-reviewer",
            },
        )

    def test_start_rejects_docs_reviewer_without_review_target(self) -> None:
        result = workbuddy_start("task", identity="docs-reviewer")
        self.assertFalse(result["ok"])
        self.assertEqual(result["错误码"], "缺少审查目标")
        self.assertEqual(
            result["error"], "缺少审查目标（caller 未传入 review_target）"
        )

    def test_start_with_mock_does_not_dispatch_real_task(self) -> None:
        """mock spawn_isolated_server 后 workbuddy_start 返回 task_id 且 mock 被调用（隔离生效）。"""
        import time
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_server = DesktopServer(
                "http://127.0.0.1:1/api/v1/acp", "", "host", "pipe", 1
            )
            with (
                patch(
                    "workbuddy_bridge.server.discover_desktop_server",
                    return_value=fake_server,
                ) as mock_discover,
                patch(
                    "workbuddy_bridge.server.spawn_isolated_server",
                    return_value=fake_server,
                ) as mock_spawn,
                patch(
                    "workbuddy_bridge.server.wait_for_task_registration",
                    return_value=False,
                ),
                patch(
                    "workbuddy_bridge.bridge_registry.register_bridge_session",
                    return_value=None,
                ),
            ):
                result = workbuddy_start("task", cwd=tmpdir)
                self.assertTrue(result["ok"], f"workbuddy_start should succeed, got {result}")
                self.assertIn("task_id", result)
                # _run 线程异步跑，等 0.2s 让 mock 被调用
                time.sleep(0.2)
                # mock 被调用（隔离生效，未真派发到 WorkBuddy）
                mock_discover.assert_called_once()
                mock_spawn.assert_called_once()


if __name__ == "__main__":
    unittest.main()

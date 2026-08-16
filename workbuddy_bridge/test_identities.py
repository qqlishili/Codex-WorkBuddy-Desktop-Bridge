from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()

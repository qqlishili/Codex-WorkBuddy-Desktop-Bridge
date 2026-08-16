from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workbuddy_bridge.bridge_registry import (
    list_bridge_sessions,
    register_bridge_session,
    registry_path,
)


class BridgeRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.profile = Path(self.temporary.name)
        self.environment = patch.dict(
            os.environ,
            {"WORKBUDDY_CONFIG_DIR": str(self.profile)},
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    def test_registers_new_session_to_json(self) -> None:
        register_bridge_session(
            "session-1",
            "/project",
            title="Test title",
            timestamp_ms=1234,
        )

        data = json.loads(registry_path().read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        session = data["sessions"]["session-1"]
        self.assertEqual(session["cwd"], str(Path("/project").resolve()))
        self.assertEqual(session["title"], "Test title")
        self.assertEqual(session["status"], "completed")
        self.assertEqual(session["created_at"], 1234)
        self.assertEqual(session["updated_at"], 1234)

    def test_updates_existing_session_preserves_created_at(self) -> None:
        register_bridge_session("s1", "/p", title="first", timestamp_ms=1000)
        register_bridge_session("s1", "/p", title="second", timestamp_ms=2000)

        sessions = list_bridge_sessions()
        self.assertEqual(sessions["s1"]["title"], "second")
        self.assertEqual(sessions["s1"]["created_at"], 1000)
        self.assertEqual(sessions["s1"]["updated_at"], 2000)

    def test_empty_title_stored_as_none(self) -> None:
        register_bridge_session("s1", "/p", title="  ", timestamp_ms=1000)

        sessions = list_bridge_sessions()
        self.assertIsNone(sessions["s1"]["title"])

    def test_custom_status(self) -> None:
        register_bridge_session("s1", "/p", status="failed", timestamp_ms=1000)

        sessions = list_bridge_sessions()
        self.assertEqual(sessions["s1"]["status"], "failed")

    def test_list_bridge_sessions_returns_empty_when_no_registry(self) -> None:
        self.assertEqual(list_bridge_sessions(), {})

    def test_corrupt_registry_recovered_to_empty(self) -> None:
        registry_path().parent.mkdir(parents=True, exist_ok=True)
        registry_path().write_text("not json {{{", encoding="utf-8")

        sessions = list_bridge_sessions()
        self.assertEqual(sessions, {})

    def test_concurrent_writes_do_not_corrupt(self) -> None:
        """并发写两个不同 session，registry 不损坏。"""
        import threading

        def write(session_id: str) -> None:
            register_bridge_session(session_id, "/p", timestamp_ms=1000)

        threads = [
            threading.Thread(target=write, args=(f"s{i}",))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        sessions = list_bridge_sessions()
        self.assertEqual(len(sessions), 5)
        # registry 文件应是合法 JSON
        json.loads(registry_path().read_text(encoding="utf-8"))

    def test_evicts_oldest_sessions_beyond_capacity(self) -> None:
        """写入超过 REGISTRY_MAX_KEEP 个 session，最旧的被淘汰。"""
        from workbuddy_bridge.bridge_registry import REGISTRY_MAX_KEEP

        for i in range(REGISTRY_MAX_KEEP + 3):
            register_bridge_session(f"s{i}", "/p", timestamp_ms=i)

        sessions = list_bridge_sessions()
        self.assertEqual(len(sessions), REGISTRY_MAX_KEEP)
        # 最旧的 s0/s1/s2（updated_at 最小）被淘汰；最新的保留
        self.assertNotIn("s0", sessions)
        self.assertNotIn("s1", sessions)
        self.assertNotIn("s2", sessions)
        self.assertIn(f"s{REGISTRY_MAX_KEEP + 2}", sessions)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import re
import unittest

from workbuddy_bridge.errors import ERROR_KEYS, err


class ErrorsTest(unittest.TestCase):
    def test_err_schema(self) -> None:
        """err() 返 3 字段结构：ok=False, 错误码=str, error=str"""
        r = err("空提示词")
        self.assertEqual(r, {
            "ok": False,
            "错误码": "空提示词",
            "error": "prompt 不能为空",
        })

    def test_err_with_placeholder(self) -> None:
        """err() 模板替换占位符"""
        r = err("无效工作目录", path="/foo")
        self.assertEqual(r["error"], "cwd 不是有效目录: /foo")
        self.assertEqual(r["错误码"], "无效工作目录")

    def test_err_without_detail(self) -> None:
        """err() 不传 detail 走 else 分支"""
        r = err("空提示词")
        self.assertEqual(r["error"], "prompt 不能为空")

    def test_err_unknown_key(self) -> None:
        """err() 错误码不在 ERROR_KEYS 时，模板 = key 本身"""
        r = err("nonexistent_key_xyz")
        self.assertEqual(r["错误码"], "nonexistent_key_xyz")
        self.assertEqual(r["error"], "nonexistent_key_xyz")

    def test_err_extra_detail_appended_to_message(self) -> None:
        """err() 传 template 未声明的占位符 → 追加到 message 末尾（容错，不报错）"""
        r = err("空提示词", extra="unexpected_field")
        self.assertFalse(r["ok"])
        self.assertEqual(r["错误码"], "空提示词")
        self.assertIn("extra=unexpected_field", r["error"])

    def test_all_error_keys_have_chinese_messages(self) -> None:
        """全契约中文化：17 ERROR_KEYS 全部含中文字符"""
        chinese_pattern = re.compile(r"[\u4e00-\u9fff]")
        for key, msg in ERROR_KEYS.items():
            with self.subTest(key=key):
                self.assertTrue(
                    chinese_pattern.search(msg),
                    f"错误码 {key!r} 的 message 不含中文字符: {msg!r}"
                )

    def test_all_error_keys_return_three_field_schema(self) -> None:
        """17 ERROR_KEYS 全部按 err() 调用返 3 字段"""
        for key in ERROR_KEYS:
            with self.subTest(key=key):
                r = err(key)
                self.assertEqual(set(r.keys()), {"ok", "错误码", "error"})
                self.assertFalse(r["ok"])
                self.assertEqual(r["错误码"], key)
                self.assertIsInstance(r["error"], str)


if __name__ == "__main__":
    unittest.main()

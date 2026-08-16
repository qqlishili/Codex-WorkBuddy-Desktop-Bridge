"""统一错误码 + err() helper，全契约中文化。"""
from __future__ import annotations

from typing import Any

# 错误码（中文 key，保留原英文 key 完整语义）→ 人类可读中文消息（带可选 {placeholder}）
ERROR_KEYS: dict[str, str] = {
    "缺少审查目标": "缺少审查目标（caller 未传入 review_target）",
    "无效工作目录": "cwd 不是有效目录: {path}",
    "空提示词": "prompt 不能为空",
    "无效身份": "identity 必须是以下之一: {choices}",
    "无效参数": "参数无效: {message}",
    "ACP端点格式异常": "ACP 端点格式异常: {endpoint}",
    "WorkBuddy启动prompt超时": "WorkBuddy 未在 15 秒内启动 prompt (session: {session_id})",
    "WorkBuddy会话超时": "WorkBuddy session 等待超时 (session: {session_id})",
    "WorkBuddy会话已取消": "WorkBuddy 取消了 prompt",
    "WorkBuddy会话异常结束": "WorkBuddy session 异常结束 (stopReason: {stop_reason})",
    "任务不可取消": "任务当前不可取消",
    "无效复审身份": "resume_review 只能与 {identities} 审查身份一起使用",
    "缺少复审会话ID": "自动复审时必须提供 review_target（caller 未传入）",
    "审查会话不支持": "只有 {identities} 审查身份支持复用旧审查会话",
    "复审缺少审查目标": "复用旧审查会话时必须提供 review_target（caller 未传入）",
    "审查目标身份不支持": "review_target 只能与 {identities} 审查身份一起使用",
    "未知任务ID": "未知任务 ID: {task_id}",
}


def err(key: str, **detail: Any) -> dict[str, Any]:
    """统一错误返回：{ok: False, 错误码: key, error: 人类可读信息}。

    Args:
        key: 错误码（ERROR_KEYS 的中文 key）
        **detail: 用于填充 {placeholder} 的字段

    Returns:
        {ok: False, 错误码: str, error: str} 三字段结构

    容错逻辑：detail 传了 template 未声明的占位符时，追加到 message 末尾而非报错。
    """
    template = ERROR_KEYS.get(key, key)
    try:
        message = template.format(**detail) if detail else template
    except (KeyError, IndexError):
        # placeholder 缺失 → 降级为追加 detail
        message = template
    if detail and "{" in template and "}" in template:
        pass  # 已 format
    elif detail:
        message = f"{message}（{', '.join(f'{k}={v}' for k, v in detail.items())}）"
    return {"ok": False, "错误码": key, "error": message}


__all__ = ["ERROR_KEYS", "err"]

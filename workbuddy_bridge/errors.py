"""统一错误码 + err() helper，全契约中文化。"""
from __future__ import annotations

from typing import Any

# 错误码 → 人类可读中文消息（带可选 {placeholder}）
ERROR_KEYS: dict[str, str] = {
    "missing_review_target": "缺少审查目标（caller 未传入 review_target）",
    "invalid_cwd": "cwd 不是有效目录: {path}",
    "empty_prompt": "prompt 不能为空",
    "invalid_identity": "identity 必须是以下之一: {choices}",
    "invalid_argument": "参数无效: {message}",
    "acp_endpoint_malformed": "ACP 端点格式异常: {endpoint}",
    "workbuddy_prompt_start_timeout": "WorkBuddy 未在 15 秒内启动 prompt (session: {session_id})",
    "workbuddy_session_timeout": "WorkBuddy session 等待超时 (session: {session_id})",
    "workbuddy_session_cancelled": "WorkBuddy 取消了 prompt",
    "workbuddy_session_abnormal_end": "WorkBuddy session 异常结束 (stopReason: {stop_reason})",
    "task_not_cancellable": "任务当前不可取消",
    "invalid_resume_review_identity": "resume_review 只能与 {identities} 审查身份一起使用",
    "missing_resume_session_id": "自动复审时必须提供 review_target（caller 未传入）",
    "review_session_unsupported": "只有 {identities} 审查身份支持复用旧审查会话",
    "missing_review_target_for_resume": "复用旧审查会话时必须提供 review_target（caller 未传入）",
    "review_target_unsupported_identity": "review_target 只能与 {identities} 审查身份一起使用",
}


def err(key: str, **detail: Any) -> dict[str, Any]:
    """统一错误返回：{ok: False, 错误码: key, error: 人类可读信息}。

    Args:
        key: 错误码（ERROR_KEYS 的 key）
        **detail: 用于填充 {placeholder} 的字段

    Returns:
        {ok: False, 错误码: str, error: str} 三字段结构
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

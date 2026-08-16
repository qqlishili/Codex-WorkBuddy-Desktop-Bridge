"""统一 config_dir 解析（DRY）。

acp.py / history.py / review_sessions.py / bridge_registry.py 复用此函数，
避免四处重复 fallback 逻辑。
"""
from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    """解析 WorkBuddy 配置根目录。

    Fallback 顺序：
    1. $WORKBUDDY_CONFIG_DIR
    2. $CODEBUDDY_CONFIG_DIR
    3. ~/.workbuddy

    Returns:
        配置根目录绝对路径
    """
    return Path(
        os.environ.get("WORKBUDDY_CONFIG_DIR")
        or os.environ.get("CODEBUDDY_CONFIG_DIR")
        or Path.home() / ".workbuddy"
    ).expanduser().resolve()


__all__ = ["config_dir"]

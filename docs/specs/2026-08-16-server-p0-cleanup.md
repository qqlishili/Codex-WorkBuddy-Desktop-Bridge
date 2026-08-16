# server.py P0 修复：TASKS 内存清理 + 错误全契约中文化

## Problem Statement

server.py:78 `TASKS: dict[str, TaskState] = {}` 永久 append 无清理机制；实测 88 个 log 意味着 88 个 TaskState 对象常驻。daemon 长期运行 → OOM 风险。

同时 commit 7 后仍有 7+ 处英文错误消息残留（LRN 全契约中文化违反）：
- server.py:152-154 / 260-271 / 371 / 373
- identities.py:209
- acp.py:45

二阶后果：进程 OOM kill → 桥全停；caller 调试中英混用错误信息；与 LRN 一致性差。

## Solution

1. **TASKS 内存清理**：`TASKS_MAX_KEEP = 64` + `_gc_tasks()` 在 `_run` finally 末尾调用
2. **错误全契约中文化**：新增 `errors.py` 统一错误码 + `err()` helper；全 module 错误消息中文化

## Implementation Decisions

1. `TASKS_MAX_KEEP = 64`（保留最近 terminal task；超出清理）
2. `_gc_tasks()` 线程安全（在 `TASKS_LOCK` 内）
3. 新增 `workbuddy_bridge/errors.py` 模块独立（与 server.py 解耦）
4. `err(key, **detail)` 返回 `{ok: False, 错误码: key, error: human_message}` 三字段结构
5. `ERROR_KEYS` 字典统一所有错误码 → 中文消息映射
6. 替换 server.py / identities.py / acp.py 7+ 处英文错误

## Testing Decisions

- 单元测试：TASKS_MAX_KEEP 边界（创建 100 task → 调 _gc_tasks → 长度 ≤ 64）
- 单元测试：active task（state=running/observing）不被清理
- 单元测试：cancelling 状态不被清理
- 单元测试：err() 输出 schema 稳定
- 直接 Python 测试：grep 验证无英文错误消息残留

## Out of Scope

- 不动 P1 类型枚举化（StrEnum）/ P2 模块拆分
- 不重构 acp.py 主体（仅修 1 处错误消息）
- 不动 activity_log / multiplexer / history

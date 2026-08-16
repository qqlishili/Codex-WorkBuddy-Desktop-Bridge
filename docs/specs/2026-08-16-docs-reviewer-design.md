# docs-reviewer 角色设计规格说明书

## Problem Statement

WorkBuddy Bridge 仓库当前 routing skill 只暴露 4 个固定身份（`online-search` / `S1` / `S2` / `S3`）以及已在实施中但未在 routing 层暴露的 `env-intel`，缺乏一个专门审查设计文档与实施计划的身份。
当调用方通过 `workbuddy-agent-routing` skill 路由调用审查任务时，期望能在不改盘的前提下，按对抗式审查方法论（第一性原理、逆向证伪、奥卡姆、二阶思维、安全边际）输出一份系统化审查报告，自动识别问题清单并标注 P0/P1/P2 等级与置信度。
现有的 S1/S2/S3 三身份仅处理代码（语法 / 依赖安全 / 规范），文档类内容无对应通道。用户当前工作流是手工评审 spec / design / implementation plan，缺少结构化对抗式审查自动化入口。

## Solution

新增 `docs-reviewer` 身份作为 WorkBuddy Bridge identity 系统中的文档审查组件：
- 在 `workbuddy_bridge/identities.py` 注册，含 5 个 alias
- 通过 `workbuddy_start(identity="docs-reviewer", ...)` 调用，必须传 review_target 绝对文档路径
- 仅分析验证，严禁修改或实现
- 输出一份以 `## 审查状态：已收敛/需补充数据` 起头的 Markdown 结构化报告，含分级 ✅/🟡/🔴/⚠️ 与 P0/P1/P2 标签

## User Stories

1. 作为 routing skill 调用方，我想通过 routing skill 调用 `docs-reviewer` 审查 to-spec 输出的 spec 文档，以便在计划落地前获得结构化发现清单与二阶后果注释
2. 作为 routing skill 调用方，我想通过 routing skill 调用 `docs-reviewer` 审查 brainstorming 输出的 design 文档，以便在写 implementation plan 前对设计做对抗式审查
3. 作为 routing skill 调用方，我想通过 routing skill 调用 `docs-reviewer` 审查实施计划，以便将每条决策按 6 段审查范围做根因深挖
4. 作为 review target 文档的 reviewer，当 caller 未传 review_target 路径时，我期望立刻收到 `"缺少审查目标"` 错误，不进入审查
5. 作为审查消费者，我期望报告以 `## 审查状态：已收敛/需补充数据` 起头，便于一眼看到收敛状态
6. 作为审查消费者，我期望报告对每个发现项标注 P0/P1/P2 等级、置信度、影响面、回退方案
7. 作为审查消费者，我期望 docs-reviewer 不修改 review_target 文档本身（仅分析验证）
8. 作为审查消费者，当剩余潜在问题风险等级均低于 P2 且无新高置信反例时，我期望 reviewer 立即停止扩散（避免过度扩张清单）
9. 作为审查消费者，我期望 reviewer 区分已验证事实（✅）+ 高置信推断（🟡）+ 低置信假设（🔴）+ 暂无法验证（⚠️）
10. 作为审查消费者，当无 P0/P1 且设计符合核心约束时，我期望 reviewer 明确给出"未发现致命缺陷，方案在当前约束下具备可行性"
11. 作为 WorkBuddy MCP 调用方，我想用 5 种 alias（`docs-reviewer` / `docs_reviewer` / `doc-reviewer` / `doc_reviewer` / `文档审查员`）都能命中同一身份
12. 作为审查消费者，跨项目调用 docs-reviewer 也是合法的（不限 WorkBuddy 桥仓库）

## Implementation Decisions

1. 身份注册：在 `workbuddy_bridge/identities.py` 注册 `IDENTITIES["docs-reviewer"]`，prompt 文本以 v3 final 版落地（完整文本不内联进 spec 以避免过期；详见 identities.py 注册值）
2. 5 个 alias：`docs-reviewer` / `docs_reviewer` / `doc-reviewer` / `doc_reviewer` / `文档审查员`，全部在 `_IDENTITY_ALIASES` 注册，case-insensitive via `value.lower()`
3. 调用契约：`workbuddy_start(identity="docs-reviewer", ...)` 必须传 review_target 绝对路径；缺失返 `{"ok": false, "错误码": "缺少审查目标（caller 未传入 review_target）"}`，不进入审查
4. 审查路径范围：跨项目允许，由 caller 决定；不限定 WorkBuddy 桥仓库
5. 审查方法论：第一性原理 / 逆向证伪 / 奥卡姆 / 二阶思维 / 安全边际 五维一体
6. 审查范围 6 段：全景扫描 / 根因深挖 / 数据证伪 / 问题清单 / 全局评估 / 收敛与终止
7. 收敛终止 4 类：停止扩散 / 避免重复 / 总结陈词 / 熵增极限
8. 输出：Markdown 结构化报告，以 `## 审查状态：已收敛/需补充数据` 起头
9. 结论分级 4 类：✅已验证事实 / 🟡高置信推断 / 🔴低置信假设 / ⚠️暂无法验证
10. 等级标签 3 类：P0 / P1 / P2
11. 硬约束：只读 / 不写盘 / 不自调用 mcp__workbuddy__*（除非 caller 显式 cascade）/ 每次审查独立不累积状态
12. 工具：Read（review_target + 关联源码）/ Grep / Bash 只读；MCP 按需挑选 codegraph / codebase memory / serena / workbuddy
13. routing 路由白名单：commit 2 同步加 docs-reviewer 到 canonical SKILL.md `identity=` 枚举 + Routing rules 一行
14. canonical `references/identities.md` 末尾追加 `## docs-reviewer` 段
15. 桥仓库 git tracked 副本同步改（commit 2 一并）

## Testing Decisions

测试模块：`workbuddy_bridge/test_identities.py`

断言清单：
- `normalize_identity("docs-reviewer")` → `"docs-reviewer"`
- `normalize_identity("docs_reviewer")` → `"docs-reviewer"`
- `normalize_identity("doc-reviewer")` → `"docs-reviewer"`
- `normalize_identity("doc_reviewer")` → `"docs-reviewer"`
- `normalize_identity("文档审查员")` → `"docs-reviewer"`
- 既有 L43 断言 `"identity must be one of: online-search, S1, S2, S3, env-intel"` 改为 `"identity must be one of: online-search, S1, S2, S3, env-intel, docs-reviewer"`

测试方法：纯 unit test（不依赖实际 MCP / 实际文档文件存在）。仅校验 identity 命名空间与 alias 解析正确性，符合既有测试（`test_normalizes_supported_identity_aliases` / `test_rejects_unknown_identity` / `test_composes_registered_identity_with_task_once`）。

## Out of Scope

- 不修改 review_target 文档本身
- 不自动修改任何文件（仅分析验证）
- 不替代 S1/S2/S3（仅处理 review_target 文档 + 内嵌代码片段；S1/S2/S3 处理独立 .py/.ts 文件）
- 不替代 env-intel（仅审查设计文档/实施计划；env-intel 探测 WorkBuddy 运行时）
- 不做配置管理（MCP 缺哪个 server 由 caller 决定）
- 不做 token 或 quota 控制
- 不做 prompt 版本控制（IDENTITIES prompt 是 immutable 文本，调优通过修改 `identities.py` 重启桥）

## Further Notes

- docs-reviewer 的 prompt 字符串是 immutable 文本，调优只能通过修改 `workbuddy_bridge/identities.py` 重启桥
- Skill 副本实测：实际可达修改点 = 3 处（canonical + 2 symlink + 桥仓库副本）；修改主源 1 处足够（2 symlink 自动跟随）
- docs 落点：本 spec 自身落在 `D:/Temp/Codex-WorkBuddy-Desktop-Bridge/docs/specs/2026-08-16-docs-reviewer-design.md`（按 Q4.3 不嵌套 superpowers）

---

## spec 自检

- [x] 占位符扫描：无 TODO / 待定 / 未完成章节
- [x] 内部一致性：问题 vs 解决方案 vs 决策 三段对齐
- [x] 范围检查：本 spec 聚焦 docs-reviewer 角色本身，不溢出到 S1/S2/S3
- [x] 模糊性检查：每条决策已明确，无歧义可两解之处

## 用户审查关卡

本 spec 已由用户授权 OK，进入下一阶段（to-tickets 切 3 tranche）。
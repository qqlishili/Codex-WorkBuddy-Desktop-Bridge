# server.py docs-reviewer 调用契约修复规格说明书

## Problem Statement

docs-reviewer 已在 identities / SKILL.md / README / spec 落地。但 server 模块的 workbuddy_start 拒绝 docs-reviewer 使用 review_target（错误信息误导为"只能与 S1、S2、S3 使用"），且不传 review_target 时静默派发——spec 承诺的"调用契约缺路径即失败"在 MCP 层不可达。

二阶后果：所有 docs-reviewer 调用走 routing skill 都会被拒或静默派发，docs-reviewer 角色"半完成"。

## Solution

在 review_sessions 模块引入 DOC_REVIEW_IDENTITIES（与现有 REVIEW_IDENTITIES 并列），让 server 模块的 workbuddy_start 对 docs-reviewer 单独校验 review_target 必传。保持 S1/S2/S3 的 review-session 子系统不变（避免误触续审 / bind 语义）。

## User Stories

1. 作为 routing skill 调用方，我想按 docs-reviewer 调用 + 传 review_target=<绝对文档路径>，不被 server 拒，能进 worker
2. 作为 routing skill 调用方，我想 docs-reviewer 不传 review_target 立即收到"缺少审查目标"错误码，不静默派发
3. 作为 docs-reviewer worker，我想 server 把 review_target 通过 prompt 注入 worker（即使不触发续审 binding），便于审查
4. 作为 S1/S2/S3 调用方，我想现有 review-session 续审 + bind 行为不变（不被 docs-reviewer 改动污染）
5. 作为 test 开发者，我想加一条断言"docs-reviewer 不传 review_target 必报 缺少审查目标"
6. 作为运维，我想 workbuddy_wait 在 task 进入 cancelling 状态时也能 notify 返回（避免 caller 阻塞）

## Implementation Decisions

1. review_sessions 模块：新增 DOC_REVIEW_IDENTITIES 集合（仅含 docs-reviewer）；新增 ALL_REVIEW_IDENTITIES = REVIEW_IDENTITIES | DOC_REVIEW_IDENTITIES
2. server 模块 workbuddy_start：review_target 校验改用 ALL_REVIEW_IDENTITIES（动态列 4 身份）
3. server 模块 workbuddy_start：新增 docs-reviewer 缺失 review_target 守卫（仅 docs-reviewer 适用，不影响 S1/S2/S3）
4. server 模块 workbuddy_start：现有 S1/S2/S3 续审 / bind 路径完全不变（REVIEW_IDENTITIES 保持 S1/S2/S3 不变）
5. 全契约中文化（error key / 字段 key / 状态枚举）：与 LRN 全契约中文化教训对齐
6. server 模块 workbuddy_wait：condition.wait 集合加入 cancelling 状态
7. server 模块 workbuddy_start 返回 dict：新增 identity 字段
8. 测试模块：新增 docs-reviewer 缺失 review_target 单元测试 + 中文化错误串断言

## Testing Decisions

- 单元测试：docs-reviewer 不传 review_target → 立即返"缺少审查目标"
- 单元测试：docs-reviewer 传 review_target → 不被 server 拒，能进 _run 阶段
- 回归：既有 S1/S2/S3 测试不变
- 集成测试：workbuddy_wait cancelling notify 行为

## Out of Scope

- 不重写 review_sessions 模块核心 binding 逻辑（仅新增 DOC_REVIEW_IDENTITIES）
- 不改 docs-reviewer prompt（spec v3 final 不动）
- 不重写 activity_log / history / multiplexer / acp 模块
- 不动 P2/P3 worker 报告里的 SKILL.md description / README 同步（独立 commit）
- 不改 spec iteration 2 的量化阈值 + 能力边界（独立 spec）

## Further Notes

- 来源：worker wb-d263a227fced 真实审查报告 P1-1
- 二阶后果：本次修后 docs-reviewer 角色在桥代码层完整可用；spec iteration 2（量化阈值）独立处理

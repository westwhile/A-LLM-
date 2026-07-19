---
title: Kimi 阶段 9 脱敏 Handoff 审核记录
date: 2026-07-19
status: pending_user_approval
---

# Kimi 阶段 9 脱敏 Handoff 审核记录

## 当前状态

脱敏包已在本地生成，但尚未发送给 Kimi 或其他第三方。只有 `tmp/kimi_handoff/handoff_manifest.json` 状态改为 `approved_once` 后，才允许执行一次 Kimi 任务。

## 授权对象

授权范围只能是 manifest 中列出的相对路径和对应 SHA-256。包内仅包含：

- 第一条看板垂直切片的任务书；
- 合成数据契约与虚构运行夹具；
- Kimi 可读/可写路径规则；
- manifest 和本审核记录不包含的本机执行信息。

明确排除：原仓库源码、真实研究指标、`outputs/**`、`data/**`、iFinD 数据、Git 历史、绝对路径、账号、令牌、Kimi 全局日志和现有用户修改。

本地审核摘要：

- payload：11 个文件，共 9,324 bytes；
- manifest SHA-256：`1f342ebac40457bd9e4054879fe59bc9a700817a279709d64dc352753e61b71d`；
- 凭据样式命中：0；
- 绝对路径命中：0；
- 当前基线元数据指纹重合：0；
- 与当前基线指标的精确字符串重合：0；
- 所有运行标识、日期和指标值均为显式 synthetic fixture。

## 拟执行方式

1. Kimi 的工作目录固定为脱敏包目录，不使用 `--add-dir`、MCP、网络搜索或外部 fetch。
2. 先执行一次交互式 `kimi --plan`，只允许读取脱敏包并输出 ADR/文件清单。
3. 用户审查方案后，再单独授权一次实现任务。
4. 实现阶段只允许写入 `AGENTS.md` 所列目录，并由 Codex 做前后哈希、路径、凭据和测试审计。

官方 Kimi Hooks 为 fail-open，因此不会把 Hook 当作唯一安全边界；核心边界是 Kimi 从未获得原仓库文件，只能看到这份脱敏副本。

## 一次性授权文本

审核 manifest 后，如同意，可回复：

> 我已审核 `tmp/kimi_handoff/handoff_manifest.json`，明确授权 Codex 仅在本次阶段 9 设计任务中，通过已登录的 Kimi Code CLI 发送 manifest 所列、SHA-256 一致的脱敏文件。禁止访问或发送清单外文件、父目录、绝对路径、真实研究数据、iFinD 数据、源码、凭据、日志和 Git 历史；禁止 `--add-dir`、MCP、网络搜索和外部 fetch。本次授权仅允许执行一次 `kimi --plan`，不包含代码实现授权，任务结束即失效。

实现阶段将在你审核 Kimi 方案后另行请求授权。

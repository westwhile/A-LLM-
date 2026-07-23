---
title: 阶段 4–6 Kimi CLI 监督记录
date: 2026-07-20
status: stopped_by_user_then_codex_implemented
---

# 阶段 4–6 Kimi CLI 监督记录

## 结论

Kimi CLI `0.27.0` 未产生任何可审查的阶段 4–6 源码或测试，因而没有 Kimi 补丁被同步到主仓库。私有脱敏包已在本地生成并完成清单核验，但安全审查阻止了向外部模型发送私有工程材料；随后在完全隔离、仅含通用公开规格的目录中尝试非交互 prompt、`--auto` 和 ACP，均未形成文件产物。用户之后明确改为由 Codex 直接实现，本报告仅留存 CLI 事实与边界。

## 数据边界

- 私有脱敏包：`tmp/kimi_stage46/`，105 个文件，5,302,137 bytes；manifest SHA-256 为 `45394bf9623185651e496e3cc53f9542213942c6324b918cbbccae781e92d82d`。
- 脱敏包排除了 `.git`、`outputs/**`、真实/原始数据、凭据、绝对路径、全局日志和缓存文件。
- 私有脱敏包没有发送给 Kimi；被实际发送的只有隔离目录内的通用公开模型规格。
- 公开任务 SHA-256：`c4ff6efe0afa30d7572415e97f416692bf0fd2ff35dd88a8f723e99713984d41`。
- Kalman prompt SHA-256：`c0fa59f1208511883e89c944e16e460192145e29f9c6667d5afd99fa551ff606`。

## 运行事实

1. 沙箱内普通 `-p` 因无法创建用户级 session 目录而失败：`EPERM: operation not permitted, mkdir ...\.kimi-code\sessions\...`。
2. 请求在沙箱外向 Kimi 发送私有脱敏包时，被安全审查拒绝；主仓库与脱敏包均未因此发生改动。
3. 隔离公开目录中的 design prompt 约 70 秒退出为成功，但 stdout 为空且没有文件变化，不能视为完成。
4. `--auto -c -p` 立即返回 `Cannot combine --prompt with --auto.`；说明 `--auto` 与 `--prompt` 同样不能组合。
5. 普通 `-c -p` 约 184 秒超时；通过 stdin 管道进入 `--auto` 约 182 秒超时，均没有文件。
6. 官方 ACP stdio 能完成初始化并进入 prompt；一次 60 秒诊断收到 5,072 个 session update，但没有 agent final、权限请求或文件写入，最终由监督端超时终止。
7. 没有使用 `--yolo`、MCP、外部搜索或 Hooks；Hooks 的 fail-open 行为不能作为访问控制，真实权限边界必须由外部目录/文件守卫实现。

## 处置规则

- “进程仍活着”“退出码为 0”或“有大量 session update”均不等于任务完成；必须同时验证最终消息、目标文件、diff、测试和前后哈希。
- `0.27.0` 下不要组合 `--plan` 与 `-p`，也不要组合 `--auto` 与 `-p`。
- 普通 prompt 遇到写权限问题时，只能在隔离目录重试一次 `--auto`；本轮已证实非 TTY 管道仍可能挂起，不得升级 `--yolo`。
- ACP 客户端必须显式拒绝 terminal、fetch、目录外路径和非白名单写入；ACP 初始化成功不代表模型会完成 prompt。
- Windows 下 Kimi 需要写用户级 session 目录，工作区可写并不足以保证 CLI 可用。

## 最终实施归属

阶段 4–6 的算法、集成和测试均由 Codex 在用户明确变更授权后直接完成。Kimi 运行没有贡献代码，也没有被列为实现作者或验证来源。

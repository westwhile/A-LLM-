---
title: Kimi CLI 能力核验报告
date: 2026-07-19
stage: 0A
status: partial_pass_stage46_stopped
---

# Kimi CLI 能力核验报告

## 结论

Kimi Code CLI 已安装、配置有效并可完成无项目数据的非交互结构化请求；冻结版本为 `0.27.0`。由于让第三方 CLI 读取私有仓库可能造成项目路径或内容外发，本次未获该数据外发授权，因此“读取仓库且不修改文件”仍未通过。该限制不影响本地 0A 门禁代码的实现，但阶段 0A 总门禁暂不能标记为全部通过。

## 本机核验记录

| 项目 | 结果 | 证据/说明 |
| --- | --- | --- |
| 可执行文件 | 通过 | `%USERPROFILE%\.kimi-code\bin\kimi.exe` |
| CLI 版本 | 通过 | `kimi --version` 返回 `0.27.0` |
| 配置检查 | 通过 | `kimi doctor`：`config.toml` 有效；`tui.toml` 不存在并使用内置默认值 |
| 登录与联网 | 通过 | 在不含项目文件的空目录执行固定无敏感提示，返回结构化结果且退出码为 `0` |
| 非交互模式 | 通过 | `kimi -p ... --output-format stream-json` 返回 JSONL |
| 仓库只读检查 | 未通过 | 安全审查阻止向第三方服务发送私有仓库信息；失败尝试前后仓库 SHA-256 快照无变化 |
| `--plan` + `--prompt` | 不兼容 | 当前版本返回 `Cannot combine --prompt with --plan.`，退出码 `1` |
| `--yolo` | 未使用 | 0A 明确禁止无人审查的自动授权 |
| MCP | 未使用 | 本阶段未登记或调用 MCP 服务器 |

安装方式无法仅从现有可执行文件可靠反推，故记录为“已安装，具体安装命令待用户补录”，不作猜测。

## Kimi 对 iFinD 探针的脱敏设计输入

Kimi 仅接收了同花顺官方公开端点和安全约束，没有读取仓库。其设计建议已纳入实现：固定官方 HTTPS 端点、默认 dry-run、真实请求双重显式确认、环境变量注入令牌、2 只股票/3 日/3 字段硬限制、不落盘原始响应、仅输出响应哈希和脱敏元数据。

## 当前门禁

- Kimi 安装、配置、登录、非交互和结构化输出：通过。
- Kimi 私有仓库读取：`blocked_pending_explicit_external_disclosure_approval`。
- Kimi 未修改仓库：通过哈希前后对比确认。
- 阶段 0A 总体状态：`partial_pass`，不得据此启动 iFinD 全量下载。

## 2026-07-20 阶段 4–6 补充核验

- `0.27.0` 除了不允许 `--plan` 与 `-p/--prompt` 组合，也不允许 `--auto` 与 `-p/--prompt` 组合；后者原文为 `Cannot combine --prompt with --auto.`。
- Windows 沙箱内普通 prompt 可能因用户级 `.kimi-code/sessions` 目录不可写而直接报 `EPERM`；工作目录可写不能替代该权限。
- 普通 prompt 和 stdin `--auto` 均出现超过 180 秒无文件产出的情况；退出码、存活状态与 session update 数量都不能代替文件/diff/测试验收。
- ACP stdio 初始化可用，但本轮 60 秒内收到 5,072 个 update 后仍无 final、权限请求和文件；必须设置监督端超时并核验文件哈希。
- Hooks 本轮未启用。其 fail-open 特性不能承担安全边界；目录隔离、白名单读写和外部权限处理器才是强制边界。
- 没有使用 `--yolo`、MCP 或外部搜索。Kimi 未生成阶段 4–6 代码；用户随后明确改由 Codex 直接实施。

详细逐轮事实见 `reports/kimi_stage46_supervision.md` 与 `reports/kimi_stage46_runs.csv`。

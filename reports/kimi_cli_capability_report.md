---
title: Kimi CLI 能力核验报告
date: 2026-07-19
stage: 0A
status: partial_pass
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

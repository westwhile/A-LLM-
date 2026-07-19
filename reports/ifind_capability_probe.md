---
title: 同花顺 iFinD 最小能力探针报告
date: 2026-07-19
stage: 0A
status: blocked_missing_access_token
---

# 同花顺 iFinD 最小能力探针报告

## 结论

已实现并离线验证安全的 HTTP 最小探针，但本机未发现 `iFinDPy` 或 iFinD HTTP 凭据，因此未发送真实商业数据请求。当前证据只证明“探针可运行且不会在默认模式下联网或泄漏凭据”，不证明账号权限、历史深度、字段可用性或 PIT 合格性。

阶段门禁状态为 `blocked_missing_access_token`，不得启动 iFinD 全量下载。

## 探针范围

| 项目 | 固定范围 |
| --- | --- |
| 端点 | `POST https://quantapi.51ifind.com/api/v1/cmd_history_quotation` |
| SDK 对应函数 | `THS_HQ` |
| 股票 | `300033.SZ`、`600030.SH` |
| 日期 | `2024-01-02` 至 `2024-01-04` |
| 字段 | `open`、`close`、`volume` |
| 复权/缺失 | `CPS=1` 不复权、`Fill=Omit` |
| 输出 | 脱敏 manifest；不保存原始响应 |

日期与股票仅用于最小能力验证，不构成研究样本或策略输入。

## 安全门禁

- 默认 dry-run，未显式 `--execute` 时不联网并返回非零门禁退出码。
- 真实请求还必须显式传入 `--acknowledge-authorized-use`。
- access token 只读取 `IFIND_ACCESS_TOKEN` 环境变量。
- 端点固定为同花顺官方 HTTPS 地址，禁用重定向并启用 TLS 证书验证。
- 代码硬限制 2 只 A 股、2–3 个日历日和 1–3 个允许行情字段。
- 响应上限 2 MiB；只记录 HTTP/业务错误码、数据量、结构键、响应大小与 SHA-256，不落盘行情原文。
- 单元测试验证令牌和模拟行情值不会进入 manifest。

## 当前证据

- `config/ifind_field_mapping.example.yaml`：固定探针范围；财务、历史成分和公告 ID 保持为空，必须从账号可见的 SuperCommand 获取，未作猜测。
- `ifind_probe_manifest.json`：本机 dry-run 结果。
- `data_source_gap_matrix.csv`：字段级来源决策与阻断状态。
- `tests/test_ifind_gate.py`：范围限制、凭据脱敏和不落盘原始数据测试。

## 验证结果

- 0A 定向测试：`4 passed`。
- 项目完整测试：Python 3.12 临时环境中 `71 passed, 2 warnings`；两条 warning 来自既有分组测试中的常数序列相关系数计算，与本次门禁改动无关。
- 编译检查：新增模块、脚本和测试均通过 `compileall`。
- 凭据模式扫描：新增 0A 文件未发现令牌、密码或常见密钥字面量。

## 后续真实验收

账号授权确认后先运行一次 HTTP 最小探针。只有 `gate_status=passed_minimum_http_probe` 才能证明该端点的当前账号最小访问成功；财务、历史成分和公告时间仍需分别补充账号可见指标/报表 ID 和最小 PIT 探针，不能由行情探针替代。

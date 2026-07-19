---
title: 同花顺 iFinD 授权与权限核验清单
date: 2026-07-19
stage: 0A
status: blocked_pending_account_evidence
---

# 同花顺 iFinD 授权与权限核验清单

## 当前只读预检

| 检查项 | 当前证据 | 状态 |
| --- | --- | --- |
| iFinD Python SDK (`iFinDPy`) | 项目可用的 Python 3.12 环境未发现模块 | 未配置 |
| HTTP access token | 未发现 `IFIND_ACCESS_TOKEN` 环境变量；未读取任何令牌值 | 未配置 |
| SDK 账号/密码 | 未发现 `IFIND_USERNAME` / `IFIND_PASSWORD` 环境变量；未读取任何凭据值 | 未配置 |
| Windows 安装项 | 注册表未发现 iFinD/数据接口安装项 | 未发现 |
| 同花顺快捷方式 | 仅发现普通“同花顺”客户端快捷方式，不能证明具备 iFinD 数据接口权限 | 证据不足 |
| 真实最小请求 | 因无 SDK/HTTP 凭据而未发送 | 阻断 |

普通同花顺网站或客户端账号不等同于 iFinD 数据接口账号。当前没有证据确认账号类型、历史深度、字段范围或数据使用许可。

## 需由账号持有人确认

- [ ] 已购买或获准试用的是 iFinD **数据接口**账号。
- [ ] 账号类型：免费 / 试用 / 正式（选择一项并保留合同或账号页证据）。
- [ ] A 股历史行情、复权、财务、历史成分、ST、停牌、涨跌停、公告和 EDB 各自的起始日期与字段权限已确认。
- [ ] 单次、每周、QPS 和账号总并发限制已确认。
- [ ] 本地缓存、研究使用、图表展示和衍生结果导出的授权范围已确认。
- [ ] SDK 单设备互斥或 HTTP IP 绑定限制已确认。
- [ ] 凭据由环境变量、操作系统凭据库或密码管理器注入，不进入仓库、日志、截图或 Kimi 会话。

同花顺官方文档说明：免费、试用和正式账号权限与历史年限不同；HTTP 使用 refresh/access token；SDK 同时仅支持一台设备登录；单函数 QPS 通常为 10、EDB 为 5、账号总限制为 20。实际账号限制仍以账号页、合同和 SuperCommand 为准。

## 阻断与解锁条件

当前状态：`blocked_by_missing_interface_credentials_and_license_evidence`。

解锁真实探针前必须同时满足：

1. 账号持有人完成以上授权清单；
2. 通过安全方式向当前进程注入 `IFIND_ACCESS_TOKEN`；
3. 运行者明确传入 `--execute --acknowledge-authorized-use`；
4. 仅执行配置中的 2 只股票、3 日、3 字段探针。

凭据注入后使用：

```powershell
$env:PYTHONPATH = 'src'
& '<可用的 python.exe>' scripts/probe_ifind.py `
  --config config/ifind_field_mapping.example.yaml `
  --output ifind_probe_manifest.json `
  --execute `
  --acknowledge-authorized-use
Remove-Item Env:IFIND_ACCESS_TOKEN -ErrorAction SilentlyContinue
```

不要把令牌写进该命令、PowerShell 历史、配置文件或 Markdown。

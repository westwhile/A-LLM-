# 数据源审查：financial_indicator（财务指标与修订链）

- 审查日期：2026-07-19
- 审查人：Kimi（起草，待用户签署确认）
- 审查结论：**保持阻断**。开源渠道不提供公告日+完整修订链，必须由用户提供许可数据。这是 PIT 要求最高的表。

## 已做开源核验

- AkShare 财务类接口（`stock_financial_analysis_indicator` 等）只给报告期与最新值，无公告日期、无修订版本链；东财源在当前网络不可达。
- 用"最新值回填历史"被计划明确禁止（修订链必须保留）。

## 需要用户提供的表（schema 不得更改）

```text
ts_code, report_period, ann_date, usable_date, revision_date, revision_id, source_id,
roe, gross_margin, debt_ratio, revenue_yoy, profit_yoy
```

硬性口径（门禁逐行校验）：

- 同一 `ts_code + report_period + ann_date` 下 `revision_id` 唯一；
- `revision_date >= ann_date`；`usable_date` 严格晚于 `max(ann_date, revision_date)`，且必须是开市交易日（盘后公告默认下一交易日可用）；
- **保留全部历史修订版本**，禁止只保留最新修订值；首次公告与每次更正/重述各占一行；
- `source_id` 必填（公告编号或导出批次号，用于溯源）。

## 可接受来源（任选其一，附许可证据）

1. Tushare Pro `fina_indicator`（含 `ann_date`、`update_flag` 修订标记）
2. Wind 财务指标导出（含公告日期字段）+ 更正公告清单
3. iFinD 财务指标 + 公告日期/修订导出

## 字段定义要求

- `roe`、`gross_margin`、`debt_ratio`、`revenue_yoy`、`profit_yoy` 必须附供应商字段 ID 与计算口径（如 ROE 是否摊薄、毛利率是否含税金及附加），写入本文件后方可批准。

## 许可确认清单

- [ ] 允许本地缓存与多次导入
- [ ] 允许研究使用、衍生结果导出与图表展示
- [ ] 供应商对"修订历史"字段的说明页已存档

# 数据源审查：trade_calendar（交易日历）

- 审查日期：2026-07-19
- 审查人：Kimi（起草，待用户签署确认）
- 审查结论：建议批准 `approved_for_research`，`pit_ready: true`

## 来源与版本

- 提供者：AkShare 1.18.64（MIT 许可的开源数据库接口库）
- 接口：`ak.tool_trade_date_hist_sina`（新浪财经聚合的交易所交易日历）
- 抓取批次：`data/raw/real-20260719`（`fetch_manifest.json`，批次文件 SHA-256 见清单）
- 原始证据：`data/raw/real-20260719/trade_calendar.csv`；探针证据 `reports/data_sources/akshare_probe_20260719.json`

## 覆盖与字段

- 暂存表：`data/staging/real-20260719/trade_calendar.csv`
- 行数：3,048；区间：2014-01-02 → 2026-07-17（最后一个已完成交易日）
- 字段：`trade_date`（日期）、`is_open`（布尔，恒为 true——该接口只返回开市日）
- 处理说明：新浪发布未来日历至 2026-12-31，暂存时裁掉 113 个尚未开市的日历日，避免基准对齐审计对未来日期误报；裁剪记录见 `data/staging/real-20260719/assembly_manifest.json`

## 单位与口径

- `is_open`：布尔；日期为交易所自然日（北京时间）

## PIT 语义

- 交易日历为交易所事前发布的时间表，不含随时间修订的基本面数值，无未来函数风险。
- 历史部分（2014-01-02 起）覆盖协议要求的 2015-01-01 起点。

## 权限评估

- AkShare 为 MIT 许可；交易日历为交易所公开发布信息。本地缓存、研究使用、衍生结果导出与图表展示均无额外限制。不涉及账号、配额或私有授权。

## 已知限制

- 单一聚合源（新浪）。如未来发现与交易所公告日历不一致，以交易所公告为准并重新抓取。

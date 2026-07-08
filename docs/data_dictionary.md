# 数据字典

本文档定义阶段 0-5 主线 `A-LLM-` 使用的标准化表结构。所有真实数据 provider 输出必须先映射到这些字段，再进入因子、回测和报告模块。

## 统一约定

- 股票代码使用 `ts_code`，格式示例：`000001.SZ`、`600000.SH`。
- 日频面板主键默认是 `trade_date + ts_code`。
- 财务表必须保留 `ann_date` 和 `usable_date`，其中 `usable_date` 是公告日后的下一个交易日。
- 信号日、公告日、发布时间、执行日和收益结束日必须分开。
- AkShare 无法稳定提供的历史 PIT 表不能伪造为真实数据，应以本地标准表补齐或在数据质量报告中披露。

## 表清单

| 表 | 主键 | 时间字段 | 用途 |
|---|---|---|---|
| `trade_calendar` | `trade_date` | `trade_date` | 交易日对齐、下一交易日计算 |
| `stock_basic` | `ts_code` | `list_date`, `delist_date` | 新股、退市过滤和证券主数据 |
| `daily_bar` | `trade_date`, `ts_code` | `trade_date` | 量价因子、收益率、成交约束 |
| `daily_basic` | `trade_date`, `ts_code` | `trade_date` | 估值、规模、换手率、资金流 |
| `industry` | `trade_date`, `ts_code` | `trade_date` | 行业中性化和行业暴露 |
| `index_member` | `index_code`, `ts_code`, `in_date` | `in_date`, `out_date` | 历史股票池构造 |
| `financial_indicator` | `ts_code`, `report_period`, `ann_date` | `report_period`, `ann_date`, `usable_date` | 质量和成长因子 |
| `suspension` | `ts_code`, `suspend_date` | `suspend_date`, `resume_date` | 停牌过滤和成交约束 |
| `st_status` | `ts_code`, `start_date` | `start_date`, `end_date` | ST 风险警示过滤 |
| `limit_price` | `trade_date`, `ts_code` | `trade_date` | 涨跌停禁买禁卖约束 |
| `benchmark_index` | `trade_date`, `index_code` | `trade_date` | 基准收益和超额收益 |
| `news_event` | `stock_code`, `publish_date`, `event_type` | `publish_date` | LLM 事件标签和辅助解释 |

## 数据质量最低检查

- schema 必填字段完整。
- 主键唯一。
- 日频价格和复权因子为正，成交量/成交额非负。
- OHLC 不违反高低价边界。
- 财务 `usable_date` 晚于 `ann_date`。
- 真实模式下缺失核心标准表会在 `quality-check --mode real --fail-on-blocking` 中失败。

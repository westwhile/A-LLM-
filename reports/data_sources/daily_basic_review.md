# 数据源审查：daily_basic（每日估值与资金流）

- 审查日期：2026-07-19
- 审查人：Kimi（起草，待用户签署确认）
- 审查结论：**保持阻断**。开源渠道无法满足逐日粒度与覆盖率要求，必须由用户提供许可数据。

## 已做开源核验（2026-07-19 实况探针）

- `ak.stock_zh_valuation_baidu(600000, 市盈率(TTM), 全部)`：610 个观测点（1999-11 → 2026-07-18），约半月频，远低于逐日覆盖率 95% 的门禁要求。
- 百度总市值同样周频（731 点 / 10 年）。
- `ak.stock_individual_fund_flow(600000)`（东财资金流）：本机代理持续 ProxyError，不可作为稳定来源。
- 证据：`akshare_probe2_20260719.json`、`akshare_probe3_20260719.json`。

## 需要用户提供的表（schema 不得更改）

```text
trade_date, ts_code, pe_ttm, pb, total_mv, turnover_rate, net_mf_amount
```

- 粒度：每股票每交易日一行，与 daily_bar 键对齐（缺失率 >20% 即阻断）
- 单位：`total_mv`/`net_mf_amount` 人民币元；`turnover_rate` 比率（非百分数）
- 覆盖：2015-01-01 起的全部历史股票池成员（含退市股），估值须为当日收盘后可得值

## 可接受来源（任选其一，附许可证据）

1. Tushare Pro `daily_basic`（pe_ttm/pb/total_mv/turnover_rate）+ `moneyflow`（net_mf_amount），需相应积分权限
2. Wind `w.wsd` 日频估值与资金流序列导出
3. iFinD `THS_HQ`/`THS_BD` 日频估值序列导出

## 许可确认清单

- [ ] 允许本地缓存（约 11 年 × 全股票池）
- [ ] 允许研究使用与衍生结果导出
- [ ] 允许图表展示
- [ ] 字段单位与口径说明（尤其 turnover_rate 分母为流通股还是自由流通股）已记录

## 备注

资金流（net_mf_amount）为主动性买卖统计口径，各家供应商定义不同；登记表中必须写明所用口径来源页，否则保持阻断。

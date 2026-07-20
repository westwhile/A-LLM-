# 数据源审查：daily_bar（个股日行情 + 复权因子）

- 审查日期：2026-07-19
- 审查人：Kimi（起草，待用户签署确认）
- 审查结论：建议批准 `approved_for_research`，`pit_ready: true`（多源、口径已文档化）

## 来源与版本

- 提供者：AkShare 1.18.64
- 主用行情源：`ak.stock_zh_a_daily`（新浪财经日线）——1,190,706 行 / 499 只股票
- 退市股行情源：`ak.stock_zh_a_hist_tx`（腾讯财经日线）——472,433 行 / 254 只退市或长期停牌股票；该源只提供成交量（手），**不提供成交额**
- 未用源：`ak.stock_zh_a_hist`（东方财富）——2026-07-19 经本机代理持续不可达（ProxyError），抓取脚本已自动熔断；证据见 `bars_manifest.json`、`akshare_probe2/3_20260719.json`
- 复权因子：`ak.stock_zh_a_daily(adjust="qfq-factor")` 返回的是新浪前复权**除数** `qfq_factor_raw`；本项目按统一契约 ``adjusted_price = raw_price * adj_factor`` 派生 ``adj_factor = 1 / qfq_factor_raw``。抓取层显式保留 `qfq_factor_raw`，并拒绝零、负、非有限值。快照日期 2026-07-19
- 抓取批次：`data/raw/real-20260719/bars/*.csv`（每股一文件，含每股来源标记）+ `bars_manifest.json`

## 覆盖与字段

- 纠错暂存表：`data/staging/real-20260719-r1/daily_bar.parquet`；旧 `real-20260719` 暂存产物不得用于收益计算
- 行数：1,663,139；股票数：753；区间：2014-01-02 → 2026-07-17
- 抓取股票池 833 只 = 当前中证 500 成分快照（500，100% 成功）+ 沪深退市股（333，成功 253 + 停牌在市长 1）——**该股票池为侦察级，不构成历史成分 PIT 证据**；80 只早期退市股三个公开源均无数据，如实记录于 `bars_manifest.json`
- 字段：`trade_date, ts_code, open, high, low, close, volume, amount, adj_factor, price_adjustment`；新浪源额外保留 `outstanding_share, turnover`

## 单位与口径（已在抓取层统一）

- `volume`：股（腾讯/东财源由手×100 换算）；`amount`：人民币元（腾讯源无此字段，整列缺失）
- 单位一致性校验：`amount / (volume × close)` 的 p05/p50/p95 = 0.983 / 1.000 / 1.019，与"VWAP≈收盘价"一致，见 `assembly_manifest.json`
- `qfq_factor_raw`：新浪前复权除数快照（最新值=1.0），Sina 本地前复权价 = `close / qfq_factor_raw`
- `adj_factor = 1 / qfq_factor_raw`：项目统一乘数，满足 `close × adj_factor` 得前复权价；缺失率 0.08%（仅 689009.SH 九号公司 CDR 无新浪因子，已记录）
- `price_adjustment = raw_close_with_sina_qfq_divisor_snapshot`：明确标识快照语义
- 数值复核：`adj_factor*qfq_factor_raw` 最大绝对误差约 `1.11e-16`；逐股前复权收盘日收益绝对值超过 30% 的记录为 104 条（旧错误乘法口径为 884 条）。固定除权测试验证 `raw_price/qfq_factor_raw == raw_price*adj_factor`，不再发生双重调整。

## PIT 语义

- OHLCV/成交额为当日公开行情，不存在事后修订。
- 复权因子为**快照语义**：本次快照日为 2026-07-19；未来新除权会改变历史前复权因子，因此批次清单记录抓取日期与内容哈希，重跑需整批重取并重签。
- **用途限制**：`adj_factor` 仅保证收益率/比例类计算在快照日内一致；跨快照比较绝对价格水平（如 `close × adj_factor` 的数值）会随未来除权事件变化，不能当作可跨期直接相加的“真实历史价格”。

## 权限评估

- 公开行情数据经 MIT 许可的 AkShare 聚合；本地缓存、研究、衍生结果与图表展示无额外限制。未绕过任何频控：逐股串行、间隔 0.25 秒、失败有限重试。

## 已知限制

- 腾讯源 254 只股票缺成交额（缺失率 28.4%，门禁为 warning 级）；待东财网络恢复可重取升级。
- 80 只无数据退市股在幸存者审计中将如实显现为缺口，不得用推测值补齐。
- 停牌日无行（各源一致），停牌区间推导方案见 `suspension_review.md`。

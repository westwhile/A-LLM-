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

---

## 2026-08-11 附录：RESSET 补历史缺行情成员 783 只（主板 751 + 科创 32）

### 来源

- RESSET 股票·行情与分配（QTTNDIST）：`data/staging/real-pit-20260725/source/bars_missing/s*/*.csv`，751 只主板历史成员，2,088,383 行（2014-01-02 ~ 2026-06-30），主键零重复，751/751 全覆盖
- RESSET 科创板库·科创板日行情（STIBQTTN）：`source/bars_kcb/*.csv`，取 `bars_missing_kcb.txt` 清单 32 只，42,629 行（2019-07-22 起，止于 2026-07-03）
- RESSET 科创板复权因子事件表：`source/kcb_adjfactor.csv`（2,447 行事件；32 只中 28 只有事件）
- 与既有 753 只零重叠；合并后 1,536 只，中证500 历史池 1,356 只全覆盖

### 复权口径（两路，与既有批次快照日不同）

- **主板**：`adj_factor = AdjClPr2 ÷ ClPr`（RESSET 前复权价反推，数据止于 2026-06-30，导出快照约 2026-07 下旬）。**新增决策 D1**：按每股最后记录日归一为 1.0，与既有批次"最新=1.0"契约对齐；归一前 36 只偏差 ≤5.46%（窗口外 2026-07 除权事件所致），归一不改变收益率序列。标记 `price_adjustment = resset_qfq_ratio_snapshot_20260630`
- **科创**：`RaAdjFac` 为**累计**因子，每股事件乘子 = 相邻累计取比（首事件 1/ra_1），`adj_factor(t)=Π_{e>t} 乘子`，最新交易日=1.0。标记 `resset_raadjfac_cumprod_snapshot_20260703`
- 三个批次快照锚点互不相同（2026-07-19 / 2026-06-30 / 2026-07-03）：**仅收益率/比例在各自快照语义内一致，绝对价位不可跨批直接比较**（与上文"快照语义"用途限制一致）

### 数值验证（全部通过，证据 `derived/daily_bar_extension_stats.json`）

1. 每股 adj_factor 最新交易日=1.0：归一后最大偏差 0.0（两路）
2. 除权日连续性（adjusted 收益 == 交易所参考价收益）：主板 7,069 个事件日中位偏差 0.018%、p95 0.14%；科创 149 个事件日中位 2.0e-7、最大 8.0e-7
   - **离群留痕**：主板 40 个事件日（0.57%）偏差不收敛，均为破产重整转增不除权/配股类供应商因子口径特例（如 601777 2020-12-23、002251 2024-08-02、000980 2021-12-15），全部清单见统计 JSON `main_v2_outliers_gt_1pct`；供应商因子与交易所参考价在此类事件上语义不同，未做任何手工修补
3. 无双重调整：`close × (AdjClPr2/ClPr)` 与 AdjClPr2 最大相对误差 2.2e-16
4. 合并后主键（trade_date, ts_code）零重复；单位核验 amount/(volume×close) p05/p50/p95 = 0.983/1.000/1.018，与既有批次一致

### 缺口与留痕

- ClPr 缺失 225 行（主板，2014-04-16 ~ 2026-06-18，129 只股票各 1~3 行）：OHLC/成交额/ adj_factor 如实留空，行保留并计数；分布见统计 JSON
- 合并产物：`data/staging/real-pit-20260725/standard_input/daily_bar.parquet`，3,794,151 行 × 13 列（既有 753 只原样保留）

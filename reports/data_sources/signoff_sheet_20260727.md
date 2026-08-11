# 真实 PIT 许可、入库与冻结签署清单

> 本页由用户本人在审阅 `预检总报告_20260727.md` 与 7 份 `*_review.md` 后填写。

## A. 许可与入库授权（完整导入前）

- 目标数据批次：`data/staging/real-pit-20260725/`（RESSET 导出批次，2026-07-25 ~ 2026-07-27 导出）
- 数据覆盖期：2014-01-01 ~ 2026-07（财务表含 2014 前历史；行业/成分含更早期）
- 指数：`000905.SH`
- 研究起点：不晚于 `2015-01-01`
- 最终留出期起点：`2024-01-01`

本人已核对对应 `*_review.md`、许可摘要、字段口径、PIT 语义和预检结果，并逐表作出以下决定：

| 表 | 供应商/产品 | 版本/接口/批次 | 缓存 | 研究/回测 | 衍生输出 | 图表展示 | PIT 合格 | 决定 | 保留事项 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| daily_basic | RESSET 锐思 / 央财图书馆订阅 | 市盈率/日市值/日换手率/资金流向表 2026-07 导出 | [x] | [x] | [x] | [x] | [x] | 批准 | 689009 资金流缺失；规则 M1–M5 见 review |
| financial_indicator | RESSET 锐思 / 央财图书馆订阅 | FININD/FINRATIO/科创板会计指标 2026-07 导出 | [x] | [x] | [x] | [x] | [x] | 批准 | 11 只更早已退市公司无记录（0.8%）；规则 R1–R6 |
| index_member | RESSET 锐思 / 央财图书馆订阅 | IDXCOMPO + 指数成分股权重快照 2026-07 导出 | [x] | [x] | [x] | [x] | [x] | 批准 | 快照推导规则 v1（R1–R4）已审阅同意 |
| industry | RESSET 锐思 / 央财图书馆订阅 | INDHIS + 科创板行业变更历史 2026-07 导出 | [x] | [x] | [x] | [x] | [x] | 批准 | 689009 无行业记录；11 只早期退市股无记录 |
| limit_price | RESSET 锐思 / 央财图书馆订阅 | STKPRICELIMIT + 科创板涨跌停价 2026-07 导出 | [x] | [x] | [x] | [x] | [x] | 批准 | 无 |
| st_status | RESSET 锐思 / 央财图书馆订阅 | STKSPCTRMT 2026-07 导出 | [x] | [x] | [x] | [x] | [x] | 批准 | 区间拼合规则 S1–S5 已审阅同意 |
| suspension | RESSET 锐思 / 央财图书馆订阅 | SUSPNSNRESMPTN + 科创板停复牌 2026-07 导出 | [x] | [x] | [x] | [x] | [x] | 批准 | 规则 F1–F3、v2 已审阅同意 |

共同确认：

- [x] 我有权按上述范围使用这些数据，且项目不会再分发受限原始数据。
- [x] 我确认 7 张必需表全部选择"批准"后，才允许完整真实导入。
- [x] 我授权按已核对的证据更新 `config/data_source_registry.yaml` 的表级来源、版本、许可、PIT、单位和证据路径（即将各表 `license_status` 改为 `approved_for_research`、`pit_ready` 改为 `true`）。
- [x] 我授权将全局 `review_status` 设置为 `approved`，并使用下方本人提供的审查人和时间。
- [x] 我理解本签署只是许可与入库授权，不代表数据质量/PIT 专项审计已经通过。
- [x] 我承诺不根据 2024-01-01 以来最终留出期表现修改候选模型、参数网格或晋级门槛。

- 审查人（用户本人）：李伟嘉
- 审查时间（含时区）：2026-07-30 23:59 +08:00
- 签名或明确确认：确认
- 许可原件保存位置/编号（不得含凭据）：央财图书馆数据库订阅（在校学生教学科研使用），RESSET 版权说明 PDF 存于 `data/staging/real-pit-20260725/RESSET_版权说明_证据.pdf`

## C. 终审签署（导入与门禁通过后）

### C.1 门禁豁免确认（豁免决策已于 2026-08-11 签署批准，此处终审勾选确认）

- [x] 我确认豁免 financial_indicator.gross_margin 的金融类成员日（industry 表新申万一级行业名命中 银行/非银金融 等关键词判定；依据：金融类公司无营业成本概念，RESSET 毛利率留空属行业惯例）。实现位置：`monthly_research.py` `COVERAGE_EXEMPTION_FIELDS`；审计输出含逐日 `exempted_count` 列可审计。
- [x] 我确认豁免 daily_bar.amount 的 254 只无成交额股票成员日（识别规则：daily_bar 全部行 amount 均缺失；清单留痕 `data/staging/real-pit-20260725/derived/no_amount_stocks.txt`；依据：腾讯源退市股无成交额，`daily_bar_review.md` 已声明的已知限制）。
- [x] 我已审阅豁免量化影响与最终结果（`预检总报告_20260727.md` 第六节 + `reports/gate/real-pit-20260725-r2/field_coverage_probe.json`）：两豁免字段最终失败日数均为 **0/2,790 天**；豁免后 amount min 覆盖率 1.0、gross_margin min 覆盖率 0.98167；科创毛利率缺口已由 `financial_ratio_kcb.csv`（科创板主要财务分析指标）闭合。
- [x] 我理解上述豁免仅作用于指定字段的分母，逐日计数可审计，且为本批次一次性签署决策（写死、不可配置）。

### C.2 审计验收（批次 `data/standard/real-pit-20260725-r2`，门禁 `reports/gate/real-pit-20260725-r2/`）

| 验收项 | 结果/值 | 证据路径 | 用户核对 |
| --- | --- | --- | --- |
| import_gate_status | ready_for_quality_audit | `data/standard/real-pit-20260725-r2/data_manifest.json` | [x] |
| verify-data | verified=true，mismatches=[]（11 表内容哈希与 manifest 全对） | `tmp/verify_r2.out.txt` | [x] |
| blocking 质量问题数 | 0（27 条 warning 均为已签署声明的结构性缺口） | `reports/gate/real-pit-20260725-r2/data_quality_issues.csv` | [x] |
| PIT timing 全通过 | 548,524 行，0 失败 | `pit_timing_audit.csv` | [x] |
| 财务修订链全通过 | 248,078 行 | `financial_revision_audit.csv` | [x] |
| 存活偏差审计全通过 | 5,533 行 | `survivorship_audit.csv` | [x] |
| 历史成分最低覆盖率 | 2,790 天 0 失败（daily_bar min=1.0） | `universe_coverage.csv` | [x] |
| 基准对齐全通过 | 2,790 行 | `benchmark_alignment.csv` | [x] |
| 总门禁 status | **passed**（blocking_reasons=[]） | `data_gate_summary.json` | [x] |
| 月度标签/留出期隔离 | 118 标签、31 因子、gate_status=passed；标签全部早于 2024-01-01 留出期 | `outputs/monthly/real-pit-20260725-r2/monthly_sample_summary.json` | [x] |

冻结对象：

| 对象 | SHA-256 或数据版本 | 用户核对 |
| --- | --- | --- |
| `data_manifest.json`（r2） | `92375bdb14bdaab9b9ad8d36d80805de1caa29cc769a7db59f1422304692dc68` | [x] |
| 标准数据 `data_version`（r2） | `f73f1a150c81b31a702bba6e78cd90f08f0622c3de5a064f17e4c63102841ada` | [x] |
| `data_gate_summary.json`（r2） | `51587cf2e192ba557b5dc8209ed2be6f149e00c37c2821430021c5106c7226a3` | [x] |
| `config/data_source_registry.yaml` | `fb3ecfa919e23e1946d892fdd5f18619cd9cb65976a49503787fdb4eaf78d104` | [x] |
| `config/research_protocol.real.yaml` | `da35cf83397b610423679b55409af521d2ef5b1ce26e07869ebc616d8608a28a` | [x] |

- [x] 所有必需审计非空且全部通过，`data_gate_summary.status=passed`。
- [x] 本批次目录 `real-pit-20260725-r2` 是新建目录，未覆盖旧原始或标准批次。
- [x] 我批准冻结上述版本，供阶段 4–6 真实 OOS 研究使用。
- [x] 我理解任何数据、映射、登记表、协议或门槛变化都会使本冻结签署失效并要求重跑。

- 最终验收人（用户本人）：李伟嘉
- 验收时间（含时区）：2026-08-11 15:18 +08:00
- 签名或明确确认：确认（用户本人在会话中逐字确认，由 Kimi 按授权代录）
- 保留事项：已知缺口如实保留（689009 CDR 多字段缺失；11 只更早已退市公司无财务/行业记录；sp/cfp/large_order_mf_20 因子本批不可计算；2026-07 起 12 天留待下一增量批次）

## B. 登记表与协议哈希确认（完整导入前）

| 对象 | SHA-256 | 用户核对 |
| --- | --- | --- |
| `config/data_source_registry.yaml` | `fb3ecfa919e23e1946d892fdd5f18619cd9cb65976a49503787fdb4eaf78d104`（2026-08-11 重算：daily_bar 追加 RESSET 补源后记入） | [x] |
| `config/research_protocol.real.yaml` | `da35cf83397b610423679b55409af521d2ef5b1ce26e07869ebc616d8608a28a` | [x] |

- [x] 我确认上述哈希对应的登记表和协议正是我授权用于本批次导入的版本。
- 哈希确认人：李伟嘉
- 确认时间（含时区）：2026-08-11 11:36 +08:00
- 签名或明确确认：确认（用户本人在会话中逐节授权，由 Kimi 按授权原文代录）

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

---

## 2026-07-27 更新：用户提供 RESSET 许可数据（修订链完整，预检通过）

### 实际来源

- 提供方：RESSET 金融研究数据库（中央财经大学图书馆订阅）
- 表：FININD 财务指标（主板，`find2_*.csv` 含 CompanyCode 版，1,766,793 行）+ FINRATIO 财务比率（毛利率专用）+ 科创板主要会计指标 STIBMACCIND（进行中）
- 辅助表：SECUCDCHGINFO 证券代码变更信息（125,506 行，用于退市股挂回）

### 预检结果

- **公告日期（Infopubdt）零缺失**；公告日早于报告期仅 8 行（已标记）
- 披露结构清晰：每（公司, 报告期）按"披露批次（AdjFlg 0=当期/1=后期）× 口径（AdjType 累计 1/2 与单季 4/5/6/7/8）× 会计准则（1 新/9 旧）"展开——**修订链按披露批次排序即得**（`revision_id`=批次序号、`ann_date`=首批公告日、`revision_date`=本批公告日，天然满足 revision_date ≥ ann_date）
- 非空代码行在全键下零重复
- **退市股挂回**：FININD 对退市公司使用老三板代码（如泛海→400205），经 SECUCDCHGINFO 注册表（SecuCd → CompanyCode）挂回 **62/73**；映射存 `derived/delisted_companycode_map.json`
- **最终已知缺口（11/1356，0.8%）**：000418、000748、000780、002013、002143、600068、600260、600270、600317、600401、600636——均为更早已退市/被吸收合并公司，FININD 无其公司记录，不回填不编造；其会员期内基本面因子置 NaN，影响量化写入签署页
- 毛利率：金融类公司（银行/保险/券商）无营业成本概念，RESSET 口径留空，如实置 NaN；FINRATIO 衍生比率按 RESSET 计算口径（可能基于最新调整后报表，已在文档声明）

### 字段与计算规则 v1（待用户签署确认）

- **R1**：指标行取 `AdjType ∈ {1, 2}`（累计 YTD 口径）；单季口径（4/5/6/7/8）保留在源文件不导入
- **R2**：`revision_id` = 披露批次序号（按 Infopubdt 排序）；`ann_date` = 首批公告日；`revision_date` = 本批公告日；`usable_date` = max(ann_date, revision_date) 后首个开市交易日
- **R3**：`roe` 取 ROE（摊薄）；`debt_ratio` = Totlia ÷ Totass；`revenue_yoy`/`profit_yoy` 由累计营收/净利润按同披露版本同比计算；`gross_margin` 取 FINRATIO 销售毛利率（拼接键：公司+报告期+报表类型）
- **R4**：退市股经 `delisted_companycode_map.json` 挂回原代码；科创板由 STIBMACCIND 补充（是否调整 AdjFlg 与主板同语义）
- **R5**：`source_id` = `ID`（RESSET 行级唯一 ID）+ 导出批次目录名

# P0-C1：11 张标准表组装计划（只读规划，未实施）

- 计划日期：2026-08-09
- 编制：Kimi（quant-data-audit 能力域，只读）
- 授权范围：只读冻结现有原始与派生批次；完成 11 表的来源映射、字段映射、转换规则、输出目录与验收门禁**计划**。
- 本阶段未做：未写入 `data/standard`、未运行真实导入、未修改任何在途报告与数据文件、未访问最终留出期、未联网、未提交 Git。
- 上游依据：`signoff_sheet_20260727.md`（A/B 门禁已签署）、`真实PIT许可与人工签署执行指南.md`、7 份表级审查文件、`预检总报告_20260727.md`、`config/data_source_registry.yaml`（SHA-256 `9d6153ac…e04`）、`config/research_protocol.real.yaml`（SHA-256 `da35cf83…a28a`）。

## 1. 冻结基线（本阶段新增证据）

- 冻结清单：`reports/data_sources/staging_freeze_20260809.sha256`
- 范围：`data/staging/real-pit-20260725/` 全批次（含许可证据 PDF、source 全部分片、derived、zips）+ `data/staging/real-20260719-r1/`（4 张可复用表 + assembly_manifest.json）
- 规模：**306 个文件，6,091,134,911 字节（≈5.67 GiB）**，逐文件 SHA-256 与字节数
- 性质：只读计算，原批次零写入；后续任何文件变化都会与该清单失配，即触发重新签署

## 2. 11 表就绪度矩阵

| # | 标准表 | 来源 | 状态 |
|---|---|---|---|
| 1 | trade_calendar | `staging/real-20260719-r1/trade_calendar.csv`（3,048 行，2014-01-02~2026-07-17） | ✅ 只读复用 |
| 2 | stock_basic | `staging/real-20260719-r1/stock_basic.csv`（5,533 行含 333 退市） | ✅ 只读复用（2026-08-09 复核：1,356 成员 0 缺失） |
| 3 | benchmark_index | `staging/real-20260719-r1/benchmark_index.csv`（3,048 行，000905.SH 收盘） | ✅ 只读复用 |
| 4 | index_member | `real-pit-20260725/derived/index_member_derived.csv`（1,662 行） | 🔧 需确定性转换 |
| 5 | suspension | `source/suspension.csv`（81,535 行）+ `source/suspension_kcb.csv`（562 事件） | 🔧 需确定性转换 |
| 6 | st_status | `source/st_status.csv`（4,105 事件） | 🔧 需确定性转换 |
| 7 | limit_price | `source/limit_price/A_*`（11 包）+ `B_*`（14 包）+ `KCB_*`（1 包），合计 11,973,238 行 | 🔧 需确定性转换 |
| 8 | industry | `source/industry_history_raw.csv`（145,631 行）+ `source/industry_kcb.csv`（10,469 行） | 🔧 需确定性转换 |
| 9 | financial_indicator | `source/find*_RESSET_FININD_*`（8 分片）+ `frat_RESSET_FINRATIO_*`（2 分片）+ `financial_kcb(2).csv` + `code_change.csv` + `derived/delisted_companycode_map.json` | 🔧 需确定性转换（PIT 最高） |
| 10 | daily_basic | `source/pe/**`（40 分片）+ `mv/**`（37 分片）+ `turnover/**`（26 分片）+ `moneyflow/**`（84 分片 + 科创 6 分片）+ `valuation_kcb_*`（3 分片） | 🔧 需确定性转换（依赖 ⑨） |
| 11 | daily_bar | `staging/real-20260719-r1/daily_bar.parquet`（1,663,139 行 / **753 只**） | ⛔ **覆盖缺口，见第 3 节决策点 D1** |

## 3. 关键阻断发现（2026-08-09 只读复核确认）

### D1：daily_bar 历史成员覆盖缺口（C 门禁必然阻断）

用已冻结文件直接计算（成员集 = `index_member_derived.csv` 1,356 只）：

- 成员缺 `stock_basic`：**0 只** ✅
- 成员缺 `daily_bar`：**783 只（57.7%）**＝主板 751（`bars_missing_main.txt`）＋科创 32（`bars_missing_kcb.txt`），与批次内缺口清单完全一致
- 后果（对照 `pit_audit.py` 门禁逻辑）：
  - `survivorship_audit`：783 行 `historical_member_missing_daily_bar` → 阻断
  - `universe_coverage`：有 bars 成员仅 573/1,356（≈42%），远低于 `min-coverage 0.95` → 阻断
- 暂存区无任何 OHLCV 源（DMV/PERATIO/DTURNR 只有市值/收盘/换手率字段，无法重建开高低收+成交额+复权因子），**组装本身无法闭合该缺口**

可选路线（需用户书面选择，均不在本阶段执行）：

| 路线 | 内容 | 后果 |
|---|---|---|
| **A（推荐）** | 用户从 RESSET 补导日行情（优先全量 1,356 只，含 OHLC、成交量/额、复权因子字段） | 新数据按 7 表同样流程预检→审查→签署增补；若全量到位，daily_bar 整体替换为 RESSET 口径，复权语义统一，0719 旧 bars 留档不用；缺口 783 中约 80 只早期退市股 RESSET 大概率有覆盖，需导出后实测 |
| B | 任务级批准 akshare 联网重抓 783 只 | 违反 `daily_bar_review.md` 快照一致性约束（0719 快照日复权因子 vs 新抓快照日）→ 必须整批重取 1,356 只并**重签 B 门禁**；东财源本机代理曾持续不可达，风险高 |
| C | 缩小股票池到已有 bars 的 573 只 | 违反研究协议全历史股票池要求；`universe_coverage` 仍按全部在册成员审计，依旧阻断。**不可行，仅列出备查** |

### D2：科创板 turnover_rate 来源缺失（规则 M5 无法落地）

- 已核实：主板 RESSET 表（DMV/DTURNR/PERATIO 2026 分片）**均不含 688 代码**（grep 0 命中）；科创板估值表 STIBVALIDX 字段为 `ToMV/PETTM/PB/PBLF`，**无成交量、无流通股本**
- 规则 M5（科创换手率=成交量÷流通股本）在现有材料中没有输入
- 选项：
  - **a（推荐）**：随 D1 路线 A 一并补导科创板日行情（成交量）与流通股本口径字段
  - b：用户书面修订 M5 为"科创 turnover_rate 置 NaN 并登记已知缺口"——影响 103 只科创成员换手类因子；不影响 `universe_coverage`（该行仍存在，覆盖率按行存在性计）

### D3：无（保留编号）

（原计划的第三决策点在复核中已消解：`real-pit-20260726/` 为空目录脚手架，与本次组装无关，保持原样不动。）

## 4. 已核实的格式事实（转换规则的事实基础）

- 标准 `ts_code` 格式：`000001.SZ` / `600000.SH`（stock_basic、daily_bar、index_member_derived 三处一致）
- RESSET 主板表 `R_SecuCode` 前缀映射：`90_`→`.SZ`、`83_`→`.SH`（600000 浦发、600036 招商均为 `83_`，已抽样验证）
- `index_member_derived.csv` 的 `index_code` 为裸 `000905` → 转换时必须映射为 `000905.SH`（`universe_coverage` 按 `000905.SH` 精确匹配）
- `weight` 列全空（1,662/1,662）：按审查规则 R3 留空，导入触发 `missing_rate:weight` **warning 级**，解释文案预登记（见第 8 节）
- st_status、limit_price、pe/mv/turnover/moneyflow 的代码列为 6 位裸代码：后缀经 `stock_basic` 唯一挂接（A 股代码命名空间沪深不相交）；挂接失败行进异常清单，不静默丢弃
- 全部 RESSET 分片为 UTF-8 带引号 CSV；导入程序 `pd.read_csv` 默认读取，无需编码转换
- 导入程序契约（`import_standard.py` 实测）：source 目录内按 `<表名>.csv|.parquet` 精确文件名读取；real 模式校验登记表签署（已批准✓）；`financial_indicator` 走 4 列修订键唯一性 + `revision_date ≥ ann_date` + `usable_date` 严格晚于信息日的逐行校验；其余表走主键唯一性校验
- 质量审计空值口径（`data_quality.py` 实测）：非主键必填列空值 = warning（可解释放行），主键列空值 = blocking；`index_member.out_date`、`suspension.resume_date`、`st_status.end_date`、`stock_basic.delist_date` 在豁免清单内

## 5. 逐表组装方案

### 5.1 只读复用（4 张，实施期复制到新 source 目录，原件不动）

| 表 | 来源文件 | 验收检查点 |
|---|---|---|
| trade_calendar | `staging/real-20260719-r1/trade_calendar.csv` | 3,048 行；2014-01-02 起覆盖协议起点；末行 2026-07-17 即审计窗上限（RESSET 各表覆盖均 ≥ 该窗口，逐表 date_range 在转换验收时记录） |
| stock_basic | `staging/real-20260719-r1/stock_basic.csv` | 5,533 行主键唯一；1,356 成员 0 缺失（2026-08-09 已复核） |
| benchmark_index | `staging/real-20260719-r1/benchmark_index.csv` | 3,048 行与日历逐日对齐；close>0 |
| daily_bar | **暂缓**，待 D1 决策 | 若路线 A 全量替换：新表按 RESSET 口径单独预检与签署增补 |

### 5.2 index_member（🔧 转换）

- 输入：`derived/index_member_derived.csv`（1,662 行 = 1,259 精确 + 358 快照推导 + 45 至少自 2005-01 在场）
- 规则：
  1. `index_code`：`000905` → `000905.SH`
  2. 保留 `source` 溯源列（模板允许增列）
  3. `weight` 全空保留（R3）
- 验收：主键（index_code, ts_code, in_date）零重复；同股区间零重叠（2026-07-25 已验，转换后复验）；2015-01-01 起逐日在册恰 500

### 5.3 suspension（🔧 转换）

- 输入：`source/suspension.csv` + `source/suspension_kcb.csv`
- 规则（审查 F1–F3 + KCB v2）：
  1. F1：保留 `SuspnsnType ∈ {30, 50}`（日级）；10/20/40/60 剔除（留原件）
  2. F2：`ResmptnDt == 1900-01-01` → 空值（339 行哨兵）
  3. F3：保留 `InfoPubDt`、`SuspnsnReason`、`SuspnsnType` 溯源列
  4. KCB v2：按 `HaltResuType`（1 停/2 复）逐股配对成 `[停牌日, 复牌日)`；4 只未复牌 → `resume_date` 空
  5. `ts_code`：主板由 `R_SecuCode` 前缀映射，科创由 `R_SecuCode`（83_）映射；统一 `XXXXXX.SH/SZ`
- 验收：主键（ts_code, suspend_date）零重复；区间零重叠；预检基线 59,205 + 283 区间可对账

### 5.4 st_status（🔧 转换）

- 输入：`source/st_status.csv`（4,105 事件）
- 规则（S1–S5 状态机）：
  1. S1：`ImpDt`（实施日）为区间端点；`InfoPubDt` 保留溯源
  2. S2/S3/S4：进入类开区间、撤销类闭区间、升降级先闭后开、退市整理期独立成段、异常事件先闭旧再开新并留痕
  3. S5：`end_date` 空=仍在状态；退市股开放区间由 `stock_basic.delist_date` 截断
  4. `ts_code`：6 位裸代码经 stock_basic 挂接后缀；挂接失败入异常清单
- 验收：2,930 段基线对账；区间零重叠；当前在 ST/*ST 466 只对账

### 5.5 limit_price（🔧 转换）

- 输入：`limit_price/A_*`（11 包 2014-01~2020-06）+ `B_*`（14 包 2020-07~2026-07）+ `KCB_*`（2019-07-22 起）
- 规则：
  1. `up_limit = PrcCell`，`down_limit = PrcFlr`；保留 `BuyVolUnit/SellVolUnit` 溯源列
  2. 接缝去重（2020-06-30/2020-07-01 已验证无重叠，转换后复验）；主键（trade_date, ts_code）零重复
  3. 空涨跌停 4,565 行 = 无涨跌幅限制日（新股/恢复上市/科创前 5 日），保留空值（warning 级，解释预登记）
  4. 过滤到 `stock_basic` A 股代码集（剔除 B 股 900/200 段）
  5. `ts_code` 经 stock_basic 挂接后缀
- 验收：总行数对账 11,973,238 → 过滤后行数记录；分板块幅度抽查（10/20/30/5%）；已知涨跌停样本 ≥1% 对账（审查要求）

### 5.6 industry（🔧 转换）

- 输入：`industry_history_raw.csv` + `industry_kcb.csv`
- 规则（I1–I3）：
  1. 过滤 `IndClsStd=38`（新申万）
  2. I1：`industry_code/name` 取一级（`IndCd1/IndNm1`）
  3. I2：`[EffDt, CancelDt]` 双端含当日；`CancelDt` 空=当前生效；按 trade_calendar 逐日展开
  4. I3：科创板同标准并入
  5. 同日同股多区间冲突：优先 `IfPerformed=1`，再取最新 `EffDt`；冲突全量留痕
  6. 展开范围：stock_basic 内全部股票（含退市），日期窗 = 日历 2014-01-02 起
- 验收：主键（trade_date, ts_code）零重复；成员日覆盖 ≥95%（预检 96.04% + 科创后 ~99%）；689009 与 11 只早期退市股缺失登记为已知缺口
- 规模预估：约千万级行（5,533 股 × 3,048 日），建议实施期直接落 CSV 供导入转 parquet

### 5.7 financial_indicator（🔧 转换，PIT 要求最高）

- 输入：`find_RESSET_FININD_1..4` + `find2_RESSET_FININD_1..4`（含 CompanyCode）+ `frat_RESSET_FINRATIO_1..2` + `financial_kcb.csv` / `financial_kcb2.csv`（STIBMACCIND）+ `code_change.csv`（SECUCDCHGINFO）+ `derived/delisted_companycode_map.json`
- 规则（R1–R6）：
  1. R1：指标行取 `AdjType ∈ {1, 2}`（累计 YTD）；会计准则与报表类型过滤在实施时按预检记录固化
  2. R2 修订链：每（公司, 报告期）按 `Infopubdt` 排批次 → `revision_id`=批次序号、`ann_date`=首批公告日、`revision_date`=本批公告日；`usable_date`=max(ann, revision) 后首个开市日（**依赖 trade_calendar**）
  3. R3：`roe`=ROE（摊薄）；`debt_ratio`=`Totlia ÷ Totass`；`revenue_yoy/profit_yoy`=同披露版本累计值同比；`gross_margin`=FINRATIO `GIncmRt`（键：代码+报告期+报表类型）
  4. R4：退市股经 `delisted_companycode_map.json`（62/73）+ `code_change.csv` 挂回原代码；KCB 由 STIBMACCIND 补充
  5. R5：`source_id` = RESSET 行级 `ID` + 导出批次目录名
  6. R6：KCB 同行多口径取营收较大者（累计口径恒 ≥ 单季）
  7. 历史窗：`report_period ≥ 2012-12-31`（为 2013 年同比保留基期），registry 登记 history_start 2013-01-01
- 验收：导入程序硬校验（4 列修订键唯一、revision ≥ ann、usable 严格晚于信息日）+ `pit_timing_audit`、`financial_revision_audit` 全 passed；11 只无记录公司登记为已知缺口不回填

### 5.8 daily_basic（🔧 转换，五源合并，依赖 5.7）

- 输入与字段映射：
  | 标准列 | 主板来源 | 科创板来源 | 规则 |
  |---|---|---|---|
  | pe_ttm | `pe/**` `PeRatio`（TTM） | `valuation_kcb_*` `PETTM` | M4：日历日（含周末）记录按 trade_calendar 过滤 |
  | total_mv | `mv/**` `Dmc`（总市值，元） | `valuation_kcb_*` `ToMV` | M4 同上 |
  | turnover_rate | `turnover/**` `DtrdTurnR ÷ 100`（M2 流通股本口径） | **待 D2 决策** | M5 |
  | net_mf_amount | `moneyflow/m0..m6` Σ(IfSum−OfSum \| TrdSumPd∈{3,4})（M1） | `moneyflow/kcb` 同规则（科创阈值档已由 TrdSumPd 编码） | 185 行负值（0.0005%）导入时检查登记 |
  | pb | **推导：total_mv ÷ 归母净资产（SHEwioMin，PIT 对齐，M3）** | `valuation_kcb_*` `PB` | 主板依赖 5.7 的财务修订链 |
- 分片拼接规则：各目录同名分段（如 `RESSET_PERATIO_2016_2020_*` 在 s2/s3 重复出现）→ 全部 concat → 完全重复行去重（PE 边界去重基线 13,498 行可对账）→ 同键异值冲突即阻断入异常清单
- 主键：（trade_date, ts_code）合并后唯一；缺失组合置 NaN（689009 资金流等已知缺口，warning 级解释预登记）
- `ts_code`：裸代码经 stock_basic 挂接后缀

### 5.9 组装顺序（依赖拓扑）

```text
trade_calendar(复用) ─┬─► financial_indicator ─► daily_basic(主板 pb)
stock_basic(复用)   ─┼─► st_status(截断)/ts_code 挂接（全部转换表）
                    ├─► industry(逐日展开)/suspension/index_member/limit_price(独立)
                    └─► daily_basic M4 日历过滤
benchmark_index(复用，独立)
daily_bar(D1 决策后)
```

## 6. 输出目录与批次命名提案（实施期）

- 组装 source 目录（新建，add-only）：`data/staging/real-pit-20260809/source/`
  - 4 张复用表从 `staging/real-20260719-r1/` **复制**（原件不动）
  - 7 张转换表由转换程序从 `real-pit-20260725` 只读生成
  - 若 D1 新数据晚到，改用新批次名（如 `real-pit-20260809-r1`），不覆盖
- 标准目录（导入产物）：`data/standard/real-pit-20260809/`（导入程序要求不存在或为空）
- 门禁目录：`reports/gate/real-pit-20260809/`
- 月度样本：`outputs/monthly/real-pit-20260809/`
- 明确不触碰：`data/raw/real-20260719`、`data/staging/real-20260719(-r1)`、`data/standard/real-stage-20260719(-r1)`、`data/staging/real-pit-20260725`、`data/staging/real-pit-20260726`（空脚手架）

## 7. 验收门禁（对照指南步骤 3–5）

```powershell
$env:PYTHONPATH = 'src'
$SourceDir   = 'data/staging/real-pit-20260809/source'
$StandardDir = 'data/standard/real-pit-20260809'
$GateDir     = 'reports/gate/real-pit-20260809'

.venv\Scripts\python.exe -m ashare_factor_research.main import-data `
  --source-dir $SourceDir --output-dir $StandardDir `
  --format parquet --mode real --source-registry config/data_source_registry.yaml
# 判据：退出码 0；import_gate_status=ready_for_quality_audit

.venv\Scripts\python.exe -m ashare_factor_research.main verify-data --data-dir $StandardDir --mode real

.venv\Scripts\python.exe -m ashare_factor_research.main quality-check `
  --data-dir $StandardDir --output-dir $GateDir --mode real --fail-on-blocking `
  --required-start 2015-01-01 --index-code 000905.SH --min-coverage 0.95
# 判据：退出码 0；data_gate_summary.status=passed 且 blocking_reasons 为空；
# 五审计（pit_timing/financial_revision/survivorship/universe_coverage/benchmark_alignment）全 passed
```

通过后才进入指南步骤 5（build-monthly-sample）与 C 门禁签署。

## 8. 预登记 warning 解释清单（门禁时逐条引用，不做全局静默）

| 表 | 预期 warning | 解释依据 |
|---|---|---|
| index_member | `missing_rate:weight`=1.0 | 审查 R3：weight 留空不编造，月度权重留存源文件 |
| limit_price | 空 up/down 4,565 行 | 无涨跌幅限制日（新股/恢复上市/科创前 5 日），非缺失 |
| daily_basic | 689009 资金流/（或换手率）NaN | 预检已知缺口 1/1,356，不补齐不编造 |
| daily_bar（若现表） | 腾讯源 amount 缺失 28.4%、adj_factor 缺失 0.08%（689009）、zero_amount、amount_spikes、adj_factor_jumps | `daily_bar_review.md` 已登记口径 |
| industry / financial_indicator | 11 只早期退市股无记录 | 预检总报告第三节，方向性影响已声明 |
| financial_indicator | 金融股 gross_margin NaN | RESSET 口径无营业成本概念 |

## 9. 当前门禁预测（基于 2026-08-09 只读复核）

- **若 daily_bar 按现状（753 只）直接组装**：`survivorship_audit` 783 行失败 + `universe_coverage` 覆盖率 ≈42% → `status=blocked_by_pit_quality`，**必然不过**
- 其余 10 表按本计划转换后，依据预检基线与程序校验逻辑，预期可达门禁要求（实施期以实测为准）
- 因此正确顺序是：**先决 D1（含 D2），再做转换实现，再一次导入验收**

## 10. 实施前提（需用户逐项批准，本次均未执行）

1. **D1 路线选择**（A/B/C）：daily_bar 缺口闭合路线；路线 A 需用户导出 RESSET 日行情
2. **D2 选项选择**（a/b）：科创板换手率来源或 M5 修订
3. **转换实现授权**：批准编写并运行转换程序（激活 quant-code-review），从冻结暂存区只读生成 7 张标准表到新 source 目录
4. **真实导入授权**：11 表齐后运行第 7 节命令序列
5. 上述任何数据文件变化 → 原签署失效，按指南重签

## 附：本阶段只读操作留痕

- 枚举并抽样：`data/staging/real-pit-20260725/**`、`data/staging/real-20260719-r1/*`、`data/standard/real-stage-20260719*/`（仅目录级）
- 只读分析：成员↔主表↔行情三集合差异计算（stdout，无落盘）
- 程序契约阅读：`import_standard.py`、`schema.py`、`source_registry.py`、`data_quality.py`、`pit_audit.py`、`main.py`（CLI 参数）
- 新增文件仅两份：本计划 + `staging_freeze_20260809.sha256`

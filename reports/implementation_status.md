# 项目实施进度与下一步

更新时间：2026-08-11（P0 真实数据门禁冻结通关、P1/P2 真实运行完成；此前状态见各节历史记录）

当前主线：`A-LLM-`

总体状态：**P0 真实数据门禁已冻结通关（批次 real-pit-20260725-r2，签署页 A/B/C 全签），P1（阶段 2–6 真实运行）与 P2（阶段 7–8 真实运行）已完成；阶段 8 最终结论为 insufficient_evidence——含义是"证据不足"，不是"策略无效"：受预注册 FDR 口径约束，动态权重只覆盖 4 个 OOS 月，七组消融共同窗不足 36 个月，无法对动态方案作出有效或无效的统计裁定。**

## 一、现在处于什么位置

阶段 4–6 的工程实现、合成恢复测试、CLI、配置契约和防泄漏门禁早已完成；真实 PIT 数据已补齐并通过验收（2026-08-11，批次 real-pit-20260725-r2），阶段 2–8 已全部完成真实运行。sample 和测试夹具只证明工程链可运行，不构成真实市场结论；真实结论以第八节摘要与阶段 8 晋级产物为准。

| 工作流 | 工程状态 | 真实数据/实证状态 | 当前结论 |
| --- | --- | --- | --- |
| 核心多因子研究与回测 | 已完成 | 完整 PIT 真实基线已形成（r2 批次） | 工程与真实基线均可用 |
| 协议、实验登记与配置契约 | 已完成 | 签署页 A/B/C 三部分全签（2026-07-30 许可入库、2026-08-11 哈希确认与终审） | 配置已冻结，签署完成 |
| 真实数据导入与六类审计 | 已完成 | r2 批次门禁 status=passed，五项审计全过 | 已通关冻结 |
| 阶段 2 月度时序样本 | 已完成 | 真实月度产物已生成：118 标签 / 31 因子 / gate_status=passed；benchmark_returns.csv 自动落盘并登记哈希 | 真实产物完成 |
| 阶段 3 诊断与简单基准 | 已完成 | 真实诊断与基准已运行（3 目标 × 7 模型，58/56/58 OOS 点） | 复杂模型未显著胜过简单基准，按验收标准不进入组合 |
| 阶段 4 Kalman | 已完成 | 27 组预注册网格真实 OOS 57 月全部完成 | 未胜过 24 个月滚动 IC 基线（RMSE 0.1602 vs 0.1597），负结果如实记录 |
| 阶段 5 Gaussian HMM | 已完成 | 2/3 态真实运行完成（三种子 17/29/43） | 跨窗稳定性不达标（3 态 52% 窗口完全翻转）；有效月 34<36 |
| 阶段 6 波动模型与 DCC | 已完成 | 六类波动模型真实比较完成（各 70 预测） | 无模型全面占优，不自动晋级；DCC 因子数 5<6 记 insufficient |
| 阶段 7 组合与七组消融 | 已完成（stage7 + run-portfolio-ablation CLI + 测试） | 真实消融已运行 | 共同窗 4 个月 <36，全臂 insufficient_history（未放松口径） |
| 阶段 8 过拟合审计与晋级 | 已完成（stage8 + run-promotion-audit CLI + 19 项测试，promotion 配置段已冻结并登记入配置契约） | 正式晋级审计已执行 | 结论 insufficient_evidence，dynamic_ready=false |
| 阶段 9 只读研究看板 | 已完成（8 页 Streamlit 看板 + 只读适配层 + 契约测试） | 可展示真实产物（月度/阶段 3–8 均已落盘） | 不阻塞研究主线 |
| 阶段 10 深度学习实验 | 未开始 | 前置条件不满足（阶段 8 结论为证据不足） | 暂不启动 |

## 二、已经完成的工程工作

### 1. 核心研究与治理

- 三配置统一驱动，Top50/5%、成本、执行和约束参数一致。
- 标准数据导入、列映射、主键与日期校验、SHA-256 manifest 和真实模式硬阻断已实现。
- 信号日、执行日、标签结束日和可用日显式保留；财务公告、修订和可用时点具备 PIT 校验。
- 历史成分、行业/ST/停牌/涨跌停、成交延迟、成本、容量和未成交分析已进入工程合同。
- 基准相对指标、行业/市值/个股/回撤/成本归因和稳健性产物已实现。
- LLM 事件标签保持离线优先，并保存来源、原文、prompt/model 版本、JSON、cache key 和人工抽查状态。

### 2. 真实 PIT 工程门禁

- 冻结 2015/2018/2024 研究窗口、最终留出期和实验登记。
- `data_manifest.json` v2 绑定来源登记表，真实目录禁止覆盖。
- 财务表保留完整修订链，不允许最新值回填历史。
- 已实现数据质量、PIT timing、财务修订、幸存者、历史成员覆盖和基准对齐审计。
- 完整真实导入要求 `review_status: approved`，且 `reviewed_by`、`reviewed_at` 非空。
- 新浪 qfq 因子已按除数语义纠正：保留 `qfq_factor_raw`，并令 `adj_factor = 1 / qfq_factor_raw`。
- 已提供 [真实 PIT 许可与人工签署执行指南](data_sources/真实PIT许可与人工签署执行指南.md) 和 [签署清单模板](data_sources/templates/真实PIT许可签署清单模板.md)。

### 3. 阶段 2–3 时间序列基础链

- `build-monthly-sample`：月末收盘信号、下一交易日开盘执行、非重叠标签和最终留出期隔离。
- 输出月度 IC、原始/中性化因子收益、状态变量、成本和历史成员覆盖率。
- 当前只落盘 3 个核心月度 CSV；真实阶段 4–6 还要求显式的 `trade_date,benchmark_return` 日频文件，这是数据到位后需要补齐的交接产物。
- `run-time-series-baselines`：逐预测点记录训练截止日及 ADF、KPSS、ACF/PACF、Ljung-Box、ARCH LM、Zivot-Andrews 等诊断。
- 已比较 lag-1、历史均值、12/24 月均值、EWMA、AR(1) 和固定滞后 ARIMAX。

### 4. 阶段 4–6 模型加固

- 新增 `run-time-series-models`，候选模型与完整 pipeline 共用实现。
- Kalman：严格执行 `availability_date < test_date`，完成 27 组预注册网格、动态权重、换手和稳定性产物。
- HMM：完成两状态和三状态 Gaussian HMM；每个预测点只用训练期标准化、filtered probability 和固定种子多初始化。
- 波动模型：比较 historical 20/60、EWMA、GARCH、GJR-GARCH 和 EGARCH，输出 RMSE、MAE、QLIKE、ARCH 和极端期误差。
- DCC：限定在 Kalman 筛选后的 6–10 个因子，输出动态协方差和风险贡献，并校验对称性、半正定性和参数稳定性。
- 所有空产物保留固定 schema；不足 36 个非重叠 OOS 月时维持 `insufficient_history`。
- sample 明确标记 `synthetic_engineering_only=true`；完整 pipeline 不会自动采用未达门槛的动态分数。

## 三、曾阻断项与解除记录

> 本节为 2026-07-23 时点的阻断记录，保留备查。**全部阻断已于 2026-08-11 解除**：7 张必需表经 RESSET 导出、只读预检、标准转换、签署页 A/B/C 三部分签署后，冻结为 real-pit-20260725-r2 批次；数据质量与五项专项审计全过，门禁 status=passed（`reports/gate/real-pit-20260725-r2/`）。当前状态见文末"八、P0/P1 完成摘要与遗留事项"。

### 1. 七张必需 PIT 表尚未到位

当前已有：

- `trade_calendar`
- `stock_basic`
- `daily_bar`
- `benchmark_index`

当前缺失：

- `daily_basic`
- `financial_indicator`
- `index_member`
- `industry`
- `limit_price`
- `st_status`
- `suspension`

`news_event` 为可选表，不阻断本轮真实数据门禁。

### 2. 来源登记和人工签署尚未完成

- `config/data_source_registry.yaml` 当前仍为 `pending_user_review`。
- 7 张表的实际供应商、版本、接口/批次、许可、单位、PIT 语义和证据位置尚未回填并批准。
- 入库前“许可与入库授权”未签署。
- 审计通过后的“审计验收与数据冻结”尚不能签署。
- 旧 `signoff_sheet_20260719.md` 的协议哈希已过期，只作历史记录。

### 3. 当前真实门禁证据

当前 `reports/gate/real-stage-20260719-r1/data_gate_summary.json`：

- `status = blocked_by_missing_pit_tables`
- 13 条阻断原因仍存在。
- `pit_timing_audit.csv`：0 行。
- `financial_revision_audit.csv`：0 行。
- `survivorship_audit.csv`：0 行。
- `universe_coverage.csv`：0 行。
- `benchmark_alignment.csv`：2,803/2,803 交易日通过，但不能替代其他 PIT 审计。

因此阶段 2 的真实月度 IC、因子收益和状态变量尚未生成，阶段 3–6 也没有可接受的真实输入。

## 四、下一步待办清单

### P0：先解锁真实数据门禁

- [ ] 确定 7 张必需表各自的合法数据来源。
- [ ] 按标准模板导出 CSV/Parquet，覆盖起点不晚于 2015-01-01，并包含已剔除、退市和历史状态。
- [ ] 准备许可摘要：缓存、研究/回测、衍生输出、图表展示和禁止再分发范围。
- [ ] 准备字段与 PIT 证据：单位、分母、公告/修订/可用日、生效区间和导出批次。
- [ ] 由 Codex 做只读预检：schema、主键、空值、日期、区间重叠、单位、覆盖率和跨表关系。
- [ ] 修复预检发现的数据问题，直至 7 张表具备批准条件。
- [ ] 用户完成第一次签署：许可与入库授权。
- [ ] 按签署结果更新 `data_source_registry.yaml`，计算并核对登记表和协议哈希。
- [ ] 新建真实标准目录执行完整导入，不覆盖旧批次。
- [ ] 运行数据质量和五个专项审计，令 blocking 归零、专项审计非空且全部通过。
- [ ] 用户完成第二次签署：审计验收与数据冻结。

详细字段和签署步骤见 [真实 PIT 许可与人工签署执行指南](data_sources/真实PIT许可与人工签署执行指南.md)。

### P1：运行真实阶段 2–6

全部完成（2026-08-11，批次 real-pit-20260725-r2）：

- [x] 生成阶段 2 真实月度 IC、因子收益、状态变量和历史成员覆盖产物（118 标签 / 31 因子 / gate_status=passed，`outputs/monthly/real-pit-20260725-r2/`）。
- [x] 从已验收的 `benchmark_index` 生成并审计 `trade_date,benchmark_return` 日频文件：`build-monthly-sample` 已自动落盘 `benchmark_returns.csv`（3,035 开市日）并在 `monthly_sample_summary.json` 登记 `benchmark_returns_sha256=746aeb94…`。
- [x] 运行阶段 3 诊断和简单基准（`outputs/baselines/real-pit-20260725-r2/`）：逐预测点诊断可审计；早期窗口 48 行 insufficient_history、24 行 unavailable、1 个极端值复核标记均如实留痕；结论：复杂模型未显著胜过简单基准。
- [x] 运行阶段 4 的 27 组 Kalman 网格并与静态、12 月、24 月和 EWMA 权重比较（真实 OOS 57 个月；Kalman 最优组 RMSE 0.1602 未胜 24 月滚动基线 0.1597）。
- [x] 运行阶段 5 的 2/3 状态 HMM（三种子）：状态标签与持续期可解释性一般，3 态跨窗稳定性不达标（52% 窗口概率完全翻转）。
- [x] 运行阶段 6 的六类波动模型和 DCC：无模型全面占优（historical_20 QLIKE 最优但残差 ARCH 拒绝率 100%；GARCH 族残差诊断优但 QLIKE 略逊）；DCC 因筛选后因子数 5<6 记 insufficient_factors_or_history。
- [x] 确认至少 36 个非重叠 OOS 月：达成 57 个月（阶段 4–6 口径）。
- [x] 保持 2024-01-01 起最终留出期隔离：阶段 0–8 全程零接触，未根据留出期表现修改任何参数或门槛。

### P2：完成研究结论链

真实运行已完成（2026-08-11），结论为证据不足而非策略无效：

- [x] 实现并运行阶段 7 的七组固定组合与消融实验（真实模式，`outputs/ablation/real-pit-20260725-r2/`）：因 Kalman 动态权重仅覆盖 4 个 OOS 月，七臂共同窗压缩为 4 个月 <36，全臂判定 `insufficient_history`。
- [ ] 区分 Kalman、HMM、波动控制和 DCC 的独立增量：**未能区分**——共同窗不足 36 个月，增量归因按纪律保持 insufficient，未放松口径；待 FDR 瓶颈有协议级决策后重跑。
- [x] 执行阶段 8 的预测检验、过拟合审计和正式模型晋级（真实模式，`outputs/promotion/real-pit-20260725-r2/`）：最终结论 **insufficient_evidence**（等级 1/4），dynamic_ready=false。
- [x] 只有达到预注册门槛时才允许 `dynamic_ready`：门槛未达，保留"不晋级"结论；静态方案维持现状。
- [ ] 更新研究报告、导师汇报材料和证据 manifest：部分完成——本文档与 `factor_research_report.md` 已更新（2026-08-11）；导师汇报材料与证据 manifest 更新留待用户安排。

### P3：非关键路径

- [ ] 根据需要建设只读研究看板；不得让前端替代数据和模型门禁。
- [ ] 深度学习实验仅在至少 8 年合格真实数据、PIT 问题归零且传统模型基线完成后启动。
- [x] 阶段 4–6 实现与文档变更已提交，工作树干净（2026-07-23）；后续 commit/push 节奏由用户另行决定。

## 五、完成条件

### 阶段 4–6“工程完成”——已经满足

- [x] 算法、CLI、配置契约和固定 schema 已实现。
- [x] 防未来标签、过滤概率、参数约束和不足历史阻断已有测试。
- [x] 合成恢复和 CLI smoke 已通过。
- [x] 未达到 OOS 门槛时不会自动晋级动态方案。

### 阶段 4–6“真实研究完成”——已满足（2026-08-11）

- [x] 真实 PIT 数据门禁 `status=passed`（批次 real-pit-20260725-r2）。
- [x] 阶段 2–3 真实产物完整并通过时点审计。
- [x] 至少 36 个非重叠 OOS 月（57 个月）。
- [x] Kalman/HMM/GARCH/DCC 真实比较完成，无 NaN 爆炸或未解释失败（DCC 因子数不足按设计记 insufficient，不视为工程失败）。
- [x] 阶段 7 消融和阶段 8 过拟合审计完成（判定分别为 insufficient_history 与 insufficient_evidence，均属合规结论而非运行失败）。
- [x] 最终留出期只用于一次性确认，不用于调参（全程未触发留出期确认；阶段 8 代码无留出期触点）。
- [x] 用户签署最终数据冻结（签署页 C 部分，2026-08-11）。
- [ ] 用户确认模型晋级结论（insufficient_evidence，待终审）。

## 六、最近验证结果

验证日期：2026-08-11

解释：工程检查与真实运行结果并列；真实门禁与阶段结论不构成收益承诺。

| 检查 | 结果 |
| --- | --- |
| `compileall` | 通过 |
| `unittest` | 176 项通过，0 失败 |
| 真实 PIT 数据门禁（real-pit-20260725-r2） | **status=passed**（blocking=0；pit_timing 548,524 行 0 失败、universe_coverage 2,790 日 0 失败等五项审计全过） |
| 真实月度样本（阶段 2） | gate_status=passed；118 标签 / 31 因子；benchmark_returns_sha256 已登记 |
| 阶段 3 真实诊断基准 | 运行完成；复杂模型未显著胜过简单基准 |
| 阶段 4–6 真实 OOS | 运行完成；57 个 OOS 月；Kalman 未胜 24 月滚动基线、HMM 稳定性不达标、波动模型无全面占优、DCC 因子数不足 |
| 阶段 7 真实消融 | 运行完成；共同窗 4 个月 <36，全臂 insufficient_history |
| 阶段 8 真实晋级审计 | 运行完成；结论 insufficient_evidence，dynamic_ready=false |
| 权重口径回归（gross=1） | 通过：economic_comparison 爆炸月 48→0（2026-08-11 用户批准的协议级修改，见 `预检总报告_20260727.md` 第七节） |

历史记录（2026-07-25，sample 模式）：unittest 163 项、7 个 Notebook smoke、sample pipeline CLI 均通过；当时真实门禁仍为 blocked_by_missing_pit_tables。

完整质量门禁已运行：

```powershell
$env:PYTHONPATH = 'src'
.venv\Scripts\python.exe -m ashare_factor_research.main quality
```

本次环境未运行 Ruff（完整质量门禁只在 Ruff 已安装时自动加入该步骤）；compileall、unittest、Notebook 和 CLI 门禁均为 0 退出码。

## 七、真实数据到位后的命令顺序

下面只列顺序；实际批次名和签署步骤以真实 PIT 指南为准。

```powershell
$env:PYTHONPATH = 'src'

# 1. 完整真实导入（必须已完成第一次人工签署）
.venv\Scripts\python.exe -m ashare_factor_research.main import-data `
  --source-dir data/staging/real-pit-YYYYMMDD/source `
  --output-dir data/standard/real-pit-YYYYMMDD `
  --format parquet `
  --mode real `
  --source-registry config/data_source_registry.yaml

# 2. 数据哈希和真实门禁
.venv\Scripts\python.exe -m ashare_factor_research.main verify-data `
  --data-dir data/standard/real-pit-YYYYMMDD `
  --mode real

.venv\Scripts\python.exe -m ashare_factor_research.main quality-check `
  --data-dir data/standard/real-pit-YYYYMMDD `
  --output-dir reports/gate/real-pit-YYYYMMDD `
  --mode real `
  --fail-on-blocking `
  --required-start 2015-01-01 `
  --index-code 000905.SH `
  --min-coverage 0.95

# 3. 月度样本
.venv\Scripts\python.exe -m ashare_factor_research.main build-monthly-sample `
  --data-dir data/standard/real-pit-YYYYMMDD `
  --output-dir outputs/monthly/real-pit-YYYYMMDD `
  --mode real `
  --final-holdout-start 2024-01-01 `
  --min-coverage 0.95

# 4. 阶段 4–6；只有 data_gate_summary.status=passed 才允许运行
.venv\Scripts\python.exe -m ashare_factor_research.main run-time-series-models `
  --mode real `
  --monthly-ic outputs/monthly/real-pit-YYYYMMDD/monthly_factor_ic.csv `
  --monthly-returns outputs/monthly/real-pit-YYYYMMDD/monthly_factor_returns.csv `
  --state-variables outputs/monthly/real-pit-YYYYMMDD/monthly_state_variables.csv `
  --benchmark-returns outputs/monthly/real-pit-YYYYMMDD/benchmark_returns.csv `
  --protocol config/research_protocol.real.yaml `
  --pit-gate-summary reports/gate/real-pit-YYYYMMDD/data_gate_summary.json `
  --output-dir outputs/stage46/real-pit-YYYYMMDD
```

注意：`--benchmark-returns` 要求 CSV 且包含 `trade_date,benchmark_return` 两列。自 2026-07-25 起 `build-monthly-sample` 自动从已验收基准指数点位转换出第 4 个交接产物 `benchmark_returns.csv`（非空、日期唯一、无 NaN 校验，并在 `monthly_sample_summary.json` 登记 `benchmark_returns_sha256`）；不能把指数点位 Parquet 直接传入。

## 八、P0/P1 完成摘要与遗留事项（2026-08-11）

### 1. 完成摘要

- **冻结批次**：`data/standard/real-pit-20260725-r2/`（RESSET 7 张必需表 + 4 张补导表；签署页 `reports/data_sources/signoff_sheet_20260727.md` A/B/C 三部分全签）。门禁 `reports/gate/real-pit-20260725-r2/data_gate_summary.json` status=passed，五项专项审计全过；字段级覆盖率 14 字段 × 2,790 日零失败（两项登记豁免逐日计数可审计）。
- **阶段 2（真实月度样本）**：118 标签 / 31 因子 / gate_status=passed。
- **阶段 3（诊断与基准）**：真实运行完成；ARIMAX 等复杂模型相对简单基准无显著优势，按预注册验收标准不进入组合。
- **阶段 4（Kalman）**：27 组预注册网格真实 OOS 57 个月全部完成；最优组未胜过 24 个月滚动 IC 基线（负结果如实记录）。
- **阶段 5（HMM）**：2/3 态三种子真实运行完成；3 态跨窗稳定性不达标，有效概率月数 34<36。
- **阶段 6（波动/DCC）**：六类波动模型无全面占优者，不自动晋级；DCC 因筛选后因子数 5<6 保持 insufficient。
- **阶段 7（七组消融）**：真实运行完成；共同投资窗仅 4 个月 <36，全臂 insufficient_history（未放松口径）。
- **阶段 8（晋级审计）**：真实运行完成；最终结论 **insufficient_evidence**（证据不足，非策略无效），dynamic_ready=false。理由链：预注册 FDR（q≤0.05）多数月份通过因子不足 5 个 → 动态权重仅 4 个月 → 共同窗 4 个月 → OOS 不足 36 → 无法统计裁定。

### 2. 遗留事项

- **FDR 瓶颈（协议级，需用户决策方可修订）**：57 个 OOS 月中 27 个月 0 个因子通过 q≤0.05，仅 4 个月达到权重下限 5 因子 → 动态权重与消融共同窗受限。FDR 口径为预注册项，2026-08-11 用户决策保持不变；任何调整须走协议修订与重新签署。
- **DCC 空缺**：筛选后因子数 5<6，dynamic_covariance 与风险贡献为空表；阶段 7 G 臂的无 DCC 退化路径未触发（整臂 insufficient）。
- **HMM 有效月 34<36**：有效概率覆盖不足协议最低 OOS 月数，按"证据不足"如实裁定。
- **2026-07 尾巴留待下一增量批次**：本批数据统一止于 2026-06-30（决策 3），2026-07 的 12 个开市日由下一批补齐。
- **已闭合项**：科创流通市值换手（M5）与科创 gross_margin 缺口已由 2026-08-11 补导批次闭合（附录 A/第七节留痕）。
- **数据缺口保持 NaN 并计数**：689009.SH（九号公司 CDR）资金流/行业/财务缺失；ps、large_order_net_mf_amount、operating_cash_flow 三个因子输入无来源列，对应因子置空（均已声明）。

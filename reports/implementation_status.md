# 项目实施进度与下一步

更新时间：2026-07-23

当前主线：`A-LLM-`

总体状态：**工程链已具备，真实研究仍被 PIT 数据验收阻断。**

## 一、现在处于什么位置

当前不需要继续扩展 Kalman、HMM、GARCH 或 DCC 的算法骨架。阶段 4–6 的工程实现、合成恢复测试、CLI、配置契约和防泄漏门禁已经完成；当前关键路径是补齐并验收真实 PIT 数据。

只有真实数据门禁通过、月度研究样本生成，并形成至少 36 个非重叠 OOS 月后，才能评价动态模型是否有效。sample 和测试夹具只证明工程链可运行，不构成真实市场结论。

| 工作流 | 工程状态 | 真实数据/实证状态 | 当前结论 |
| --- | --- | --- | --- |
| 核心多因子研究与回测 | 已完成 | 尚未形成完整 PIT 真实基线 | 工程可用，实证待补 |
| 协议、实验登记与配置契约 | 已完成 | 最终签署待真实数据来源确认 | 配置已冻结，签署待办 |
| 真实数据导入与六类审计 | 已完成 | 被 7 张必需表阻断 | 当前最高优先级 |
| 阶段 2 月度时序样本 | 主体已完成 | 真实月度产物未生成；日频基准收益交接文件待补 | 等待 PIT 门禁 |
| 阶段 3 诊断与简单基准 | 已完成 | 真实基准未运行 | 等待阶段 2 真实产物 |
| 阶段 4 Kalman | 已完成 | 真实 OOS 比较未运行 | 候选模型，不得晋级 |
| 阶段 5 Gaussian HMM | 已完成 | 真实状态稳定性未验证 | 候选模型，不得解释状态 |
| 阶段 6 波动模型与 DCC | 已完成 | 真实风险预测未验证 | 候选模型，不得用于配置 |
| 阶段 7 组合与七组消融 | 已完成（stage7 + run-portfolio-ablation CLI + 测试） | 真实消融未运行 | 等待阶段 4–6 真实结果 |
| 阶段 8 过拟合审计与晋级 | 已完成（stage8 + run-promotion-audit CLI + 19 项测试，promotion 配置段已冻结并登记入配置契约） | 未执行正式晋级 | 等待阶段 7 真实结果 |
| 阶段 9 只读研究看板 | 已完成（8 页 Streamlit 看板 + 只读适配层 + 契约测试） | 仅可展示 sample/已有产物 | 不阻塞研究主线 |
| 阶段 10 深度学习实验 | 未开始 | 前置条件不满足 | 暂不启动 |

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

## 三、当前硬阻断

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

只有 P0 全部完成后才执行：

- [ ] 生成阶段 2 真实月度 IC、因子收益、状态变量和历史成员覆盖产物。
- [ ] 从已验收的 `benchmark_index` 生成并审计 `trade_date,benchmark_return` 日频文件；自 2026-07-25 起 `build-monthly-sample` 已自动落盘该第 4 个输入并登记哈希，运行后核对即可。
- [ ] 运行阶段 3 诊断和简单基准，确认缺失、异常和模型失败状态可审计。
- [ ] 运行阶段 4 的 27 组 Kalman 网格，与静态、12 月、24 月和 EWMA 权重比较。
- [ ] 运行阶段 5 的 2/3 状态 HMM，检查状态标签、持续期和跨窗口稳定性。
- [ ] 运行阶段 6 的六类波动模型和 DCC，检查极端期误差、PSD 和风险贡献。
- [ ] 确认至少 36 个非重叠 OOS 月；不足时继续标记 `insufficient_history`。
- [ ] 保持 2024-01-01 起最终留出期隔离，不根据留出期表现修改参数或门槛。

### P2：完成研究结论链

- [ ] 实现并运行阶段 7 的七组固定组合与消融实验。
- [ ] 区分 Kalman、HMM、波动控制和 DCC 的独立增量。
- [ ] 执行阶段 8 的预测检验、过拟合审计和正式模型晋级。
- [ ] 只有达到预注册门槛时才允许 `dynamic_ready`；否则保留静态方案或“不晋级”结论。
- [ ] 更新研究报告、导师汇报材料和证据 manifest。

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

### 阶段 4–6“真实研究完成”——尚未满足

- [ ] 真实 PIT 数据门禁 `status=passed`。
- [ ] 阶段 2–3 真实产物完整并通过时点审计。
- [ ] 至少 36 个非重叠 OOS 月。
- [ ] Kalman/HMM/GARCH/DCC 真实比较完成，无 NaN 爆炸或未解释失败。
- [ ] 阶段 7 消融和阶段 8 过拟合审计完成。
- [ ] 最终留出期只用于一次性确认，不用于调参。
- [ ] 用户签署最终数据冻结与模型晋级结论。

## 六、最近验证结果

验证日期：2026-07-25

解释：以下只验证当前工程状态；不验证真实市场有效性。

| 检查 | 结果 |
| --- | --- |
| `compileall` | 通过 |
| `unittest` | 163 项通过，0 失败 |
| 7 个 Notebook smoke | 通过 |
| 临时样例数据生成 CLI | 通过 |
| 临时 sample pipeline CLI | 通过 |
| 阶段 4–6 sample/real 测试夹具 | 正确输出固定产物与 `insufficient_history` |
| 真实 PIT 数据门禁 | 未通过，仍为 `blocked_by_missing_pit_tables` |

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

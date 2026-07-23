# 真实 PIT 许可与人工签署执行指南

版本：2026-07-20  
适用范围：中证 500（`000905.SH`）真实数据研究链，研究起点不晚于 2015-01-01  
当前结论：真实模式仍被 7 张必需表和人工签署阻断；工程与合成测试不受影响，真实实证、模型晋级和投资结论继续冻结。

> 本指南是执行清单，不是签署结果。任何 `approved`、审查人姓名和日期都必须由用户本人确认；Codex 只能校验、整理证据和按明确授权更新登记表，不能代签。

## 1. 现在到底缺什么

真实模式共有 11 张核心必需表。当前已有 4 张：`trade_calendar`、`stock_basic`、`daily_bar`、`benchmark_index`；仍缺以下 7 张：

- `daily_basic`
- `financial_indicator`
- `index_member`
- `industry`
- `limit_price`
- `st_status`
- `suspension`

`news_event` 是可选表，不影响本轮真实 PIT 门禁，可以继续保持未启用。

完成“真实 PIT 许可表及人工签署”不是只把 7 个文件放进目录。每张表都必须同时满足四层条件：

| 层次 | 要证明什么 | 通过标志 |
| --- | --- | --- |
| 许可 | 有权本地缓存、用于研究、输出衍生结果和展示图表；不再分发原始数据 | 对应 `*_review.md` 有脱敏证据摘要，用户明确批准 |
| PIT 语义 | 数据在历史时点何时真实可用，修订和状态变化没有被当前值回填 | 表级 PIT 规则写清且预检通过，登记表 `pit_ready: true` |
| 数据质量 | schema、主键、日期、区间、覆盖率和跨表关系通过 | 质量报告无 blocking，专项审计非空且全部通过 |
| 人工治理 | 用户确认来源、协议、哈希、留出期和冻结范围 | 入库前授权 + 审计后冻结确认均有签名/确认记录 |

## 2. 你需要向数据供应商或导出人员索取的材料

### 2.1 七个标准数据文件

- 格式：UTF-8 CSV 或 Parquet。
- 文件名必须是 `<表名>.csv` 或 `<表名>.parquet`。
- 表头以 `reports/data_sources/templates/<表名>.template.csv` 为准；允许增加溯源列，但不得缺列或改标准列名。
- 覆盖起点不晚于 2015-01-01，包含历史成分、已剔除和已退市股票，禁止只交当前在市股票。
- 原始导出不得放进 Git；建议放入新的日期化目录，例如 `data/staging/real-pit-YYYYMMDD/source/`。
- 不要覆盖 `data/raw/real-20260719`、`data/staging/real-20260719-r1` 或 `data/standard/real-stage-20260719-r1`。

### 2.2 每个来源的许可证明

许可证明可以是合同条款、账号权限页、供应商邮件、终端授权页或官方许可说明。至少要能回答：

- [ ] 供应商和产品/模块名称是什么？
- [ ] 账号类型是什么？只写账号类型，不写账号、密码、令牌或 cookie。
- [ ] 是否允许将原始数据缓存在本机并重复导入？
- [ ] 是否允许用于量化研究、回测和论文/研究报告？
- [ ] 是否允许导出统计量、模型参数、组合结果等衍生结果？
- [ ] 是否允许在论文、报告或答辩中展示聚合图表？
- [ ] 是否明确禁止向第三方再分发原始数据？如禁止，项目必须遵守。
- [ ] 授权有效期和适用主体是什么？个人、学校、机构或项目组？
- [ ] 许可证据的页码、条款号、截图编号或邮件日期是什么？

仓库内只保存脱敏摘要和证据位置，不保存商业合同全文、权限截图原件、凭据或受限原始数据。原件可保存在用户控制的位置，项目中只登记“原件位置/文档编号 + SHA-256（可选）”。

### 2.3 每张表的导出与字段证据

每张表还要记录：

- [ ] 导出人、导出日期和时区。
- [ ] 供应商版本、终端版本、接口名称或文件批次号。
- [ ] 请求参数、指数代码、日期范围、市场范围和是否包含退市证券。
- [ ] 原始字段 ID 到标准字段名的映射。
- [ ] 每个数值字段的单位、分母、复权或计算口径。
- [ ] 公告日、修订日、生效日、可用日和区间结束日的定义。
- [ ] 原始文件名、文件大小、行数和 SHA-256。

## 3. 七张表的硬性清单

### 3.1 `daily_basic`

标准列：

```text
trade_date,ts_code,pe_ttm,pb,total_mv,turnover_rate,net_mf_amount
```

- 主键：`trade_date + ts_code`，每股票每交易日一行。
- `total_mv`、`net_mf_amount`：人民币元；如供应商给万元，导入前必须明确换算。
- `turnover_rate`：小数比率，不是百分数；必须写明分母是总股本、流通股本还是自由流通股本。
- PIT：使用当日收盘后可得值，不允许后来修订值回填过去。
- 导入前宽松阻断：相对 `daily_bar` 的键缺失率不得超过 20%。
- 最终门禁：中证 500 历史有效成分的逐日覆盖率目标为至少 95%；20% 只是早期导入拒绝线，不代表最终合格。
- `net_mf_amount` 必须附供应商主动买卖/资金流定义页。

### 3.2 `financial_indicator`

标准列：

```text
ts_code,report_period,ann_date,usable_date,revision_date,revision_id,source_id,
roe,gross_margin,debt_ratio,revenue_yoy,profit_yoy
```

- 这是 PIT 风险最高的表，必须保留首次披露和全部更正、重述版本，不能只交最新值。
- 唯一性：`ts_code + report_period + ann_date + revision_id` 必须唯一。
- `report_period <= ann_date`。
- `revision_date >= ann_date`；首次披露没有独立修订日时，应按供应商真实语义填写，不能凭空推断。
- `usable_date > max(ann_date, revision_date)`，并且必须是开市交易日。盘后发布默认下一交易日可用。
- `source_id` 必填，使用公告编号、修订公告编号或可复核的导出批次标识。
- 同一报告期的 `revision_id` 不得重复。
- `roe`、`gross_margin`、`debt_ratio`、`revenue_yoy`、`profit_yoy` 都要给供应商字段 ID、单位和计算定义。
- 特别注意：通用 schema 的基础粒度写作“一次公告一行”，真实导入会用包含 `revision_id` 的四列唯一键做校验；不要自行合并修订记录。

### 3.3 `index_member`

标准列：

```text
index_code,ts_code,weight,in_date,out_date
```

- 主键：`index_code + ts_code + in_date`；一次成分有效区间一行。
- 指数代码必须是 `000905.SH`，不得用当前 500 只成分回填历史。
- 覆盖 2015-01-01 以来全部调入、调出、已剔除和已退市股票。
- 区间采用左闭右开：`in_date <= 当日 < out_date`；仍在指数中时 `out_date` 留空。
- 同一指数、同一股票的有效区间不得重叠。
- `weight` 是小数比率；如果来源是百分数，必须明确除以 100。若历史权重缺失，不能编造，需在证据摘要中说明并等待项目决策。

### 3.4 `industry`

标准列：

```text
trade_date,ts_code,industry_code,industry_name
```

- 主键：`trade_date + ts_code`；每股票每交易日一行。
- 必须从真实生效区间展开，不能用当前行业分类回填历史。
- 必须固定并记录分类体系和版本，例如申万 2021 或中信；同一批次不得混用体系。
- 行业调整按真实生效日进入日表。
- 中证 500 历史有效成分逐日覆盖率至少 95%。

### 3.5 `suspension`

标准列：

```text
ts_code,suspend_date,resume_date
```

- 主键：`ts_code + suspend_date`；一次连续停牌区间一行。
- 区间采用左闭右开：`suspend_date <= 当日 < resume_date`；仍未复牌时 `resume_date` 留空。
- 同一股票的区间不得重叠。
- 仅凭行情缺行推导停牌会混入供应商漏数，只有用户书面批准推导规则、登记派生来源并完成至少 20 只已知停牌股票人工核对后才可采用。

### 3.6 `st_status`

标准列：

```text
ts_code,start_date,end_date
```

- 主键：`ts_code + start_date`；一次 ST 或 *ST 连续状态区间一行。
- 区间采用左闭右开：`start_date <= 当日 < end_date`；仍处于 ST 时 `end_date` 留空。
- 同一股票区间不得重叠，沪深两市都要覆盖。
- 只有深市更名轨迹不能代表全市场；沪市缺口未补齐时整表继续阻断。
- 如果由简称变更事件推导，必须记录进入/退出规则、特殊简称处理和人工抽查结果。

### 3.7 `limit_price`

标准列：

```text
trade_date,ts_code,up_limit,down_limit
```

- 主键：`trade_date + ts_code`；每股票每交易日一行，单位人民币元。
- 中证 500 历史有效成分逐日覆盖率至少 95%。
- 优先使用供应商直接提供的历史涨跌停价。
- 若推导，必须由用户书面批准，并覆盖 ST/*ST、科创板、创业板改革、新股无价格限制窗口、恢复上市/股改等特殊日和交易所舍入规则。
- 推导值启用前，至少抽取 1% 的可获得真实值对账；异常和无法覆盖的特殊日必须列入保留事项。

## 4. 人工签署分两次完成

### 4.1 第一次：许可与入库授权

目的：确认“有权使用这些数据、PIT 口径可接受、允许项目把登记表改为批准状态”。这是完整真实导入的前置条件，不等同于确认数据质量已经通过。

操作顺序：

1. Codex 对 7 个文件做只读预检：表头、类型、主键、空值、日期、区间、覆盖和跨表键关系。
2. 在 7 个 `reports/data_sources/*_review.md` 中补全实际供应商、版本、接口/批次、单位、PIT 语义、证据位置和预检结果。
3. 用户填写 `reports/data_sources/templates/真实PIT许可签署清单模板.md` 的 A 部分，逐表选择“批准 / 保持阻断”，并签名和日期。
4. 只有 7 张必需表全部明确批准后，用户授权 Codex 将对应登记项改为：

   ```yaml
   license_status: approved_for_research
   pit_ready: true
   ```

5. Codex 按实际证据更新 `provider`、`provider_version`、`endpoint_or_file`、`history_start`、`units`、`evidence_path`；不得保留 `pending` 或虚构版本。
6. 用户授权设置全局字段：

   ```yaml
   review_status: approved
   reviewed_by: "用户本人确认的姓名或审查标识"
   reviewed_at: "带时区的确认时间"
   ```

7. Codex 计算更新后 `config/data_source_registry.yaml` 和冻结研究协议的 SHA-256。用户在模板 B 部分核对并确认哈希后，才开始完整导入。

程序在 11 张核心表全部出现时会硬性要求上述全局签署字段，因此不能由 Codex先导入、事后再补签。

### 4.2 第二次：审计验收与数据冻结

目的：确认“实际导入的这一批数据通过了质量/PIT 门禁，可以冻结为研究输入”。

只有以下项目全部满足，用户才签模板 C 部分：

- [ ] `data_manifest.json` 的 `mode` 为 `real`。
- [ ] `import_gate_status` 为 `ready_for_quality_audit`。
- [ ] manifest 中的 source registry 哈希与当前登记表一致。
- [ ] `verify-data --mode real` 成功。
- [ ] `data_quality_issues.csv` 无 `blocking`。
- [ ] `pit_timing_audit.csv` 非空且所有 `passed=true`。
- [ ] `financial_revision_audit.csv` 非空且所有 `passed=true`。
- [ ] `survivorship_audit.csv` 非空且所有 `passed=true`。
- [ ] `universe_coverage.csv` 非空且所有 `passed=true`，最低覆盖率不低于 0.95。
- [ ] `benchmark_alignment.csv` 非空且所有 `passed=true`。
- [ ] `data_gate_summary.json` 的 `status` 为 `passed`，`blocking_reasons` 为空。
- [ ] 月度标签严格满足 `signal_date < execution_date <= label_end_date < availability_date`。
- [ ] 月度标签不重叠，且任何标签日期都早于最终留出期起点 2024-01-01。
- [ ] 最终标准目录、登记表、研究协议和门禁报告的 SHA-256 已写入签署页。
- [ ] 更正批次使用新目录，不覆盖旧原始批次。

签署后任何一项发生变化——包括数据文件、映射、登记表、研究协议、覆盖规则或留出期——原签署立即失效，必须新建批次、重跑门禁并重新签署。

## 5. 建议的实际执行流程

### 步骤 0：先保留原件和证据

创建新的日期化目录，不复制凭据，不覆盖旧批次。七张表和已有四张表最终要在同一 `source` 目录内，供完整导入读取。

### 步骤 1：只读预检

把 7 张表交给 Codex 后，预检至少输出：文件哈希、行列数、日期范围、主键重复、必填空值、单位换算记录、区间重叠、历史成员覆盖和抽样记录。预检失败时先修数据，不签 `pit_ready`。

### 步骤 2：完成第一次人工签署

复制签署模板为带日期的新文件，例如：

```text
reports/data_sources/signoff_sheet_YYYYMMDD.md
```

不要覆盖或继续签署 `signoff_sheet_20260719.md`；其中的研究协议哈希已经因后续阶段 4–6 配置调整而过期，该文件只保留为历史记录。

### 步骤 3：完整真实导入

以下命令使用新目录；`$StandardDir` 必须不存在或为空：

```powershell
$env:PYTHONPATH = 'src'
$SourceDir = 'data/staging/real-pit-YYYYMMDD/source'
$StandardDir = 'data/standard/real-pit-YYYYMMDD'

.venv\Scripts\python.exe -m ashare_factor_research.main import-data `
  --source-dir $SourceDir `
  --output-dir $StandardDir `
  --format parquet `
  --mode real `
  --source-registry config/data_source_registry.yaml
```

成功判据：退出码为 0，`import_gate_status=ready_for_quality_audit`。如果输出目录已有内容，不要删除或覆盖；改用新的批次名。

### 步骤 4：哈希与质量门禁

```powershell
$GateDir = 'reports/gate/real-pit-YYYYMMDD'

.venv\Scripts\python.exe -m ashare_factor_research.main verify-data `
  --data-dir $StandardDir `
  --mode real

.venv\Scripts\python.exe -m ashare_factor_research.main quality-check `
  --data-dir $StandardDir `
  --output-dir $GateDir `
  --mode real `
  --fail-on-blocking `
  --required-start 2015-01-01 `
  --index-code 000905.SH `
  --min-coverage 0.95
```

成功判据：两个命令退出码均为 0，门禁汇总状态为 `passed`。警告必须逐条解释；不得通过全局静默警告或删除失败行来“过门禁”。

### 步骤 5：生成严格月度样本

```powershell
$MonthlyDir = 'outputs/monthly/real-pit-YYYYMMDD'

.venv\Scripts\python.exe -m ashare_factor_research.main build-monthly-sample `
  --data-dir $StandardDir `
  --output-dir $MonthlyDir `
  --mode real `
  --project-config config/project_config.yaml `
  --factor-config config/factor_config.yaml `
  --backtest-config config/backtest_config.yaml `
  --required-start 2015-01-01 `
  --final-holdout-start 2024-01-01 `
  --min-coverage 0.95
```

成功判据：退出码为 0，月度标签和四类专项审计仍全部通过。此时仍不能查看或利用最终留出期结果调整候选模型或门槛。

### 步骤 6：完成第二次人工签署并冻结

Codex 汇总 manifest、审计、协议和标准目录哈希；用户核对模板 C 部分并签署。冻结后才允许阶段 4–6 使用该批真实输入。通过工程 sample 或合成恢复测试不等于真实数据已获批准。

## 6. 登记表填写示例

下面只是字段结构示例，不能原样照抄 `example_vendor`：

```yaml
daily_basic:
  source_type: local_file
  provider: example_vendor
  provider_version: "terminal-or-api-version"
  endpoint_or_file: "endpoint-name; export batch YYYYMMDD"
  license_status: approved_for_research
  pit_ready: true
  history_start: "2015-01-01"
  units:
    pe_ttm: ratio
    pb: ratio
    total_mv: CNY
    turnover_rate: ratio
    net_mf_amount: CNY
  evidence_path: ../reports/data_sources/daily_basic_review.md
```

批准前检查：`provider_version` 不能是 `pending`，`units` 不能为空，`history_start` 不得晚于 2015-01-01，`evidence_path` 必须实际存在。

## 7. 允许的人工签署方式

优先级从高到低：

1. 手写或合规电子签名文件：原件由用户保管，仓库保存脱敏摘要、签署日期、原件位置和哈希。
2. 用户本人直接编辑签署页：填写姓名/审查标识、日期和明确结论。
3. 用户在当前 Codex 任务中逐字确认签署声明，并明确授权 Codex把相同内容写入签署页。仓库只留必要确认摘要，不保存完整会话日志。

不接受：Codex推测用户名、代填“已同意”、根据文件已存在自动批准、把 Kimi/Codex起草人当作审查人，或用测试通过替代许可确认。

## 8. 目前的直接下一步

1. 确定 7 张表分别从哪个许可源导出；同一供应商可以覆盖多表。
2. 按本指南第 2 节准备许可和字段证据。
3. 按模板列名导出数据，先不要改登记表为 `approved`。
4. 将文件位置告诉 Codex，由 Codex做只读预检并回填 7 份审查文件。
5. 预检通过后，用户完成第一次签署；随后按第 5 节导入、审计和第二次签署。


# P2：科研平台化与 Research Package 实施计划

## 1. 目标

在不引入在线服务和大型 MLOps 的前提下，为 A-LLM 增加轻量、离线、版本化的研究注册层，使数据、特征、实验、模型和产物可追踪，并能向 PFROS 输出可验证的 Research Package。

## 2. 前置条件与并行边界

- P0 必须先完成；
- schema 与目录设计可与 P1 并行；
- 真实结果包的验收必须等待 P1 完成；
- 本阶段不改变现有数据、因子和回测计算逻辑；
- 不把 A-LLM 包直接加入 PFROS 的 `PYTHONPATH`。

## 3. 建议模块

计划中的逻辑模块如下，具体路径在实现任务中经代码设计审查后冻结：

```text
research_platform/
├── dataset_registry
├── feature_registry
├── experiment_registry
├── artifact_registry
├── package_schema
├── package_exporter
└── package_validator
```

第一版优先使用项目现有 YAML/CSV/JSON/Parquet 和文件 manifest；除非出现明确的并发、规模或查询瓶颈，不引入服务化 Feature Store。

## 4. 工作包

### P2-W1：Dataset Registry

记录：

- dataset ID、schema version、mode；
- 来源、许可和再分发限制；
- 时间范围、资产范围、粒度和主键；
- manifest、内容哈希和生成时间；
- PIT/质量/覆盖/冻结状态；
- 受限数据路径不得写入可发布 manifest。

### P2-W2：Feature Registry

每个特征至少记录：

- `feature_id`、版本、公式和输入字段；
- 粒度、时间戳、可用时点和滞后规则；
- 去极值、标准化、中性化和缺失处理；
- 数据集依赖和代码实现版本；
- 覆盖率门槛、单位、方向和已知风险。

第一版是“研究特征注册表＋离线快照”，不是在线训练/推理服务。

### P2-W3：Experiment Registry

固定：研究问题、假设、数据版本、特征集、模型、参数空间、种子、时间窗口、指标、成本、对照组、消融、晋级门槛和状态。实验失败也必须登记。

### P2-W4：Artifact Registry

登记模型文件、预测、指标、图表、审计、报告和日志摘要的路径、哈希、schema、生成者和依赖。产物不可原地覆盖，新结果使用新 `run_id`。

### P2-W5：Research Package v1

最小合同至少包含：

```text
package_id
schema_version
producer
run_id
code_commit / source_tree_hash / diff_hash
config_hash
dataset_manifest_hash
research_question
universe
signal_time / execution_time / target_window
sample_period / OOS_period / final_holdout
cost_and_slippage_assumptions
data_gate_status
model_promotion_status
metrics_and_uncertainty
ablation_and_robustness
limitations
artifact_manifest
human_approval_status
```

### P2-W6：Exporter 与 Validator

- Exporter 只封装现有 run，不重算研究；
- Validator 检查 schema、哈希、必需证据、成熟度和许可输出类别；
- sample 包只能达到 `engineering_valid`；
- 未冻结真实数据或 OOS 不足的包不得达到 `data_accepted`/`market_evidence_eligible`；
- 任一文件篡改必须导致验证失败。

### P2-W7：兼容与 Adapter 合同

- 包 schema 独立于 Python 包版本；
- 至少支持当前 major version；是否兼容前一版本由实现评审决定；
- PFROS 使用文件 Adapter，测试使用内存 Adapter；
- 两个 Adapter 共享同一合同用例。

## 5. 测试计划

- dataset/feature/experiment ID 唯一与版本不可变；
- 哈希篡改、文件缺失、schema 漂移和路径泄漏失败；
- sample/real 成熟度不会误判；
- 脏工作树必须绑定 diff/source-tree 哈希或被拒绝；
- 受限数据和绝对本地路径不进入可发布包；
- exporter 不触发研究重算；
- package 被接受后不能原地覆盖。

## 6. 产物

- 四类 registry schema 与示例；
- Research Package JSON Schema；
- exporter、validator 和 Adapter 合同；
- sample 包夹具；
- 实现与兼容 ADR；
- 测试与验收报告。

## 7. 验收标准

- [ ] 相同 run 可产生稳定、可复核的包 manifest；
- [ ] 篡改任一文件后验证失败；
- [ ] sample 包只能达到工程有效；
- [ ] 未签署或门禁失败的 real 包无法晋级；
- [ ] PFROS 不依赖 A-LLM 内部目录或 Python 模块；
- [ ] 包不包含授权原始数据、凭据或个人金融 P2/P3 数据；
- [ ] registry 不复制现有 pipeline 的业务逻辑；
- [ ] 完整回归通过。

## 8. 暂不实施

Feast、在线/offline 一致性服务、模型在线部署、实时特征、云对象存储、自动训练编排和模型自动晋级均不属于 v1。

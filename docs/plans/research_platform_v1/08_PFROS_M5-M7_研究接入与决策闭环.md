# PFROS M5–M7：A-LLM 接入与决策闭环实施计划

## 1. 目标

在不耦合仓库、不泄露个人金融明细、不自动执行交易的前提下，使 PFROS 能验证 A-LLM Research Package、比较研究候选与脱敏持仓、记录人工决策并复盘结果。

## 2. 双门禁

启动 M5 真实接入必须同时满足：

- A-LLM：P0 冻结完成，P1 有可接受真实 run，P2 包合同通过；
- PFROS：M3 持仓/估值/对账完成，M1 隐私与恢复门禁有效。

sample 包可提前用于合同测试，但只能达到 `engineering_valid`。

## 3. M5：Research Package 接入

### M5-W1：ResearchLabPort

PFROS 只通过稳定接口读取包：

```python
class ResearchLabPort:
    def inspect(self, package_ref: str): ...
    def load(self, package_ref: str): ...
```

生产使用文件 Adapter，测试使用内存 Adapter。调用者不读取 A-LLM 内部目录或 Python 类。

### M5-W2：Research Registry

统一验证：

- schema version；
- 文件清单和 SHA-256；
- run、代码、配置、数据 manifest 和时间截点；
- sample/real、PIT、OOS、成本、消融、过拟合和留出期；
- 许可输出类别与个人数据边界；
- 成熟度等级和拒绝原因。

### M5-W3：sample 合同验收

篡改、缺文件、schema 漂移、绝对路径、未冻结数据和 sample 冒充 real 均必须失败或降级。

### M5-W4：真实包验收

只有 A-LLM 达到对应门禁，PFROS 才能把包标为 `data_accepted` 或 `market_evidence_eligible`。PFROS 独立复核，不只读取报告结论文本。

## 4. 脱敏持仓研究视图

PFROS 可输出：

```text
portfolio-view/<snapshot_id>/
├── manifest.json
├── holdings.csv
├── constraints.json
└── benchmark.json
```

仅包含 as-of、一致的 instrument ID、数量或权重、允许公开的约束和基准。不得包含机构名、账号、持有人、原始流水、现金备注、决策私密文本或凭据。

需要显式 `instrument_id ↔ ts_code` 映射、有效期和失败队列。

## 5. M6：Decision Candidate 与复盘

### 工作块

- Research Card/Decision schema；
- Decision Journal 的 record/approve/review；
- 研究候选与当前持仓的权重、行业、因子、集中度和风险差异；
- 候选方案的证据、风险、失效条件、数据截点和适用边界；
- 人工批准、拒绝、延期或保留原方案；
- 真实执行事实从券商/银行重新导入；
- 复盘当时信息、候选、人工判断、实际执行和结果。

`approve` 不能写 Financial Book，研究候选不能直接产生金融事件。

## 6. 反馈学习边界

PFROS 可以记录研究候选、人工决定和结果，但不能自动把个人结果作为 A-LLM 标签：

- 人工选择造成选择偏差；
- 个人持仓规模和约束与研究股票池不同；
- 后续结果可能受未记录现金流和外部事件影响；
- 任何训练反馈都要另立数据合同、因果/统计审查和脱敏门禁。

## 7. M7：运行、只读 AI 与加固

### 工作块

- Read Model 与静态日报/月报；
- 失败可重试且不重复入账的运行编排；
- 备份、导入、对账、研究成熟度和阻断健康状态；
- 本地只读 Dashboard；
- 只读 AI 助手：检索、解释、异常摘要和文档；
- 隐私、恢复、灾难重建和长期迁移审计。

AI 不能批准、入账、修改历史事实或执行交易。

## 8. 验收标准

- [ ] 两个仓库可独立安装、测试和发布；
- [ ] 两个 Adapter 共享合同测试；
- [ ] sample/real 成熟度不误判；
- [ ] 包任一文件篡改后验证失败；
- [ ] 持仓视图不含 P2/P3 字段；
- [ ] instrument 映射和 as-of 规则通过测试；
- [ ] DecisionCandidate 无写事实权限；
- [ ] 人工批准与执行事实分离；
- [ ] 复盘可追溯当时信息和版本；
- [ ] AI 只有脱敏只读上下文；
- [ ] 备份恢复与灾难重建演练通过。

## 9. 暂不实施

自动调仓、券商写接口、资金转移、实时 Agent 决策和根据单次个人结果自动训练均不在本路线内。若未来授权，必须单独引入 `trading-safety-review` 和生产变更门禁。

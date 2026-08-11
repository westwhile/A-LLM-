# 模块 16：隐私、安全与 Human-in-the-loop 计划

> 优先级：治理主线；从 PFROS 设计第一天启用。Human-in-the-loop 是核心架构，不是最后附加的确认按钮。

## 1. 中央目标

让 A-LLM 的研究证据进入 PFROS 后，只能形成可审计的决策候选；个人金融事实、批准、执行和复盘保持分离，任何 AI 都不能绕过人工授权。

## 2. 数据分级

| 等级 | 示例 | 默认处理 |
|---|---|---|
| Public research | 公开行情、论文、公开公告 | 按许可和 PIT 管理 |
| Internal research | 特征、模型、未公开报告 | 本地最小权限、内容哈希 |
| Personal sensitive | 持仓、现金流、负债、目标 | PFROS 内加密/脱敏，最小披露 |
| Credential/identity | 账号、令牌、身份证明 | 不进入 A-LLM/模型 prompt/日志 |

## 3. 受控闭环

```text
A-LLM Research Package
  → schema/hash/maturity 验证
  → PFROS Research Registry
  → 与脱敏持仓/约束比较
  → DecisionCandidate
  → 人工审阅与明确批准/拒绝
  → 外部人工执行
  → 银行/券商事实重新导入账本
  → 复盘（观察性反馈）
```

研究、建议、批准、执行、事实和反馈使用不同对象与权限。

## 4. 安全实现块

- 本地密钥管理、静态/传输加密、备份和恢复演练；
- RBAC/最小权限、审计日志、不可变批准记录；
- prompt/log 脱敏、外部模型数据边界和保留策略；
- Research Package 签名/哈希和 replay 防护；
- 模型/Agent 工具白名单、预算、超时和 fail-closed；
- 模拟篡改、提示注入、恶意包和越权动作。

## 5. Federated Learning / Differential Privacy

- 单人本地 PFROS 通常不需要联邦学习；只有多设备/多参与方联合训练需求才评估；
- 联邦学习不等于隐私保证，仍需威胁模型、安全聚合和泄漏评估；
- 差分隐私需定义邻接关系、epsilon/delta、效用损失和组合预算；
- 在没有明确共享任务前，不因技术新颖度进入实现。

## 6. Human-in-the-loop 验收

- UI/CLI 明示证据等级、适用范围、不确定性、成本和风险；
- 缺少批准、包校验失败或成熟度不足时不能进入执行候选；
- AI 建议与人工决定同时保存，拒绝/修改也进入复盘；
- 紧急停止、权限撤销和恢复流程经过演练；
- 个人执行反馈不得未经因果/选择偏差审查直接训练模型。

## 7. 实验与红队场景

- sample 包伪装成 real；
- artifact 被替换但文件名不变；
- prompt 注入要求读取账号或绕过批准；
- Agent 试图调用交易/外部消息工具；
- 重放旧批准用于新候选；
- 日志或导出包含敏感字段。

## 8. 退出门

- 敏感字段不会进入 A-LLM 或外部模型；
- 包篡改、成熟度不足和无批准均 fail-closed；
- 人工批准不可由 AI/Agent 伪造或复用；
- 账本可恢复、对账和重放；
- 安全事件有审计、撤销、恢复和披露路径。

## 9. 阅读路线

| 资料 | 重点 | 来源状态 |
|---|---|---|
| [McMahan et al. (2017), Communication-Efficient Learning of Deep Networks from Decentralized Data](https://proceedings.mlr.press/v54/mcmahan17a.html) | 联邦平均与分布式训练边界 | AISTATS/PMLR 原始页面已核验 |
| 差分隐私权威教材/原始论文 | 隐私预算与组合 | 具体方案出现后再核验最小来源集 |
| 项目 Research Package 与 PFROS 门禁 | 人工决策和事实边界 | 本地权威合同 |

学习产物：数据流/威胁模型、一份权限矩阵、六个红队测试、一次备份恢复演练和一份人工批准记录样例。

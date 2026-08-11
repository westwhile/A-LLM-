# 模块 10：金融知识图谱与 GNN 计划

> 优先级：C；只有供应链/行业/事件关系具有可验证的时点版本后，图神经网络才有研究意义。

## 1. 中央问题

事件对供应商、客户、竞争者和行业的传播关系能否相对于行业分类和人工邻接基准，提供可解释、PIT-safe 的横截面预测增量？

## 2. 图谱合同

```text
Node: company / security / industry / product / policy / event
Edge: supplies / customer_of / competes_with / belongs_to / affected_by
Fields: valid_from, valid_to, first_seen_at, source_id, confidence, reviewer
```

关系必须同时区分业务有效期和系统首次可得时间。当前已知的供应链不能回填到未知的历史时期。

## 3. 方法阶梯

### M0 关系数据与规则传播

- 先做小规模人工验证的公司—行业—供应链图；
- 一跳/两跳邻居事件加权和行业基准；
- 比较错误关系、方向、重复边和关系失效。

### M1 图表示

- node2vec/矩阵分解作为简单基准；
- GraphSAGE 适合随时间新增公司/节点的归纳表示；
- GCN/GAT 仅在图稳定性和样本量支持时比较。

### M2 LLM + 图谱

- LLM 只提出候选实体/关系；高影响关系需来源和人工复核；
- RAG 检索图谱快照并输出证据路径；
- 不让 LLM 生成的关系未经核验直接成为历史真值。

## 4. 实验设计

- link prediction 与事件传播预测分开评估；
- 训练/验证/测试按时间切图，禁止使用未来边；
- 基准：行业哑变量、静态邻接、随机图、度数匹配图；
- 消融：边类型、方向、时间衰减、来源置信度和文本表示；
- 指标：关系精确率/召回、路径可解释率、OOS IC/组合增量和对映射错误的敏感性。

## 5. 实现块

1. schema 与图谱快照 manifest；
2. 来源证据和人工审查队列；
3. 时间切片图查询；
4. 规则传播/行业基准；
5. GraphSAGE/GCN 候选模型；
6. 预测、路径和错误案例报告。

## 6. 退出门

- 关键边的来源、有效期、首次可得时间可追溯；
- 时间切图无未来边；
- 图模型优于行业/规则传播基准；
- 结果不只是度数、规模或流动性暴露；
- 图谱维护成本可接受，否则停止 GNN，保留小型知识层供 RAG 使用。

## 7. 阅读路线

| 资料 | 重点 | 来源状态 |
|---|---|---|
| Kipf & Welling, *Semi-Supervised Classification with Graph Convolutional Networks* | GCN 基础 | 用户提供线索；正式引用前核验 ICLR/OpenReview |
| [Hamilton, Ying & Leskovec (2017), GraphSAGE](https://proceedings.neurips.cc/paper/2017/hash/5dd9db5e033da9c6fb5ba83c7a7ebea9-Abstract.html) | 归纳节点表示 | NeurIPS 原始页面已核验 |
| Wu et al. (2020), GNN survey | 方法全景 | 用户提供线索；正式引用前核验期刊与 DOI |

学习产物：一个 20–50 家公司的时点图、10 条人工证据路径、一个随机图负对照和一份未来边泄漏测试。

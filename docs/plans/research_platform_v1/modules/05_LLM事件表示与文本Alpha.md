# 模块 05：LLM 事件表示与文本 Alpha 计划

> 优先级：B；对应 P4；核心创新候选，但必须晚于文本数据许可、PIT、去重和结构化 ML 基准。

## 1. 中央问题

在传统因子、市场状态和结构化事件标签已经纳入后，金融文本表示是否仍提供稳定、独立、成本后成立的样本外增量？

本模块不以“用了 LLM”为贡献，而以信息增量、时点纪律、可复现性和失败条件为贡献。

## 2. 数据门禁

- 明确新闻/公告来源许可、转载限制、保存期限和可发布字段；
- 保存 `published_at`、`first_seen_at`、抓取时点、修订时点和来源；
- 同文转载、标题改写、同事件多稿、盘中/盘后必须去重和分时；
- 公司实体映射、股票代码历史和事件影响窗口须人工抽检；
- 文本缺失不是中性信号，需单独建模 coverage。

## 3. 表示阶梯

### M0 现有透明标签

- event type、sentiment、confidence、source quality；
- 保留人工标签子集和规则基准；
- `sentiment × confidence` 只是基准，不是假定真结构。

### M1 金融 Embedding

- 冻结模型和 tokenizer 版本；
- 文档级/事件级聚合、PCA 或训练折内降维；
- 比较通用中文 Embedding、金融情绪模型和无文本基准；
- FinBERT 是金融情绪研究基线，不自动适配中文 A 股，也不等于通用语义 Embedding。

### M2 RAG 事件理解

- 检索仅使用事件时点前可得的公司公告、财报和历史事件；
- 输出必须携带引用片段、检索时间和知识库版本；
- 以实体解析/事件要素/收益增量为评价目标，不能只评主观“回答更好”。

### M3 多 Agent / 时间序列事件模型

- Event、Financial Impact、Priced-in、Risk 可作为独立可测试角色；
- 聚合器必须保留分歧，不能用多数投票掩盖不确定性；
- Temporal Transformer/TFT 只有在事件序列覆盖足够且简单聚合基准稳定后进入。

### M4 微调

- 先论证训练集版权、中文金融任务、算力、复现和外部验证；
- BloombergGPT 主要作为设计阅读，不是可直接依赖的开放权重；
- FinGPT/其他权重实施前单独核验许可证、版本和数据来源。

## 4. 预注册实验

| 对照 | 新增信息 | 主要检验 |
|---|---|---|
| 传统结构化特征 | 无文本 | 基准预测与组合 |
| +结构化事件标签 | 标签 | 标签的独立增量 |
| +通用 Embedding | 语义向量 | 表示增量 |
| +金融模型表示 | 金融域表示 | 域适配增量 |
| +PIT RAG | 历史知识 | 检索增量与引用正确率 |

主要指标：OOS Rank IC、预测增量、成本后组合差异、跨期稳定性；质量指标：实体/事件标注一致性、去重误差、引用可追溯率、覆盖率。

负对照：发布时间后移、文本随机配股、打乱事件顺序、仅标题、去除公司名、未来知识库检索检测。

## 5. 实现块

1. `TextDatasetManifest` 与许可/PIT gate；
2. 文档规范化、去重、实体映射和人工 gold set；
3. 可复现 embedding cache 与模型卡；
4. 事件聚合和 feature-store 注册；
5. RAG 的 snapshot retriever、引用和时点审计；
6. 结构化/文本/检索消融与 Research Package 输出。

## 6. 退出门与停止规则

- gold set 的实体、事件和去重质量达到预注册门槛；
- 文本时点和知识库快照无未来信息；
- 文本增量在结构化基准之上成立，而非只与空模型比较；
- prompt/model 尝试全部登记；
- 若覆盖不足、许可不清或增量不稳定，停止 RAG/Agent/微调，保留标签基准或形成负结果。

## 7. 阅读路线

| 资料 | 用途 | 来源状态 |
|---|---|---|
| [Araci (2019), FinBERT](https://arxiv.org/abs/1908.10063) | 金融情绪域适配基线 | 原始预印本已核验 |
| [Wu et al. (2023), BloombergGPT](https://arxiv.org/abs/2303.17564) | 金融/通用混合预训练与评测 | 原始预印本已核验 |
| [Yang, Liu & Wang (2023), FinGPT](https://arxiv.org/abs/2306.06031) | 数据中心化与轻量适配思路 | 原始预印本已核验 |
| [Lewis et al. (2020), RAG](https://proceedings.neurips.cc/paper_files/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html) | 参数/非参数记忆与检索评估 | NeurIPS 原始页面已核验 |
| [Yao et al., ReAct](https://openreview.net/pdf?id=WE_vluYUL-X) | 推理与工具调用框架 | ICLR 2023 原始页面已核验 |
| Lim et al., Temporal Fusion Transformers | 多步时序与可解释变量选择 | 用户提供线索；正式引用前核验期刊/DOI |

学习产物：50–100 条人工标注规范、一次标签 vs Embedding 小实验、一个未来检索反例和一份模型/许可选择记录。

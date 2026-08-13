# R1 LLM Event Factor 工程实施与人工闸门

> 当前状态：`engineering_ready / research_blocked`
>
> 更新日期：2026-08-13
>
> 适用范围：R1 的本地、离线、可审计工程底座。本文不代表真实文本已获许可、研究协议已冻结、模型已选定或 Alpha 已成立。

## 1. 已完成的 AI 工程块

| 工程块 | 实现 | 完成边界 |
|---|---|---|
| 文本数据准备 | `llm/text_dataset.py` | 强制 `publish_time` 与 `available_time`，保存原文哈希、规范化哈希、去重组、实体状态和质量报告 |
| 去重与复核 | `find_near_duplicate_candidates` | 精确重复只分组、不自动删除；近重复只生成候选，不替代人工裁决 |
| 实体映射队列 | `entity_review_queue.csv` | 映射失败或未经验证的证券进入待审队列，不进入默认 signal-ready 数据 |
| 规则透明基准 | `rule_lexicon.py`、`rule_baseline.py` | 词典版本、哈希、标签分布和输入 manifest 可审计 |
| 标签缓存治理 | `llm/cache.py` | cache key 覆盖原文、模型、prompt、标签 schema 和词典/模型配置指纹 |
| Gold Set 候选抽样 | `build_stratified_review_queue` | 按年份、事件、情绪和置信区间分层；最终标签仍为人工职责 |
| Embedding adapter | `llm/embedding.py` | 模型、权重 revision、tokenizer、预处理、pooling、维度和许可状态全部进入缓存指纹 |
| 表示统一接口 | `llm/representation.py` | 规则标签、LLM 标签、Embedding 和未来 PIT RAG 统一交付 `TextRepresentationArtifact` |
| 公司—信号日聚合 | `llm/aggregation.py` | 只使用显式 cutoff 前事件；精确去重；文本缺失保持为缺失而非自动中性 |
| 固定线性评价器 | `llm/evaluator.py` | base 与 base+text 使用相同 OOS 样本、训练窗和 purge/embargo；不在 R1 内调收益模型 |
| 负向对照 | `build_negative_control_features` | 支持安全的事件时间后移和同日证券映射置换，不修改目标收益 |
| R1 协议合同 | `llm/r1_protocol.py` | 协议、试验、指标、负向对照、预算和人工签署可校验；草稿不能运行正式评价器 |

## 2. 当前实验阶梯状态

| 阶段 | 工程状态 | 科研状态 |
|---|---|---|
| R1-E0 无文本 | 固定线性 evaluator 已实现 | 等待你冻结协议、指标和数据 |
| R1-E1 规则/词典 | 已形成可运行 CLI 与 artifact | 等待真实文本许可、PIT/实体/去重复核及 OOS 检验 |
| R1-E2 结构化 LLM 标签 | schema、adapter、cache、审核队列和 artifact 已实现 | 等待你选择模型/API、本地权重、标注指南与 gold set 门槛 |
| R1-E3 Embedding | 模型无关 adapter、cache、向量展开和聚合已实现 | 等待你选择中文通用/金融模型并审查权重与许可证 |
| R1-E4 PIT RAG | 未提前实现 | 按停止规则，只有 E2/E3 出现稳定增量且知识库许可清楚后启动 |
| R1-E5 微调 | 未提前实现 | 只有前级通过且训练集版权、算力与外部验证方案明确后立项 |

R1-E4/E5 暂不实现是研究设计要求，不是工程遗漏。提前建设会增加试验自由度，并可能把未来知识或未经许可语料引入历史实验。

## 3. 输入数据合同

`prepare-text-events` 至少需要：

```text
event_id
stock_code
title
content
source
publish_time
available_time
```

其中 `available_time` 必须由经审查的采集/PIT 规则生成，程序不会用 `publish_date` 自动代替。推荐额外提供：

```text
first_seen_time
revision_time
source_url
language
license_category
entity_mapping_status
```

## 4. CLI 流程

以下命令均在 `A-LLM-/` 下执行。

### 4.1 文本准备与审计队列

```powershell
.venv\Scripts\python.exe -m ashare_factor_research.main prepare-text-events `
  --input data/approved_text/news_raw.csv `
  --stock-registry data/approved_text/stock_registry.csv `
  --output-dir outputs/r1/text_preparation
```

产物：

- `prepared_text_events.csv`
- `near_duplicate_candidates.csv`
- `entity_review_queue.csv`
- `text_quality_report.json`

### 4.2 生成 R1-E1 规则基准

```powershell
.venv\Scripts\python.exe -m ashare_factor_research.main label-events `
  --input data/approved_text/news_raw.csv `
  --output outputs/r1/rule_labels.csv `
  --cache outputs/r1/rule_label_cache.jsonl `
  --artifact-dir outputs/r1/rule_baseline
```

### 4.3 包装统一文本表示

```powershell
.venv\Scripts\python.exe -m ashare_factor_research.main build-r1-label-representation `
  --prepared-events outputs/r1/text_preparation/prepared_text_events.csv `
  --labels outputs/r1/rule_labels.csv `
  --output-dir outputs/r1/rule_representation `
  --representation-id R1-E1-RULE-V1 `
  --representation-type rule_labels `
  --model-revision rule_lexicon_v1 `
  --model-license-status internal_only `
  --text-manifest data/approved_text/text_dataset_manifest.json `
  --trial-id R1-E1
```

CLI 固定输出 `draft`。它不会因为文件生成成功就把表示标为 `accepted` 或 `frozen`。

### 4.4 校验研究协议

```powershell
.venv\Scripts\python.exe -m ashare_factor_research.main validate-r1-protocol `
  --protocol config/r1_protocol.template.yaml `
  --receipt outputs/r1/r1_protocol_receipt.json
```

模板当前是 `draft`，`research_ready=false`。你需要确定数据、切分、最终留出、指标、试验预算和模型参数后，完成人工签署才能改为 `frozen`。

### 4.5 运行固定评价器

```powershell
.venv\Scripts\python.exe -m ashare_factor_research.main run-r1-fixed-evaluator `
  --protocol config/r1_protocol.frozen.yaml `
  --panel outputs/r1/evaluator_panel.csv `
  --base-features size,value,momentum `
  --text-features text_sentiment_score,text_coverage `
  --output-dir outputs/r1/evaluation
```

如果协议仍是草稿，该命令会拒绝运行。评价面板的 `signal_date`、`label_end_date`、`ts_code`、目标收益和所有特征必须完整；缺失文本需要显式 coverage 和预注册填充方案，评价器不会自动把缺失填成 0。

## 5. 仍需你决定的科研闸门

1. 批准哪个历史文本数据源、许可范围、保存期限和可发表字段；
2. 冻结 `available_time` 规则、实体映射来源和近重复裁决标准；
3. 完成人工 gold set 的标注规范、复核者和通过阈值；
4. 选择 E2 模型和 E3 中文 Embedding 候选，并核验模型权重/服务版本及许可证；
5. 冻结 R1 evaluator、主要指标、试验预算、停止规则和最终留出；
6. 决定是否支持 E3/E4 晋级，并对最终经济机制和替代解释负责。

## 6. 验收口径

工程验收只证明：接口、哈希、缓存、PIT 防线、artifact、负向对照和合成测试可运行。

它不证明：

- 真实文本已被授权；
- 实体和重复事件已经人工复核；
- FinBERT、FinGPT 或任一 Embedding 适合中文 A 股；
- 文本表示有真实 OOS Alpha；
- 可用于 PFROS 的实际投资决策。

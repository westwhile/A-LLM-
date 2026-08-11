# 模块 12：金融基础模型与时间序列 Foundation 计划

> 优先级：C；当前只评估和适配已有模型，不训练金融基础模型，不把“大模型”作为默认升级方向。

## 1. 中央问题

预训练金融语言模型或时间序列基础模型，在严格避免预训练语料/评测泄漏并控制算力成本后，是否相对于任务专用简单模型提供可重复的 OOS 增量？

## 2. 两条独立支线

### A. 金融语言基础模型

- 任务限定为情绪、实体、事件、检索或表示，不把所有任务混成聊天能力；
- 检查模型权重、许可证、训练数据时期和中文能力；
- BloombergGPT 用于理解设计，不能假定可获得同等模型/语料；
- 微调只有在冻结基准、合法标注和外部验证集齐全后进入。

### B. 时间序列 Foundation Model

- Chronos、TimesFM、Lag-Llama 首先作为 zero/few-shot forecasting 候选；
- 金融收益低信噪比与公共 benchmark 不同，不能外推官方结果；
- 训练语料可能包含待评测市场/时期，必须审计 contamination；
- 预测值仍需进入既有组合和回测门，不能直接作为交易信号。

## 3. 方法阶梯

1. 朴素 seasonal/last value、ARIMA/ETS、线性/树模型；
2. 任务专用深度模型；
3. foundation zero-shot；
4. 冻结 backbone + 线性头/轻量适配；
5. 只有充分增量后才考虑 LoRA/继续预训练；
6. 从零训练大模型属于范围外，需独立资源与治理立项。

## 4. 实验与评估协议

- 同一数据切分、预测时点、输入长度和输出 horizon；
- 预测准确、概率校准、推理时间、显存/CPU、可复现和许可同时比较；
- 股票收益、波动、成交量和宏观序列分任务报告；
- zero-shot、few-shot 和 fine-tuned 结果不得混称；
- 负对照：公开 benchmark 复现与本地金融数据反差、未来时期遮蔽、模型预训练截止日不确定性。

## 5. 实现块

1. `FoundationModelCard`：来源、权重、许可、截止日、版本、资源；
2. 统一 forecasting/evaluation adapter；
3. 传统与任务专用基准；
4. zero-shot/few-shot/adapter 评估；
5. contamination、资源和失败报告；
6. 合格表示再注册进 feature store。

## 6. 退出门

- 模型来源/许可和版本可冻结；
- 与强简单基准在完全相同切分比较；
- 污染风险可接受或明确标记证据不足；
- 增量能转化为下游预测/风险价值，而非只在通用 benchmark 好看；
- 资源成本与收益相称，否则保留简单模型。

## 7. 阅读路线

| 资料 | 重点 | 来源状态 |
|---|---|---|
| BloombergGPT / FinGPT | 金融语言域适配 | 原始预印本已在模块 05 核验 |
| [Ansari et al. (2024), Chronos](https://arxiv.org/abs/2403.07815) | 序列量化与预训练概率预测 | 原始预印本已核验 |
| [Google Research, TimesFM](https://research.google/pubs/a-decoder-only-foundation-model-for-time-series-forecasting/) | patched decoder 与 zero-shot | 官方研究页面已核验 |
| [Rasul et al., Lag-Llama](https://arxiv.org/abs/2310.08278) | 滞后协变量与概率预测 | 原始预印本已核验 |

学习产物：一张任务—模型适配表、一次相同切分的 naive/ARIMA/tree/foundation 对比和一份污染/许可审计。

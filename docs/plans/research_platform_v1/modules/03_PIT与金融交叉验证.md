# 模块 03：PIT 与金融交叉验证计划

> 优先级：A；对应 P0、P1、P3。目标是验证标签区间与切分的正确性，不是机械套用 Purged K-Fold。

## 1. 中央问题

当前 `signal_time → execution_time → label_end_time` 是否在所有样本和切分中不重叠、不穿越信息可得时间，并能为结构化 ML 与文本模型提供一致的样本外协议？

## 2. 必须先画出的时间线

```text
feature available_time
    ≤ signal_time
    < execution_time
    ≤ label_start_time
    < label_end_time
```

对每种标签记录：持有期、重叠规则、交易日映射、停牌处理、退市处理和样本归属。

## 3. 方法选择规则

### 非重叠月度标签

若现有月度协议已保证训练标签结束早于验证/测试开始，扩张式 walk-forward 可能已经足够；embargo 不是自动必需项，但必须用区间审计证明。

### 重叠标签或事件窗口

当未来 20 日收益、事件 CAR 窗口或滚动标签跨越切分边界时：

- purge 与测试标签区间重叠的训练样本；
- embargo 的长度由信息/标签传播机制预注册，不凭经验随意调参；
- 对同一公司相邻新闻加入 entity-time 去重或组切分。

## 4. 实现块

1. `LabelInterval`：每行保存起止区间；
2. `SplitManifest`：训练/验证/测试/留出边界和哈希；
3. overlap detector：输出被 purge 的具体样本与原因；
4. purged walk-forward splitter；
5. 可选 purged K-fold，仅用于模型选择，不替代最终时间向前 OOS；
6. 最终留出期单次使用收据。

## 5. 实验与测试设计

- 边界日、节假日、停牌和跨月标签单元测试；
- 人工构造 10 个重叠区间，核对 purge/embargo；
- 置换未来日期、同日成交和财报发布时间，必须 fail-closed；
- 比较原 walk-forward 与 purged 协议的样本损失、指标变化和置信区间；
- 审计特征计算器是否在 split 之前全样本拟合。

## 6. 退出门

- 每个标签都有区间定义和测试；
- 任意 train 样本区间不与 validation/test 区间非法重叠；
- scaler、PCA、Embedding 降维和模型选择只在训练折拟合；
- 最终留出期没有被模型选择、prompt 选择或异常阈值选择访问；
- purge/embargo 选择有理由，样本损失已披露。

## 7. 停止条件

- 如果最小 OOS 月数因 purge 后不足，先缩短候选模型/标签范围，不降低门槛；
- 如果非重叠协议已充分，记录“不增加 embargo”的审计结论；
- 不引入未经检查的第三方 splitter 作为正确性替代。

## 8. 阅读路线

| 资料 | 重点 | 来源状态 |
|---|---|---|
| López de Prado, *Advances in Financial Machine Learning* | purging、embargo 与金融 CV | 用户提供线索；正式引用需核验版次/章节 |
| 本项目 PIT 审计、monthly protocol 与真实 gate 产物 | 当前实现与差距 | 本地现行证据，实施前重跑 |

学习产物：标签区间图、3 个泄漏反例、一个手工 purging 表和一份“何时不需要 embargo”的决策说明。

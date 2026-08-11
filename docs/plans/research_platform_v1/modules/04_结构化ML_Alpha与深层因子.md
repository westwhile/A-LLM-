# 模块 04：结构化 ML Alpha 与深层因子计划

> 科研优先级：R2；对应 P3 兼容编号；在 R1 冻结文本表示后开展，是个人第二科研方向。

## 1. 中央问题与允许结论

> 在真实 PIT 特征、预注册 walk-forward、现实成本和完整试验登记下，非线性模型是否相对透明线性/排序基准提供稳定的横截面预测增量？

允许结论只有：支持、不支持或证据不足。单个 Sharpe、一次最优参数或样本内拟合不能回答该问题。

## 2. 假设层级

- H1：Elastic Net 相对现有 IC 加权改善样本外预测；
- H2：LightGBM 相对 Elastic Net 的增量来自非线性/交互；
- H3：增量在大盘/高流动性样本、不同市场状态和成本后仍存在；
- H4（远期）：神经网络或条件 AutoEncoder 相对树模型有额外价值；
- H0：复杂模型的改进来自试验次数、微盘暴露、成本低估或泄漏。

## 3. 输入与目标

- 输入：已验收的价格、价值、质量、成长、流动性、波动、ESG、状态，以及 R1 冻结文本表示或正式 `no_text` 分支；
- 目标：预注册的下一非重叠月超额收益或横截面排名；
- 不将 `expected_return` 当可观测真值，输出需带预测区间/校准信息；
- 特征截面标准化、缺失处理和中性化必须在时点内完成。

## 4. 模型阶梯

### M0 透明基准

- 单因子、等权/IC 权重、OLS/Ridge/Elastic Net；
- 朴素 Top-N 与行业/规模中性组合。

### M1 主模型

- LightGBM，固定小参数空间；
- 对照 Random Forest 或 HistGradientBoosting；
- 特征重要性至少同时报告 permutation/SHAP 稳定性，不能解释为因果。

### M2 进阶

- 浅层 MLP；
- 传统 PCA/PLS 与通用 AutoEncoder 降维；
- 仅在样本量和 M1 结果支持时进入。

### M3 深层资产定价

- 条件 AutoEncoder、latent factor 或深层 SDF 属独立研究协议；
- 不把“压缩 768 维文本向量”误称为 Gu–Kelly–Xiu 的 Autoencoder Asset Pricing Model。

## 5. 实验协议

- 扩张式/滚动 walk-forward，所有预处理嵌入 pipeline；
- 主要指标：OOS R²、Rank IC/ICIR、分组单调性、成本后组合收益；
- 次要指标：换手、覆盖、容量、回撤、状态分解、校准；
- 负对照：目标置换、特征时间错位、随机噪声特征、去除微盘、延迟一周期；
- 消融：传统特征族逐组移除、状态特征移除、复杂度/深度阶梯；
- 用 DSR/PBO 或预注册的多重试验控制解释模型搜索。

## 6. 实现块

1. `SupervisedDatasetBuilder` 与标签 manifest；
2. 统一 `AlphaModel` 接口和可复现 seed；
3. fold-local preprocessing/training/prediction；
4. prediction artifact（股票、时点、预测、模型/特征版本）；
5. 模型对比、校准、消融和失败登记；
6. 只向 P5 输出合格预测证据，不直接生成真实交易指令。

## 7. 退出门

- 至少 36 个非重叠真实 OOS 月且最终留出未污染；
- 模型相对预注册简单基准在多个窗口有稳定增量；
- 交易成本、微盘/流动性和试验次数不能解释主要结果；
- 全部尝试进入实验登记；
- 无增量时形成负结果报告并停止升级深度模型。

## 8. 阅读路线

| 顺序 | 资料 | 重点 | 来源状态 |
|---|---|---|---|
| 1 | [Gu, Kelly & Xiu (2020), Empirical Asset Pricing via Machine Learning](https://academic.oup.com/rfs/article/33/5/2223/5758276) | 横截面预测、模型比较、非线性交互、OOS | RFS 原始页面已核验，DOI 10.1093/rfs/hhaa009 |
| 2 | [Ke et al. (2017), LightGBM](https://proceedings.neurips.cc/paper_files/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html) | GOSS/EFB 与实现边界 | NeurIPS 原始页面已核验 |
| 3 | [Gu, Kelly & Xiu (2021), Autoencoder Asset Pricing Models](https://www.sciencedirect.com/science/article/pii/S0304407620301998) | 条件 latent factor 与资产定价 | Journal of Econometrics 原始页面已核验，DOI 10.1016/j.jeconom.2020.07.009 |
| 4 | [Chen, Pelger & Zhu, Deep Learning in Asset Pricing](https://pubsonline.informs.org/doi/abs/10.1287/mnsc.2023.4695) | 深层 SDF/经济结构 | 2023 在线、2024 卷期已核验 |

学习产物：论文方法表、一个模拟横截面复现、一个 fold-local preprocessing 测试和一份模型搜索预算。

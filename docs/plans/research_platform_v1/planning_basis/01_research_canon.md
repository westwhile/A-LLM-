# Research Canon：科研平台计划事实基线

## 1. 已核验项目事实

- 活跃主线是 `A-LLM-`；
- 当前工程覆盖数据标准化、质量/PIT、因子、walk-forward、组合回测、归因、Kalman/HMM/GARCH/DCC、消融、晋级审计与只读看板；
- 2026-08-11 本轮本地完整回归为 174 项测试通过，但 P0 正式冻结必须重跑；
- `reports/gate/real-pit-20260725-r1/data_gate_summary.json` 当前为 `passed`，必需表齐全、阻断为空、专项审计非空；
- 当前工作树有未提交修改；
- `signoff_sheet_20260727.md` 的 B 哈希确认和 C 终审尚未全部完成；
- 当前 `outputs/runs` 尚无可接受的真实研究 run；
- PFROS 当前只有文档规划，未建立代码工程；
- A-LLM 与 PFROS 的现有架构都要求保持独立仓库并通过研究包连接。

## 2. 研究协议事实

- 真实数据预热从不晚于 2015 年开始；
- 评估从 2018 年开始；
- 2024-01-01 起为最终留出期；
- 月度目标为非重叠持有期；
- 至少需要 36 个非重叠 OOS 月；
- real 模式不得使用 synthetic/static fallback 伪造有效输出；
- HMM 使用 filtered probability；
- 财务与历史成分必须遵守 PIT。

## 3. 用户与项目治理约束

- 未经明确要求不 commit、push、tag、发布或部署；
- 不覆盖用户未提交修改；
- 受限数据、raw/standard、outputs、tmp 和凭据不得进入发布包；
- 第一次人工确认授权许可/入库，第二次确认审计/数据冻结，AI 不代签；
- 工程完成、数据验收和真实市场结论必须分开。

## 4. 术语定义

- `engineering_valid`：代码、配置、测试和工程运行成立；
- `data_accepted`：真实数据许可、PIT、质量、覆盖和冻结已验收；
- `market_evidence_eligible`：真实 OOS、成本、消融、过拟合和留出期允许进入决策证据候选；
- `Research Package`：版本化、可验证、只封装现有 run 的跨仓库研究证据包；
- `DecisionCandidate`：供人审查的候选，不是批准、订单或金融事实；
- `Feature Registry`：研究特征元数据和离线快照登记，不等同在线 Feature Store。

## 5. 拟实施内容，不得写成已完成

- Dataset/Feature/Experiment/Artifact Registry；
- Research Package exporter/validator；
- LightGBM/Elastic Net 等结构化 ML Alpha；
- 真实 LLM 文本 Embedding 研究；
- Black–Litterman 和更复杂组合优化；
- PFROS Python/SQLite 工程、账本和决策闭环。
- Isolation Forest/AutoEncoder 异常旁路；
- purged/embargo 验证增强；
- RAG、知识图谱、因果 ML、基础模型、Agent、另类/合成数据和多模态研究。

## 6. 已联网核验的核心研究来源（2026-08-11）

- Gu, Kelly & Xiu (2020), *Empirical Asset Pricing via Machine Learning*：RFS 33(5), 2223–2273，DOI `10.1093/rfs/hhaa009`；
- Gu, Kelly & Xiu (2021), *Autoencoder Asset Pricing Models*：Journal of Econometrics 222(1), 429–450，DOI `10.1016/j.jeconom.2020.07.009`；
- Chen, Pelger & Zhu：*Deep Learning in Asset Pricing*，2023 在线、Management Science 2024 卷期，DOI `10.1287/mnsc.2023.4695`；
- LightGBM、RAG、GraphSAGE、TimeGAN、FinBERT、BloombergGPT、FinGPT、Chronos、TimesFM、Lag-Llama 的原始论文/官方页面已核验并在模块内链接；
- Black–Litterman (1992)、DML (2018)、PBO/DSR、联邦学习原始/作者页面已核验并在模块内链接。

这些核验只支持元数据和方法定位，不支持其在 A 股数据上的有效性，也不替代正式投稿前的逐条引用复核。

## 7. 未核验与待补证据

- 长尾阅读线索的正式元数据、版次、DOI 和具体方法边界；
- 模型权重、中文能力、许可证与当前版本可用性；
- 真实文本数据来源和许可；
- LightGBM 等新增依赖在当前环境中的可用性；
- 真实阶段 2–8 运行结果；
- ML/LLM 相对传统基准的实际增量；
- PFROS 接入后是否改善个人决策。

## 8. 禁止结论

- 数据 gate `passed` 等同最终数据签署完成；
- 测试通过等同策略有效；
- 回测结果等同真实可得收益；
- 使用 AI/LLM 就构成科研创新；
- PFROS 或 Agent 可自动执行投资；
- 复杂模型必然优于简单模型。
- 异常分数等于数据错误；
- 图谱/多模态/基础模型/Agent 的技术复杂度等于科研贡献；
- 合成数据可以替代真实 OOS；
- DML 自动解决未观测混杂；
- BloombergGPT 等论文模型必然有可直接使用的开放权重。

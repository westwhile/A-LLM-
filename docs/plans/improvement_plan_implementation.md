# 改进计划实施矩阵

| 阶段 | 主要实现 | 核心验收产物 |
|---|---|---|
| 1 配置统一 | 三配置路径、成本/组合/执行注入 | 三份配置快照、`run_summary.md` |
| 2 数据闭环 | 标准导入、跨表质量审计、真实 manifest 阻断 | `data_manifest.json`、质量报告 |
| 3 PIT | 财务来源日期、信号/执行/目标日期、事件去重 | `factor_panel_timing.csv`、PIT 测试 |
| 4 样本外 | 严格滞后 walk-forward | window IC、OOS IC、方向和权重历史 |
| 5 执行/容量 | 规则、约束、延迟/成本/参与率情景 | 未成交分析、`robustness_scenarios.csv` |
| 6 归因/报告 | 主动行业、回撤、成本和稳健性图表 | 主动暴露、回撤贡献 |
| 7 LLM | 离线标签、缓存、版本、抽查门槛 | LLM 审计 CSV/Markdown |
| 8 工程质量 | 统一 CLI 和质量门禁 | compile/test/CLI/notebook smoke |

真实研究的最终可信度仍由数据源的 PIT 完整性和交易状态字段决定；合成样例通过不等于策略有效或可交易。


---
title: A股多因子研究框架阶段性项目报告
date: 2026-07-13
author: Jason Chen
advisor: 李老师
status: 阶段性汇报
project_version: 0.2.0
mainline: A-LLM-
base_commit: 58b7521b1ffd23f4b1bdafdda74e0cc54ad06957
baseline_run: advisor-baseline-20260713
---

# A股多因子研究框架阶段性项目报告

## 摘要

本项目以传统多因子样本外实证为主线，建立标准化数据接入、PIT 时间控制、因子构建与中性化、IC 与分组检验、Walk-Forward、组合构建、事件驱动回测、绩效归因和证据追溯流程。LLM 事件因子仅作为扩展；在没有合法授权文本、准确发布时间和人工复核通过率前，不进入组合信号。

本次报告统一引用独立运行目录 `A-LLM-/outputs/runs/advisor-baseline-20260713/`。该基线建立在提交 `58b7521` 上，并通过运行元数据记录当前源码树、三份配置、研究协议和数据内容哈希。当前数据为合成样例，因此结果只证明工程和统计链路可运行，不证明真实 A 股市场有效性，也不代表真实可获得收益。

## 一、结论—证据—限制

| 结论 | 证据 | 限制 |
|---|---|---|
| 工程链路可复现 | `run_metadata.json`、配置快照、数据 manifest、订单/成交/持仓 | 尚未在授权真实 PIT 数据上闭环 |
| “全期平均持仓 14.21 只”不等于配置失效 | 180 日中含 129 个未建仓日；建仓后平均 50.14 只；目标均值 50 只 | 合成样例、资金规模 100 万元 |
| 成交后约束在样例中通过 | 单票、实际行业、现金、换手、参与率均无违例 | 真实成交、冲击和容量尚需校准 |
| 20 日重叠收益不得每日连乘 | 日频结果只作横截面诊断；另输出月末非重叠分组表 | 样例仅 2 个合法持有期，统计量不足 |
| 成本归因量纲已统一 | 总成本 1,539.97 元；期初资产占比 0.1540%；净值拖累 0.1537% | 小额勾稽差来自成本时点和复利 |
| 因子显著性统计已升级 | 普通 t、HAC/Newey–West t、p 值、BH-FDR、样本量 | 合成数据显著性不可外推 |
| 真实市场有效性尚未得到支持 | `evidence_manifest.json` 明确标记为未支持 | 需要 Wind、CSMAR 或本地授权标准表 |

## 二、冻结基线与数据口径

### 2.1 唯一主线

- 唯一开发主线：`A-LLM-/`
- 其他 `A-LLM-*` 目录：历史归档，只读使用
- 基础提交：`58b7521b1ffd23f4b1bdafdda74e0cc54ad06957`
- 独立 run：`advisor-baseline-20260713`
- 冻结研究协议：`A-LLM-/config/research_protocol.yaml`
- 三份配置：`project_config.yaml`、`factor_config.yaml`、`backtest_config.yaml`
- 数据版本：`22a63c62ac9a94238f7f74fca4ab94b38b8a86747f1ea09380650552fa85343c`

由于本轮按要求不提交 Git commit，`run_metadata.json` 另外保存源码树 SHA-256 和配置文件 SHA-256，用于精确识别提交之后的实现状态。

### 2.2 当前研究口径

| 项目 | 当前口径 |
|---|---|
| 股票池/基准 | 配置指定 `000905.SH`，多基准数据不得默认取第一项 |
| 预测期 | 20 个交易日 |
| 调仓 | 月末信号，下一交易日开盘执行 |
| 财务数据 | 真实交易日计算 `usable_date`；同日修订取可确定的最新版本 |
| 组合 | Top 50，单票上限 5%，行业上限 30%，最大现金 10% |
| 执行 | 100 股一手，单次换手上限 50%，成交额参与率上限 5% |
| 成本 | 买卖佣金、卖出印花税、滑点、冲击、最低佣金 5 元 |
| 统计推断 | HAC 滞后 19 阶，BH-FDR 5% |
| LLM | 离线、人工复核门禁、只作扩展 |

## 三、三项关键口径纠正

### 3.1 持仓解释

本次基线的目标组合平均持仓数为 50.00 只。全期平均实际持仓数为 14.21 只，但 180 个净值观测日中有 129 个未建仓日；剔除未建仓区间后，51 个已投资日的平均实际持仓数为 50.14 只。建仓后平均现金比例为 6.25%，最高为 7.98%，未超过 10% 上限。

68 笔订单因一手数量约束未成交，请求金额合计约 12.07 万元。成交后审计显示：持仓数、单票权重、实际行业权重、现金比例、换手率和成交额参与率均无违例。因此，原先依据 14.21 只全期均值认定“最少持仓配置失效”的结论不成立。

证据：`metrics.csv`、`figures/execution_compliance.csv`、`figures/execution_compliance_summary.csv`、`figures/unfilled_order_analysis.csv`。

### 3.2 分组收益时间含义

日频 20 日前瞻收益高度重叠，不能把每日横截面分组均值直接连乘为累计收益。当前实现将 `group_returns.csv` 降级为横截面诊断，不再生成其累计曲线；`group_test_nonoverlap.csv` 只使用月末且持有期互不重叠的信号日期，并在发现目标收益结束日与下一信号日重叠时直接报错。

样例数据只有 2 个合法非重叠持有期，无法支撑统计或市场结论。若后续保留日频信号，应使用 cohort/重叠组合方法，而不是直接连乘前瞻标签。

### 3.3 成本归因量纲

`cost_attribution.csv` 现区分两类字段：

- 货币金额：`commission_amount`、`stamp_tax_amount`、`slippage_amount`、`impact_amount`、`total_cost`；
- 净值比例：各类 `*_ratio`、`total_cost_ratio`、`cost_drag` 和 `reconciliation_residual`。

本次基线总成本为 1,539.97 元，占期初资产 0.1540%；净值路径的成本拖累为 0.1537%，勾稽差约 0.0003 个百分点。该差异源于成本发生时点及复利，而非量纲混用。

## 四、已落地的工程与研究升级

### 4.1 配置契约

新增 `validate-config`。研究区间、月末调仓、最低上市天数、ST/停牌开关、涨跌停开关、成交价格、资金规模、换手、参与率、成本和 Walk-Forward 参数均进入程序；未消费参数、未支持值、基准不一致和在线 LLM 开关会直接报错。

### 4.2 数据版本与 PIT 门禁

数据 manifest 现在记录 schema 版本、表级内容 SHA-256、文件 SHA-256、来源和数据版本。哈希对表行序及 CSV 合理浮点往返稳定，对内容变化敏感。真实模式必须存在并通过 manifest 校验；缺少成分、停复牌、ST、涨跌停、财务等核心 PIT 表会阻断正式运行，新闻事件表可选但不能在缺时间戳时进入正式信号。

### 4.3 因子统计

新增 `factor_inference.csv`，同时保留原始因子和处理后因子结果，输出平均 Rank IC、普通 t 值、HAC 标准误、HAC t 值、p 值、BH-FDR q 值、5% FDR 判定、样本量和滞后阶数。已有逐年、市场状态、覆盖率、衰减、换手率、相关性和分组单调性诊断继续保留。

研究协议记录候选因子总数、筛选规则、股票池、基准、训练/验证/测试口径、成本和主检验。进入真实最终测试期后不得根据测试结果继续调参。

### 4.4 执行与合规

新增 `execution_compliance.csv`，按日记录实际持仓数、单票权重、实际行业权重、现金比例、换手率和实际成交参与率，并给出阈值、是否通过和违例原因。真实模式发现成交后违例会阻断正式结论。停牌或缺少当日行情的旧持仓使用最后可见收盘价估值，不再无依据归零。

### 4.5 证据生成

每个 run 新增 `evidence_manifest.json`，将工程复现、PIT 时间、因子真实有效性、执行约束和成本勾稽等主张映射到具体文件。报告构建命令只允许从指定 run 读取数字和图片。

## 五、基线样例结果

| 指标 | 数值 | 解释边界 |
|---|---:|---|
| 净累计收益 | 0.57% | 合成样例，仅验证链路 |
| 年化收益 | 0.79% | 180 日短样本年化 |
| 年化波动率 | 10.14% | 252 交易日年化 |
| Sharpe | 0.078 | 不支持因子有效性结论 |
| 最大回撤 | -9.54% | 样例路径风险 |
| 成本拖累 | 0.1537% | 标准成本，未用真实成交校准 |
| 目标持仓均值 | 50.00 | 月末目标组合 |
| 全期实际持仓均值 | 14.21 | 含 129 个未建仓日 |
| 建仓后实际持仓均值 | 50.14 | 51 个已投资日 |
| 建仓后平均/最大现金 | 6.25% / 7.98% | 上限 10% |

这些结果不应表述为真实可获得收益。合成数据可能把生成规则直接带入因子和收益，因此即使 HAC/FDR 显著，也不能外推到真实市场。

## 六、8 周分阶段计划与当前状态

| 阶段 | 时间 | 主要交付 | 当前状态/验收 |
|---|---|---|---|
| 1. 报告纠错与基线冻结 | 第 1 周 | 统一 MD/DOCX、独立 run、逐数字追溯、A4 文档 | 已实现；待最终视觉渲染复核 |
| 2. 正确性与工程契约 | 第 2—3 周 | 配置契约、稳定哈希、指定基准、成本量纲、成交后合规、临时 smoke | 已实现并加入测试 |
| 3. 统计与样本外升级 | 第 4—5 周 | 非重叠分组、HAC、FDR、研究协议、Walk-Forward 审计 | 核心实现完成；真实长样本待验证 |
| 4. 真实 PIT 与执行现实性 | 第 6—7 周 | 授权数据、财务修订、历史状态、退市/复牌/最低佣金、情景分析 | 工程门禁已准备；外部授权数据尚缺 |
| 5. 正式实证与交付 | 第 8 周 | 冻结协议一次性 OOS、容量/归因、证据清单、最终报告 | 依赖阶段 4，不提前宣称完成 |

若第 6 周前仍无法取得合法授权数据，只交付小范围数据试点和工程验证，不形成市场有效性结论。

## 七、复现入口

```powershell
# 配置完整性与未消费参数
python -m ashare_factor_research.main validate-config

# 导入后验证数据 manifest、schema、内容哈希与 PIT 条件
python -m ashare_factor_research.main verify-data --data-dir <标准数据目录> --mode real

# 按冻结协议运行
python -m ashare_factor_research.main run-research --protocol config/research_protocol.yaml --run-id <run_id>

# 只从指定 run 构建导师报告
python -m ashare_factor_research.main build-advisor-report --run-dir outputs/runs/<run_id>

# 默认在临时目录执行 Notebook/CLI smoke；显式允许时才更新静态产物
python -m ashare_factor_research.main quality
python -m ashare_factor_research.main quality --update-artifacts
```

## 八、参考方法

1. Fama, E. F., & MacBeth, J. D. (1973). Risk, Return, and Equilibrium: Empirical Tests. *Journal of Political Economy*, 81(3), 607–636.
2. Newey, W. K., & West, K. D. (1987). A Simple, Positive Semi-definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix. *Econometrica*, 55(3), 703–708.
3. Benjamini, Y., & Hochberg, Y. (1995). Controlling the False Discovery Rate. *Journal of the Royal Statistical Society: Series B*, 57(1), 289–300.
4. Jegadeesh, N., & Titman, S. (1993). Returns to Buying Winners and Selling Losers. *Journal of Finance*, 48(1), 65–91.
5. Harvey, C. R., Liu, Y., & Zhu, H. (2016). … and the Cross-Section of Expected Returns. *Review of Financial Studies*, 29(1), 5–68.

## 九、最终边界

本项目提供研究、工程和风险分析支持，不提供投资建议。当前交付完成的是“可审计的传统多因子研究框架和合成样例证据”，不是“已验证可交易的 A 股策略”。真实模式只有在核心 PIT 数据完整、质量阻断为零、协议已冻结、样本外结果独立且成交后合规通过时，才允许生成正式策略结论。

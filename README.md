# A股多因子选股策略研究：因子检验、组合回测与 LLM 辅助解释

本项目用于展示一套可复现的 A 股多因子研究框架，覆盖：

`数据清洗 -> 因子构建 -> 因子处理 -> IC/分组检验 -> 多因子组合 -> 回测绩效 -> LLM 事件解释`

当前版本重点是可审计研究工程，不直接给出真实可交易结论。样例数据由脚本合成；真实模式要求标准表、数据 manifest、PIT 质量阻断和严格基准日期对齐。

## 快速开始

```powershell
cd A-LLM-
python scripts/generate_sample_data.py
$env:PYTHONPATH="src"
python -m ashare_factor_research.main run-sample
python -m ashare_factor_research.main run-pipeline --mode sample --data-dir data/sample --run-id sample-smoke
python -m ashare_factor_research.main version
python -m unittest discover -s tests
python -m compileall src tests
python scripts/smoke_notebooks.py
python scripts/build_report_pdf.py
```

如果本机 `python` 不可用，可使用 Codex bundled Python：

```powershell
& "C:\Users\25377\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts/generate_sample_data.py
```

## 阶段 1-8 主线入口

本目录是唯一主线交付目录。根目录下其他 `A-LLM-*` 目录仅作为历史参考或能力来源，不再并行演进。

标准链路：

```text
真实数据拉取/标准化 -> 数据质量阻断 -> PIT 因子面板 -> 因子检验 -> 多因子组合回测 -> 真实基准绩效与归因报告
```

外部文件标准化并生成 `data_manifest.json`：

```powershell
python -m ashare_factor_research.main import-data --source-dir data/import/incoming --output-dir data/standard/real-v1 --format parquet
```

真实数据依赖：

```powershell
python -m pip install akshare pyarrow
```

小股票池真实数据拉取示例：

```powershell
$env:PYTHONPATH="src"
python -m ashare_factor_research.main fetch-data `
  --start-date 2024-01-01 `
  --end-date 2024-03-31 `
  --symbols 000001.SZ,600000.SH `
  --tables trade_calendar,stock_basic,daily_bar,benchmark_index `
  --output-dir data/raw/smoke `
  --format csv
```

AkShare 无法稳定提供的历史 PIT 表，例如历史指数成分、ST、停牌、行业、完整估值和财务表，应以本项目标准表格式补齐到本地目录。真实模式会把缺失核心表记为阻断问题：

```powershell
python -m ashare_factor_research.main quality-check --mode real --data-dir data/raw/smoke --output-dir outputs/quality --fail-on-blocking
```

完整阶段输出使用 `outputs/runs/<run_id>/`：

```powershell
python -m ashare_factor_research.main run-pipeline --mode sample --data-dir data/sample --output-dir outputs/runs --run-id sample-smoke
python -m ashare_factor_research.main run-robustness --mode sample --data-dir data/sample --output-dir outputs/runs --run-id robustness-smoke
```

关键输出包括三份配置快照、`data_manifest.json`、`run_summary.md`、样本外方向/权重历史、订单/成交/持仓、未成交分析、归因和 `figures/`。

统一质量门禁：`python -m ashare_factor_research.main quality`。

## 项目结构

```text
config/                         参数配置
data/sample/                    合成样例数据，可提交
docs/                           面试说明与补充文档
notebooks/                      可顺序运行的研究 notebook
reports/                        报告、图表、指标与实现状态说明
scripts/                        命令行辅助脚本
src/ashare_factor_research/     核心 Python 包
tests/                          单元测试与 smoke test
```

## 报告与展示入口

- 完整研究报告：[reports/factor_research_report.md](reports/factor_research_report.md)
- PDF 报告：运行 `python scripts/build_report_pdf.py` 生成 [reports/factor_research_report.pdf](reports/factor_research_report.pdf)
- Notebook 顺序复现：[notebooks/README.md](notebooks/README.md)
- 面试问题准备：[docs/interview_notes.md](docs/interview_notes.md)
- 标准数据字典：[docs/data_dictionary.md](docs/data_dictionary.md)

核心样例图表：

![累计净值](reports/figures/cumulative_return.png)

![回撤](reports/figures/drawdown.png)

![因子相关性](reports/figures/factor_corr_heatmap.png)

最近一次样例运行的核心指标见 [reports/figures/performance_metrics.csv](reports/figures/performance_metrics.csv)。当前样例数据为合成数据，指标只用于验证工程流程和展示报告结构，不代表真实可交易收益。

## 关键时间假设

- 因子在信号日 `trade_date` 收盘后计算。
- 组合在下一交易日生效，避免同日收盘信号同日成交。
- 因子 IC 使用未来 20 个交易日收益作为默认目标。
- 财务/新闻类数据必须按公告日或发布时间做 point-in-time 过滤。
- 回测结果仅代表研究框架验证，不代表真实可获得收益。
- 合成样例中的基准仅用于验证严格对齐和相对指标计算，不代表真实指数表现。
- 标准 `run-pipeline` 仅在 `benchmark_index` 与策略日期严格匹配时计算 Alpha、IR 等相对指标，不做隐式 forward-fill。

## 当前实现范围

已实现：

- 合成 A 股截面样例数据生成与读取。
- 量价、估值、规模、质量、资金流、LLM 事件因子示例。
- MAD 去极值、截面 z-score、行业/市值中性化。
- IC、Rank IC、分组收益、因子相关性。
- 配置驱动的 Top50/5% 上限组合、训练/验证/测试滚动方向与权重、下一交易日执行回测。
- 成本/延迟/成交额参与率压力测试，未成交原因、行业主动暴露和回撤贡献。
- 默认离线的 LLM 事件标签、缓存、prompt/model 版本和人工抽查门槛。
- 年化收益、波动率、夏普、Calmar、最大回撤、信息比率、换手率。
- `unittest` 测试和最小流水线 smoke test。
- 7 个顺序 Notebook、核心 PNG 图表、研究报告 Markdown、PDF 生成脚本和面试说明。

未实现和可改进项见 [reports/implementation_status.md](reports/implementation_status.md)。

完整阶段验收矩阵见 [docs/improvement_plan_implementation.md](docs/improvement_plan_implementation.md)。

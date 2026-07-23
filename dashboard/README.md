# 只读研究看板（阶段 9）

本地优先、只读、可追溯的 Streamlit 多页研究看板，用于查看数据质量、PIT 审计、
时间序列模型、消融结果、过拟合审计和运行证据。

## 用法

```powershell
# 安装依赖（项目 .venv，含 streamlit）
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe -m pip install streamlit

# 启动（默认仅监听 127.0.0.1）
powershell -File scripts/run_dashboard.ps1
```

等价手动命令（从项目根）：

```powershell
.venv\Scripts\python.exe -m streamlit run dashboard\app.py --server.address 127.0.0.1
```

## 只读约束

- 不修改原始数据、配置、模型参数或运行产物；适配层只调用 `pd.read_csv` /
  `Path.read_text` 与 sha256 计算，绝不写入源文件。
- 不触发交易、下单、调仓；不在浏览器端调用 Kimi 或同花顺接口。
- 不在前端重新计算与研究流水线不一致的核心指标；页面只透视/透视展示产物数值。
- 不隐藏 `synthetic_engineering_only`、缺失文件、过期运行或审计失败：
  缺文件显示"缺失"，schema 不符显示期望/实际列，synthetic 标记以红色横幅展示。
- 不补零、不插值、不让大模型生成替代数值。
- 默认仅监听 127.0.0.1；无数据库写入、无后台任务。

## 页面清单（9 页）

| 页面 | 入口 | 数据来源 |
| --- | --- | --- |
| 研究总览 | `dashboard/app.py` | run_metadata.json、research_protocol_snapshot.json、evidence_manifest.json |
| 数据源与缺口 | `dashboard/pages/1_数据源与缺口.py` | data_source_gap_matrix.csv |
| 数据质量与 PIT | `dashboard/pages/2_数据质量与PIT.py` | reports/gate/*/data_gate_summary.json + 五项审计 CSV |
| 因子时序 | `dashboard/pages/3_因子时序.py` | dynamic_factor_weights.csv、factor_weight_*、factor_timing_comparison |
| 市场状态 | `dashboard/pages/4_市场状态.py` | regime_probabilities.csv 等 regime_* |
| 波动与风险 | `dashboard/pages/5_波动与风险.py` | volatility_*、dynamic_covariance、dcc_risk_contributions |
| 消融对比 | `dashboard/pages/6_消融对比.py` | outputs/stage7*/ablation_*.csv |
| 统计与过拟合 | `dashboard/pages/7_统计与过拟合.py` | outputs/stage8*/ 审计 CSV、model_selection_audit.csv |
| 证据与运行 | `dashboard/pages/8_证据与运行.py` | evidence_manifest.json、data_manifest.json、文件哈希 |

每个图表/表格下方均展示来源文件、sha256、修改时间；所有数字可定位到源文件与字段。

## 数据契约（适配层期望列）

看板只能从 `dashboard/adapters/` 读取。期望列如下；多余列允许，缺少期望列即
降级为 "schema 不符" 并报出期望/实际列。

- 阶段 4–6 产物（`time_series_reader.TIME_SERIES_SCHEMAS`）：与
  `src/ashare_factor_research/time_series/stage46.py` 的 `SCHEMAS` 完全一致。
  旧版 `runs/*/figures` 产物列不一致时按"旧 schema"显式降级。
- 门禁审计（`data_quality_reader.AUDIT_SCHEMAS`）：`pit_timing_audit`、
  `survivorship_audit`、`financial_revision_audit`、`universe_coverage`、
  `benchmark_alignment` 五项 CSV，列与门禁实现写出的表头一致。
- 消融产物（`performance_reader.ABLATION_SCHEMAS`，阶段 7 数据契约，
  复制自权威的 `stage7.STAGE7_SCHEMAS`，time-series-v2）：
  - `ablation_portfolio_returns.csv`：`date, portfolio_id, gross_return,
    net_return, turnover, status, model_version`
  - `ablation_nav.csv`：`date, portfolio_id, nav, status, model_version`
  - `ablation_performance.csv`：`portfolio_id, status, annual_return,
    annual_volatility, sharpe, information_ratio, max_drawdown,
    monthly_win_rate, annual_turnover, oos_months, model_version`
  - `ablation_incremental.csv`：`comparison, treatment, baseline, status,
    incremental_annual_return, ir_improvement, max_drawdown_change,
    positive_year_ratio, model_version`
  - `ablation_cost_sensitivity.csv`：`portfolio_id, cost_scenario,
    cost_multiplier, status, net_annual_return, net_total_return, model_version`
  - `ablation_status.csv`：`portfolio_id, weight_scheme, regime_adjustment,
    volatility_control, status, oos_months, data_mode,
    synthetic_engineering_only, detail, model_version`
- 阶段 8 审计（`audit_reader.AUDIT_SCHEMAS`，数据契约，
  复制自权威的 `stage8.STAGE8_SCHEMAS`，time-series-v2）：
  - `promotion_gate_results.csv`：`gate, threshold, value, passed, status,
    detail, model_version`
  - `prediction_test_results.csv`：`test, comparison, statistic, p_value,
    passed, fdr_q_value, fdr_5pct, effective_samples, status, model_version`
  - `overfit_audit.csv`：`metric, scope, statistic, value, threshold, passed,
    p_value, fdr_q_value, fdr_5pct, trial_count, effective_samples, status,
    detail, model_version`
  - `trial_registry_coverage.csv`：`module, registered_trials, executed_trials,
    coverage, passed, status, detail, model_version`
  - `promotion_conclusion.csv`：`conclusion, conclusion_level, reasons,
    dynamic_ready, data_mode, synthetic_engineering_only, status, model_version`

run_id 隔离：页面通过运行选择器只读取所选目录的产物；CSV 含 `run_id` 列时，
适配层可校验其取值与所选 run_id 完全一致，混杂即拒绝展示。

## 测试

```bash
PYTHONPATH=src .venv/Scripts/python.exe -m unittest tests.test_dashboard_adapters -v
```

测试只覆盖适配层（不启动 Streamlit），并在读取前后校验源文件 sha256 不变。

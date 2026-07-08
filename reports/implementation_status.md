# 实现状态与改进清单

## 阶段 0：主线目录

已实现：

- `A-LLM-` 固定为唯一主线交付目录。
- 根目录 `README.md` 已说明其他 `A-LLM-*` 目录仅作历史参考。
- 主线 README 已给出阶段 0-5 的标准运行入口。

## 阶段 1：数据工程和真实数据接入

已实现：

- 标准 schema 扩展到 12 张表：交易日历、股票基础、行情、估值/资金流、行业、指数成分、财务、停牌、ST、涨跌停、基准、事件。
- `data_quality.py` 输出 Markdown 和 CSV，并可阻断主键重复、负价格、OHLC 越界、财务 PIT 错误和真实模式缺表。
- `fetch-data` CLI 支持 AkShare 拉取交易日历、股票基础、个股日行情和基准指数，并输出 `fetch_manifest.json`。
- 本地 loader 支持 CSV/Parquet 标准表。

真实数据限制：

- AkShare 无法稳定提供的历史 PIT 表不做伪造；历史指数成分、行业、ST、停牌、涨跌停、完整估值和财务表应以本地标准表补齐。

## 阶段 2：时间对齐和 PIT 防泄漏

已实现：

- 因子面板保留 `signal_date`、`execution_date`、`target_return_end_date`。
- 财务数据按 `usable_date` 前向对齐，事件因子只使用信号日前发布事件。
- 单元测试覆盖 `usable_date`、历史成分区间和 PIT 泄漏拒绝。

## 阶段 3：因子研究增强

已实现：

- 因子注册表记录类别、方向、输入字段、PIT 要求、中性化方式和说明。
- Pipeline 输出覆盖率、缺失 streak、处理审计、年度 IC、滚动 IC、市场分段 IC、IC 衰减和因子筛选报告。
- 因子筛选报告明确是研究输入，不作为样本外有效性证明。

仍需增强：

- walk-forward 权重和参数选择目前仍是保守骨架，真实研究需要用滚动训练窗口替代全样本筛选。

## 阶段 4：组合构建和回测执行

已实现：

- 下一交易日开盘事件式回测。
- 订单、成交、持仓和现金审计。
- 涨停禁买、跌停禁卖、停牌不可交易、lot size、最大换手、最小成交额、成交额占比上限。
- 未成交或部分成交会保留持仓延续，并记录原因。

仍需增强：

- 行业偏离约束、延迟一日/两日成交压力测试和多组成本情景尚未做成统一批量报告。

## 阶段 5：风险归因和绩效报告

已实现：

- 存在 `benchmark_index` 时，绩效指标使用严格日期对齐的真实基准收益。
- 输出总收益、年化收益、波动率、夏普、Sortino、Calmar、最大回撤、Alpha、Beta、跟踪误差、信息比率、超额回撤。
- 输出年度/月度收益、换手、成本拖累、行业暴露、行业收益归因、市值分桶贡献、个股 Top/Bottom 贡献。
- 标准 run 目录输出 `config_snapshot.yaml`、`data_manifest.json`、`data_quality_report.md`、`metrics.csv`、`orders.csv`、`fills.csv`、`positions.csv` 和 `figures/`。

## 验证命令

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
python -m compileall src tests
python -m ashare_factor_research.main generate-sample --output-dir data/sample
python -m ashare_factor_research.main run-pipeline --mode sample --data-dir data/sample --run-id sample-smoke
```

当前回测和报告输出只用于研究工程验证，不代表真实可获得收益，也不构成投资建议。

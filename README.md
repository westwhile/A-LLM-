# A股多因子选股策略研究：因子检验、组合回测与 LLM 辅助解释

本项目用于展示一套可复现的 A 股多因子研究框架，覆盖：

`数据清洗 -> 因子构建 -> 因子处理 -> IC/分组检验 -> 多因子组合 -> 回测绩效 -> LLM 事件解释`

第一版重点是项目框架和最小可运行样例，不直接给出真实可交易结论。样例数据由脚本合成，真实数据接入默认预留 AkShare provider。

## 快速开始

```powershell
cd A-LLM-
python scripts/generate_sample_data.py
$env:PYTHONPATH="src"
python -m ashare_factor_research.main run-sample
python -m unittest discover -s tests
python -m compileall src tests
```

如果本机 `python` 不可用，可使用 Codex bundled Python：

```powershell
& "C:\Users\25377\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts/generate_sample_data.py
```

## 项目结构

```text
config/                         参数配置
data/sample/                    合成样例数据，可提交
notebooks/                      研究 notebook 占位
reports/                        报告与实现状态说明
scripts/                        命令行辅助脚本
src/ashare_factor_research/     核心 Python 包
tests/                          单元测试与 smoke test
```

## 关键时间假设

- 因子在信号日 `trade_date` 收盘后计算。
- 组合在下一交易日生效，避免同日收盘信号同日成交。
- 因子 IC 使用未来 20 个交易日收益作为默认目标。
- 财务/新闻类数据必须按公告日或发布时间做 point-in-time 过滤。
- 回测结果仅代表研究框架验证，不代表真实可获得收益。

## 当前实现范围

已实现：

- 合成 A 股截面样例数据生成与读取。
- 量价、估值、规模、质量、资金流、LLM 事件因子示例。
- MAD 去极值、截面 z-score、行业/市值中性化。
- IC、Rank IC、分组收益、因子相关性。
- TopN 等权组合、基础成本模型、下一交易日执行回测。
- 年化收益、波动率、夏普、Calmar、最大回撤、信息比率、换手率。
- `unittest` 测试和最小流水线 smoke test。

未实现和可改进项见 [reports/implementation_status.md](reports/implementation_status.md)。

## GitHub 推送

本实现默认不自动提交或推送。由于当前环境 Git HTTPS 访问曾出现 TLS/凭据错误，本地目录是用 GitHub API 保留远端文件后初始化的工作树。凭据正常后，建议先接上远端历史，再提交：

```powershell
git pull origin main
git add .
git commit -m "Implement A-share multi-factor research framework"
git push -u origin main
```

# 实现状态

## 已完成

- 阶段 1：三配置统一驱动，Top50/5%、成本和执行参数一致，run 保存完整快照和摘要。
- 阶段 2：标准导入、列映射、主键校验、日期标准化、SHA256 manifest；真实模式无 manifest 阻断。
- 阶段 3：保留信号/执行/目标日期及财务报告期/公告日/可用日来源，PIT 逻辑有测试。
- 阶段 4：严格滞后的训练/验证/测试滚动方向、筛选和 IC 权重。
- 阶段 5：板块/ST 规则、延迟成交、成本与容量情景、行业/持仓约束和未成交分析。
- 阶段 6：严格基准相对指标、主动行业、行业/市值/个股/回撤/成本归因和稳健性图表。
- 阶段 7：离线优先 LLM 标签、原文、来源、prompt/model 版本、JSON、cache key 和人工抽查门槛。
- 阶段 8：统一 compileall、unittest、CLI、Notebook smoke 门禁；主线与历史目录职责文档化。
- 阶段 9：时间序列研究契约、ADF/KPSS/Ljung-Box/ARCH/结构突变诊断、朴素/均值/EWMA/ARIMA(1,0,0)基准比较。
- 阶段 10：严格过滤式 Gaussian HMM、Kalman 动态因子 IC 权重、GJR-GARCH 风险预测、DCC 小型因子协方差和共同投资区间策略比较。
- 真实模式禁止静态降级；样例降级、规则 walk-forward 与动态方案均记录 `score_source`，并输出三方案可用性及共同区间比较。

## 仍需真实数据验证

- 历史指数成分、行业、ST、停复牌、涨跌停、财务修订和事件文本仍需可靠 PIT 数据源。
- 复牌首日、新股无涨跌幅期、退市整理等应由数据源显式状态字段覆盖。
- 冲击成本和容量参数是情景假设，不是成交可行性证明。
- 样例输出基于合成数据，只验证工程和审计链路，不构成投资建议。
- Markov/Kalman/GARCH/DCC 已形成可审计实现，但是否提升真实策略必须由至少 36 个月非重叠 OOS 数据决定；证据不足时输出 `insufficient_history`。

## 验证命令

```powershell
$env:PYTHONPATH="src"
python -m ashare_factor_research.main quality
python -m ashare_factor_research.main run-pipeline --mode sample --run-id sample-smoke
python -m ashare_factor_research.main run-robustness --mode sample --run-id robustness-smoke
```

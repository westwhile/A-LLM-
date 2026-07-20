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
- 阶段 0/1 工程门禁：冻结 2015/2018/2024 研究协议与实验登记；manifest v2 绑定来源登记；真实财务保留修订链；新增 PIT、修订、幸存者、逐日覆盖率、基准对齐和总门禁产物；真实运行目录禁止覆盖。
- 真实模式禁止静态降级；样例降级、规则 walk-forward 与动态方案均记录 `score_source`，并输出三方案可用性及共同区间比较。
- 阶段 1D 纠错：新浪 `qfq-factor` 原值保存为 `qfq_factor_raw`，统一 `adj_factor=1/qfq_factor_raw`；完整真实导入与质量门禁要求 `review_status=approved` 且签署人、签署时间非空，当前签署继续保持 pending。
- 阶段 2：新增 `build-monthly-sample`，月末收盘信号、下一交易日开盘执行、相邻月末非重叠标签；输出 IC、原始/中性分组收益、成本与历史成员覆盖率、月度状态变量和四种预注册权重经济比较。
- 阶段 3：新增 `run-time-series-baselines`，默认仅评估 2018–2023；逐预测点记录训练截止日、ADF/KPSS/ACF/PACF/Ljung-Box/ARCH LM/Zivot-Andrews、缺失与异常处理，并比较 lag-1、历史均值、12/24 月均值、EWMA、AR(1) 与固定滞后 ARIMAX。

## 仍需真实数据验证

- 历史指数成分、行业、ST、停复牌、涨跌停、财务修订和事件文本仍需可靠 PIT 数据源。
- `config/data_source_registry.yaml` 当前为 `pending_user_review`；在用户补齐审查证据和本地 PIT 表前，真实门禁预期为 `blocked_by_missing_pit_tables` 或 `blocked_by_pit_quality`。
- 由于历史成分和 7 张许可 PIT 表尚未到位，阶段 2 的真实月度样本与阶段 3 的真实基准结果不会生成；sample 结果只用于验证时点、schema 和成本恒等式。
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
python -m ashare_factor_research.main quality-check --mode real --data-dir data/standard/real-v1 --output-dir outputs/quality/real-v1 --fail-on-blocking
```

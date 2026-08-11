# Evidence Table：计划关键声明与证据等级

| 声明 | 证据/来源 | 等级 | 允许写法 | 风险/处理 |
|---|---|---|---|---|
| A-LLM 已有完整量化工程骨架 | 当前源码、README、测试、CLI | evidence-backed | 工程能力已实现 | 不升级为真实市场有效 |
| 最新真实数据 gate 为 passed | 当前 `data_gate_summary.json` | evidence-backed | 工程门禁当前通过 | 签署与冻结仍未闭合 |
| 2026-08-11 本轮本地回归 174 项通过 | `.venv\\Scripts\\python.exe -m unittest discover -s tests` | evidence-backed | 当前观察值 | P0 冻结前重跑；现有因子源字段 warning 未掩盖 |
| 当前工作树有在途修改 | `git status --short` | evidence-backed | 尚未冻结 | 不清理/覆盖用户修改 |
| 当前没有可接受真实 run | `outputs/runs` 盘点 | evidence-backed | 真实实证尚未形成 | 不报告市场绩效 |
| PFROS 尚无代码工程 | PFROS README/TASKS 与目录盘点 | evidence-backed | 当前 M0 规划阶段 | 跨目录实施另行批准 |
| 轻量 Registry 可提高复现性 | 现有 manifest/registry 经验 | plausible-inference | 拟通过合同测试验证 | 避免过度平台化 |
| LightGBM 可能有预测增量 | 用户计划与常见研究方向 | hypothesis | 需要相对透明基准检验 | 允许不支持结论 |
| LLM Embedding 可能有独立增量 | 用户计划 | hypothesis | 文本数据验收后检验 | 当前无合格真实文本证据 |
| Black–Litterman 可能改善组合 | 用户计划 | hypothesis | 与简单方案公平比较 | 估计误差可能抵消收益 |
| PFROS 接入可改善个人财务管理 | 架构推断 | hypothesis | 先验证可审计决策闭环 | 不声称提高投资收益 |
| Multi-Agent/RL 值得近期实施 | 无当前必要证据 | unsupported | 远期 backlog | 不进入关键路径 |
| 离线特征注册可减少口径漂移 | Uber 官方平台经验 + 本地重复计算风险 | plausible-inference | 先实现轻量 PIT 特征层 | 当前无 online serving，不做在线 store |
| 异常检测能替代规则清洗 | 无支持证据 | unsupported | 只能作为人工审查旁路检验 | 不自动删改数据 |
| Purging/embargo 必须用于所有月度标签 | 取决于标签区间 | hypothesis | 先审计区间再选择 | 非重叠标签可能无需额外 embargo |
| RAG/知识图谱会提高 Alpha | 原始方法论文不涉及本项目结论 | hypothesis | 只检验独立增量和时点正确性 | 技术可行不等于金融价值 |
| DML 可以回答 AI/ESG 因果问题 | DML 原论文支持正交估计，不提供具体识别 | plausible-inference | 先定义 treatment/DAG/识别假设 | 未观测混杂仍可能存在 |
| 基础模型优于任务专用模型 | 当前项目无证据 | hypothesis | 与 naive/传统/任务模型同切分比较 | 预训练污染与许可待审计 |
| 合成数据可改善压力覆盖 | TimeGAN 等方法提供生成候选 | hypothesis | 只用于测试/压力 | 不用于真实研究晋级 |
| Human-in-the-loop 应为 PFROS 核心门 | 个人金融高风险边界与既有架构 | evidence-backed | 建议、批准、执行、事实分离 | 任何 AI 不得绕过批准 |

## 证据使用规则

1. `evidence-backed` 仍需标注快照日期和路径；
2. `plausible-inference` 必须有计划中的验证方法；
3. `hypothesis` 不能用“将会”“必然”“证明有效”表述；
4. `unsupported` 不进入近期实施，只保留为明确的远期候选或删除。

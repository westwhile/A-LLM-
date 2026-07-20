# 阶段 1D 数据源审查签署页（2026-07-19）——纠错版待用户签署

**状态：纠错版材料已重建，仍待用户本人签署**。AkShare 1.18.64 的 Sina qfq-factor
返回除数；旧标准产物曾把它当作乘数。不可覆盖原始批次 `data/raw/real-20260719`
保持不变，纠错组装保存为 `data/staging/real-20260719-r1`，标准导入保存为
`data/standard/real-stage-20260719-r1`。

纠错层保留 `qfq_factor_raw` 并令 `adj_factor=1/qfq_factor_raw`。本页已回填纠错版
manifest 与门禁哈希，但这不等同于用户许可确认；不得据此把
`config/data_source_registry.yaml` 的 `review_status` 改为 `approved`。

用户逐项核对 `reports/data_sources/*_review.md` 后在本页签署；签署即表示：

1. 确认 `config/research_protocol.real.yaml` 的窗口、候选模型、统计检验与留出期规则；
2. 确认登记表中 4 张已批准表的来源、版本、许可、单位、PIT 语义与证据路径；
3. 确认 8 张表保持阻断，并按各 review 文件中的提供规范补齐；
4. 承诺签署后不根据 2024-01-01 以来最终留出期表现修改候选模型或晋级门槛。

## 一、纠错版待签署哈希

| 对象 | SHA-256 |
| --- | --- |
| `config/research_protocol.real.yaml` | `0768abbbb3495cd5caa8f56404fb6f8dcb76d5e4b0698ac1119f7ad25a58879f` |
| `config/data_source_registry.yaml` | `f432d287a1bb7f10e4d0df2eb1290759d318396e468e30c66abcdf27303e43e9` |
| `data/raw/real-20260719/fetch_manifest.json` | `c0b6e9d2740aa22e2d6943573b39e5b4515e3695ed4d320cb3946e108ccbe530` |
| `data/raw/real-20260719/bars_manifest.json` | `ae1eda8aadbd1979aaeb1fcd5fbeba67d7cf53aee1eedbd9bcc9a2eb03b3f7b2` |
| `data/staging/real-20260719-r1/assembly_manifest.json` | `85341bd4ccf2348fd548542c432932a52985b5e58da999bd6cc70d4abb30a11d` |
| `data/standard/real-stage-20260719-r1/data_manifest.json` | `8cff79e8b7b6937a4d9802ad409809b2e498ca51535be9181e0674f2cdfe2d8e` |
| `reports/gate/real-stage-20260719-r1/data_gate_summary.json` | `44a336dcf4b4504d9b4e501d7bfc89d5157d92b95d9e7a79889d725f75acfa8a` |

注意：任何对协议或登记表的后续修改都会改变对应哈希，必须重新签署并登记新哈希。
旧 `real-20260719` 暂存/标准产物已由 `-r1` 纠错版取代，不得用于收益计算或签署。

## 二、本次已具备证据、建议批准的 4 张表

| 表 | 来源 | 关键事实 | 审查文件 |
| --- | --- | --- | --- |
| trade_calendar | AkShare 1.18.64（新浪日历） | 3,048 行，2014-01-02→2026-07-17，未来日历已裁剪 | `trade_calendar_review.md` |
| benchmark_index | AkShare 1.18.64（新浪备用，东财主源代理故障已留痕） | 3,048 行，逐日与日历对齐 | `benchmark_index_review.md` |
| stock_basic | AkShare 1.18.64（沪深交易所名单+退市名单） | 5,533 条，含 333 只退市股 | `stock_basic_review.md` |
| daily_bar | AkShare 1.18.64（新浪+腾讯，新浪复权因子快照） | 1,663,139 行 / 753 只，单位已统一并校验 | `daily_bar_review.md` |

已批准 4 表在真实导入与质量门禁中零阻断项；基准对齐审计 2,803 个交易日全部通过。

## 三、保持阻断的 8 张表（提供规范见各审查文件）

| 表 | 阻断原因（开源核验结论） | 推荐提供路径 |
| --- | --- | --- |
| index_member | 无历史成分 PIT 开源源，仅当前快照 | Wind/iFinD/Choice/Tushare Pro 历史成分导出 |
| daily_basic | 百度估值仅周频，东财资金流网络不可达 | Tushare Pro daily_basic+moneyflow 或终端日频导出 |
| financial_indicator | 开源无公告日+修订链 | Tushare Pro fina_indicator 或终端带修订导出 |
| industry | 申万历史文件下载失败，当前分类不可回填 | 终端行业历史（含生效日期）导出 |
| suspension | 无结构化停复牌历史开源源 | 终端停复牌导出；或批准推导口径 |
| st_status | 深交所已有证据（7,445 条），上交所无带日期源 | 终端 ST 历史导出；或补充上交所证据后推导 |
| limit_price | 无历史涨跌停价格开源源 | Tushare Pro stk_limit 或终端导出；或批准推导口径 |
| news_event | 可选表，暂无结构化授权源 | 暂不启用 |

## 四、门禁现状（2026-07-19 纠错版）

- `data_gate_summary.json` 状态：`blocked_by_missing_pit_tables`（符合设计，不是工程失败）
- 当前纠错版有 13 条阻断：7 张必需 PIT 表缺失、导入尚未就绪、7 张缺表质量项及 4 个空专项审计；基准对齐仍为 2,803/2,803。
- source registry 保持 `review_status: pending_user_review`；即使 7 张缺失表补齐，在用户明确签署前，完整质量门禁也会因缺少 `review_status/reviewed_by/reviewed_at` 而硬阻断。
- 纠错数值复核：1,663,139 行中 `adj_factor*qfq_factor_raw` 最大绝对误差约 `1.11e-16`；按股票计算的绝对日收益超过 30% 记录由旧口径 884 条降至 104 条。

## 五、签署

- 审查人（用户）：＿＿＿＿＿＿＿＿
- 签署日期：＿＿＿＿＿＿＿＿
- 对 4 张已批准表许可权限的确认（缓存 / 研究 / 衍生导出 / 图表展示）：＿＿＿＿＿＿＿＿
- 意见与保留事项：＿＿＿＿＿＿＿＿

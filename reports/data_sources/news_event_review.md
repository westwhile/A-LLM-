# 数据源审查：news_event（新闻/事件标签，可选表）

- 审查日期：2026-07-19
- 审查人：Kimi（起草，待用户签署确认）
- 审查结论：**保持阻断（可选表，不阻塞真实门禁）**。

## 定位

- 真实门禁只要求 11 张核心表，`news_event` 为可选扩展（缺失仅 warning）。
- 项目 LLM 事件模块（`label-events`）只输出审计用途的模拟标签，不接入外部 API，不构成研究数据。

## 若未来启用，schema 不得更改

```text
stock_code, publish_date, event_type, sentiment, impact_horizon, confidence, reason
```

- `sentiment ∈ {positive, neutral, negative}`；`confidence ∈ [0, 1]`（门禁硬检查）
- 强烈建议包含 `publish_time`（区分盘中/盘后，否则按盘后规则处理并记 warning）
- 来源必须是带发布时间戳的结构化授权源（交易所公告、授权新闻库）；不得使用模型生成内容、问财回答或搜索摘要。

## 当前状态

- 未提供、未使用；第一阶段研究不依赖本表。

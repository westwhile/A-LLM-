# 数据源审查：benchmark_index（中证 500 基准日行情）

- 审查日期：2026-07-19
- 审查人：Kimi（起草，待用户签署确认）
- 审查结论：建议批准 `approved_for_research`，`pit_ready: true`

## 来源与版本

- 提供者：AkShare 1.18.64
- 主用接口：`ak.stock_zh_index_daily_em(csi000905)`（东方财富）——2026-07-19 经本机代理多次连接失败（ProxyError，证据见 `akshare_probe2_20260719.json` 与 `fetch_manifest.json` 的 `fallback_errors`）
- 实际承接接口：`ak.stock_zh_index_daily(sh000905)`（新浪财经日线，备用源自动生效）
- 抓取批次：`data/raw/real-20260719/benchmark_index.csv`

## 覆盖与字段

- 暂存表：`data/staging/real-20260719/benchmark_index.csv`
- 行数：3,048；区间：2014-01-02 → 2026-07-17，与裁剪后交易日历逐日一致
- 字段：`trade_date`、`index_code`（恒为 `000905.SH`）、`close`（收盘点位）
- 完整性：与交易日历 3,048 个开市日一一对应，无缺日

## 单位与口径

- `close`：指数点位（index_points）；不复权（指数本身无复权概念）

## PIT 语义

- 指数收盘为当日公开行情，无修订语义；历史序列自 2014-01-02 起，覆盖 2015-01-01 协议起点。

## 权限评估

- 公开指数行情，经 MIT 许可的 AkShare 聚合获取；本地缓存、研究、衍生结果与图表展示无额外限制。

## 已知限制

- 主用源（东财）在本网络下不稳定，本次以新浪源落盘；如两源未来出现点位分歧，需以中证指数公司公布值复核。
- 仅含收盘价；状态变量所需的指数成交额将取自全市场个股成交额加总（daily_bar），不从本表取。

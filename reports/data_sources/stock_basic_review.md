# 数据源审查：stock_basic（证券主表）

- 审查日期：2026-07-19
- 审查人：Kimi（起草，待用户签署确认）
- 审查结论：建议批准 `approved_for_research`，`pit_ready: true`

## 来源与版本

- 提供者：AkShare 1.18.64（聚合沪深交易所官网公开名单）
- 在市股：`ak.stock_info_sh_name_code(主板A股)` 1,698 条 + `(科创板)` 610 条 + `ak.stock_info_sz_name_code(A股列表)` 2,892 条
- 退市股：`ak.stock_info_sh_delist` 159 条（含上市日期、暂停上市日期）+ `ak.stock_info_sz_delist` 208 条（含上市日期、终止上市日期）
- 抓取批次：`data/raw/real-20260719/stock_basic.csv`；深交所原始股本/行业字段存档 `data/raw/real-20260719/raw_sources/szse_name_code.csv`

## 覆盖与字段

- 暂存表：`data/staging/real-20260719/stock_basic.csv`
- 行数：5,533（含 333 只已退市股）；`ts_code` 主键唯一
- 字段：`ts_code, name, list_date, delist_date, exchange`
- `list_date` 区间：1990-12-01 → 2026-07-10；退市股 `delist_date` 来自交易所退市名单
- 合并规则：在市名单与退市名单交集 6 只（退市后重新上市/多事件），保留带退市日期的记录并在 `fetch_manifest.json` warnings 留痕

## 单位与口径

- `list_date` / `delist_date`：日期；`exchange`：SH/SZ 两位代码

## PIT 语义

- 主表描述证券静态属性与生命周期日期，不含随时间变化的估值字段；上市/退市日期为交易所公开事实。
- 幸存者审计所需"曾上市但已退市"股票已由交易所退市名单覆盖（333 只）。

## 权限评估

- 交易所官网公开名单，经 MIT 许可 AkShare 聚合；缓存、研究、衍生与图表展示无额外限制。

## 已知限制

- 当前名称为最新简称，不含历史简称变迁（深交所更名历史已另存为 ST 推导暂存证据，见 `st_status_review.md`；上交所无带日期公开源）。
- 不提供历史股票池成员资格（见 `index_member_review.md`，仍阻断）。

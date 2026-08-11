# Data Quality Report

- Tables audited: 11
- Blocking issues: 0
- Warnings: 27

## Blocking Issues

- None

## Warnings

- `daily_bar` `missing_rate:open`: 5.9e-05 (Missing values in required field.)
- `daily_bar` `missing_rate:high`: 5.9e-05 (Missing values in required field.)
- `daily_bar` `missing_rate:low`: 5.9e-05 (Missing values in required field.)
- `daily_bar` `missing_rate:close`: 5.9e-05 (Missing values in required field.)
- `daily_bar` `missing_rate:volume`: 5.9e-05 (Missing values in required field.)
- `daily_bar` `missing_rate:amount`: 0.124575 (Missing values in required field.)
- `daily_bar` `missing_rate:adj_factor`: 0.000425 (Missing values in required field.)
- `daily_bar` `zero_amount`: 50 (Zero turnover requires suspension/stale-price review.)
- `daily_bar` `amount_spikes`: 1669 (Absolute day-on-day amount change exceeds 2000%.)
- `daily_bar` `adj_factor_jumps`: 931 (Adjustment-factor jump exceeds 50%; verify corporate actions.)
- `daily_basic` `missing_rate:pe_ttm`: 0.00317 (Missing values in required field.)
- `daily_basic` `missing_rate:pb`: 0.080087 (Missing values in required field.)
- `daily_basic` `missing_rate:total_mv`: 0.03061 (Missing values in required field.)
- `daily_basic` `missing_rate:turnover_rate`: 0.113632 (Missing values in required field.)
- `daily_basic` `missing_rate:net_mf_amount`: 0.212873 (Missing values in required field.)
- `index_member` `missing_rate:weight`: 1.0 (Missing values in required field.)
- `financial_indicator` `missing_rate:roe`: 0.029882 (Missing values in required field.)
- `financial_indicator` `missing_rate:gross_margin`: 0.114676 (Missing values in required field.)
- `financial_indicator` `missing_rate:debt_ratio`: 0.024319 (Missing values in required field.)
- `financial_indicator` `missing_rate:revenue_yoy`: 0.116102 (Missing values in required field.)
- `financial_indicator` `missing_rate:profit_yoy`: 0.112793 (Missing values in required field.)
- `limit_price` `missing_rate:up_limit`: 0.000199 (Missing values in required field.)
- `limit_price` `missing_rate:down_limit`: 0.000199 (Missing values in required field.)
- `news_event` `missing_table`: news_event (Expected standardized table is not present.)
- `daily_basic` `daily_bar_key_missing_rate`: 0.001571 (Share of daily-bar asset-date keys missing from this table.)
- `industry` `daily_bar_key_missing_rate`: 0.010549 (Share of daily-bar asset-date keys missing from this table.)
- `limit_price` `daily_bar_key_missing_rate`: 0.089511 (Share of daily-bar asset-date keys missing from this table.)

CSV detail: `data_quality_issues.csv`

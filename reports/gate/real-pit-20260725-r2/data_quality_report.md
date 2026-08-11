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
- `daily_bar` `missing_rate:amount`: 0.12478 (Missing values in required field.)
- `daily_bar` `missing_rate:adj_factor`: 0.000422 (Missing values in required field.)
- `daily_bar` `zero_amount`: 47 (Zero turnover requires suspension/stale-price review.)
- `daily_bar` `amount_spikes`: 1668 (Absolute day-on-day amount change exceeds 2000%.)
- `daily_bar` `adj_factor_jumps`: 931 (Adjustment-factor jump exceeds 50%; verify corporate actions.)
- `daily_basic` `missing_rate:pe_ttm`: 0.002831 (Missing values in required field.)
- `daily_basic` `missing_rate:pb`: 0.06538 (Missing values in required field.)
- `daily_basic` `missing_rate:total_mv`: 0.014951 (Missing values in required field.)
- `daily_basic` `missing_rate:turnover_rate`: 0.05739 (Missing values in required field.)
- `daily_basic` `missing_rate:net_mf_amount`: 0.066911 (Missing values in required field.)
- `index_member` `missing_rate:weight`: 1.0 (Missing values in required field.)
- `financial_indicator` `missing_rate:roe`: 0.025106 (Missing values in required field.)
- `financial_indicator` `missing_rate:gross_margin`: 0.055418 (Missing values in required field.)
- `financial_indicator` `missing_rate:debt_ratio`: 0.021738 (Missing values in required field.)
- `financial_indicator` `missing_rate:revenue_yoy`: 0.101159 (Missing values in required field.)
- `financial_indicator` `missing_rate:profit_yoy`: 0.101959 (Missing values in required field.)
- `limit_price` `missing_rate:up_limit`: 0.000199 (Missing values in required field.)
- `limit_price` `missing_rate:down_limit`: 0.000199 (Missing values in required field.)
- `news_event` `missing_table`: news_event (Expected standardized table is not present.)
- `daily_basic` `daily_bar_key_missing_rate`: 2e-05 (Share of daily-bar asset-date keys missing from this table.)
- `industry` `daily_bar_key_missing_rate`: 0.010564 (Share of daily-bar asset-date keys missing from this table.)
- `limit_price` `daily_bar_key_missing_rate`: 0.088132 (Share of daily-bar asset-date keys missing from this table.)

CSV detail: `data_quality_issues.csv`

# Data Quality Report

- Tables audited: 4
- Blocking issues: 7
- Warnings: 6

## Blocking Issues

- `daily_basic` `missing_table`: daily_basic (Expected standardized table is not present.)
- `financial_indicator` `missing_table`: financial_indicator (Expected standardized table is not present.)
- `index_member` `missing_table`: index_member (Expected standardized table is not present.)
- `industry` `missing_table`: industry (Expected standardized table is not present.)
- `limit_price` `missing_table`: limit_price (Expected standardized table is not present.)
- `st_status` `missing_table`: st_status (Expected standardized table is not present.)
- `suspension` `missing_table`: suspension (Expected standardized table is not present.)

## Warnings

- `daily_bar` `missing_rate:amount`: 0.284061 (Missing values in required field.)
- `daily_bar` `missing_rate:adj_factor`: 0.000834 (Missing values in required field.)
- `daily_bar` `zero_amount`: 2 (Zero turnover requires suspension/stale-price review.)
- `daily_bar` `amount_spikes`: 464 (Absolute day-on-day amount change exceeds 2000%.)
- `daily_bar` `adj_factor_jumps`: 215 (Adjustment-factor jump exceeds 50%; verify corporate actions.)
- `news_event` `missing_table`: news_event (Expected standardized table is not present.)

CSV detail: `data_quality_issues.csv`

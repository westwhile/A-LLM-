# Selected Factors

This report is based on the current in-sample factor diagnostics. It is an input
to walk-forward research, not proof of live tradability or out-of-sample alpha.

| factor | selected | direction | mean_ic | icir | reason |
| --- | --- | --- | ---: | ---: | --- |
| mf_20 | true | 1 | 0.181647 | 1.330456 | direction is positive; selected for next-stage research |
| large_order_mf_20 | false | 1 | 0.176411 | 1.362965 | direction is positive; correlation conflict with mf_20 (0.95) |
| turnover_chg_20 | true | -1 | -0.170638 | -2.419319 | direction is negative; selected for next-stage research |
| size | true | 1 | 0.160068 | 1.332995 | direction is positive; selected for next-stage research |
| roe | true | 1 | 0.153386 | 2.091170 | direction is positive; selected for next-stage research |
| amount_mom_20 | true | 1 | 0.133047 | 1.479408 | direction is positive; selected for next-stage research |
| roa | true | 1 | 0.132804 | 1.488350 | direction is positive; selected for next-stage research |
| revenue_yoy | true | 1 | 0.123494 | 1.189399 | direction is positive; selected for next-stage research |
| debt_ratio | true | 1 | 0.110097 | 1.807070 | direction is positive; selected for next-stage research |
| roe_delta | true | 1 | 0.100524 | 1.126096 | direction is positive; selected for next-stage research |
| ep | true | 1 | 0.092194 | 0.785164 | direction is positive; selected for next-stage research |
| sp | true | 1 | 0.081607 | 0.781155 | direction is positive; selected for next-stage research |
| bp | true | 1 | 0.077285 | 0.696124 | direction is positive; selected for next-stage research |
| gross_margin_stability | true | 1 | 0.076346 | 0.542769 | direction is positive; selected for next-stage research |
| cfp | true | 1 | 0.069914 | 0.681533 | direction is positive; selected for next-stage research |
| asset_turnover | true | 1 | 0.061403 | 0.919202 | direction is positive; selected for next-stage research |
| profit_yoy | true | 1 | 0.053670 | 0.553100 | direction is positive; selected for next-stage research |
| turnover_20 | true | -1 | -0.043894 | -0.544452 | direction is negative; selected for next-stage research |
| mf_5 | true | 1 | 0.040283 | 0.238317 | direction is positive; selected for next-stage research |
| vol_60 | true | -1 | -0.036510 | -1.073284 | direction is negative; selected for next-stage research |
| rev_5 | true | 1 | 0.033462 | 0.301070 | direction is positive; selected for next-stage research |
| mom_20 | true | 1 | 0.020856 | 0.241176 | direction is positive; selected for next-stage research |
| rev_20 | false | -1 | -0.020856 | -0.241176 | direction is negative; correlation conflict with mom_20 (1.00) |
| gross_margin | true | 1 | 0.013333 | 0.172022 | direction is positive; selected for next-stage research |
| vol_20 | true | -1 | -0.010155 | -0.140824 | direction is negative; selected for next-stage research |
| beta_60 | false | -1 | -0.002718 | -0.033769 | abs IC below 0.01; abs ICIR below 0.05 |
| amihud_20 | false | -1 | -0.001572 | -0.019442 | abs IC below 0.01; abs ICIR below 0.05 |
| idio_vol_60 | false | 0 | nan | nan | abs IC below 0.01; abs ICIR below 0.05 |
| mom_60_skip5 | false | 0 | nan | nan | abs IC below 0.01; abs ICIR below 0.05 |
| mom_120 | false | 0 | nan | nan | abs IC below 0.01; abs ICIR below 0.05 |

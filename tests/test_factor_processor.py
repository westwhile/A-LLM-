import unittest

import numpy as np
import pandas as pd

from ashare_factor_research.factors.factor_processor import process_factors, winsorize_mad, zscore_by_date


class FactorProcessorTest(unittest.TestCase):
    def test_winsorize_mad_clips_outlier(self):
        df = pd.DataFrame(
            {
                "trade_date": ["2022-01-01"] * 6,
                "factor": [1, 1, 1, 2, 2, 100],
            }
        )
        out = winsorize_mad(df, "factor", n=2)
        self.assertLess(out["factor"].max(), 100)

    def test_zscore_by_date_has_zero_mean(self):
        df = pd.DataFrame({"trade_date": ["2022-01-01"] * 4, "factor": [1.0, 2.0, 3.0, 4.0]})
        out = zscore_by_date(df, "factor")
        self.assertAlmostEqual(float(out["factor"].mean()), 0.0, places=12)
        self.assertAlmostEqual(float(out["factor"].std(ddof=0)), 1.0, places=12)

    def test_process_factors_can_return_audit_without_changing_keys(self):
        df = pd.DataFrame(
            {
                "trade_date": ["2022-01-01"] * 5,
                "ts_code": [f"{i:06d}.SZ" for i in range(5)],
                "factor": [1.0, 2.0, 3.0, 4.0, 100.0],
                "size": [10.0, 11.0, 12.0, 13.0, 14.0],
                "industry_code": ["A", "A", "B", "B", "B"],
            }
        )
        out, audit = process_factors(
            df,
            ["factor"],
            size_col="size",
            industry_col="industry_code",
            neutralize=False,
            return_audit=True,
        )
        self.assertEqual(len(out), len(df))
        self.assertFalse(out.duplicated(["trade_date", "ts_code"]).any())
        self.assertIn("standardized", set(audit["step"]))


if __name__ == "__main__":
    unittest.main()

import unittest

import numpy as np
import pandas as pd

from ashare_factor_research.factors.factor_processor import winsorize_mad, zscore_by_date


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


if __name__ == "__main__":
    unittest.main()

import unittest

import pandas as pd

from ashare_factor_research.factors.coverage import audit_factor_coverage
from ashare_factor_research.factors.registry import enabled_factor_names, get_factor_specs, load_factor_config


class FactorRegistryCoverageTest(unittest.TestCase):
    def test_config_factors_are_registered(self):
        config = load_factor_config("config/factor_config.yaml")
        names = enabled_factor_names(config)
        specs = get_factor_specs(names)
        self.assertGreaterEqual(len(specs), 15)
        self.assertEqual(set(names), {spec.name for spec in specs})

    def test_coverage_audit_identifies_missing_factor_values(self):
        df = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2022-01-03"] * 4),
                "ts_code": [f"{i:06d}.SZ" for i in range(4)],
                "industry_code": ["A", "A", "B", "B"],
                "size": [1.0, 2.0, 3.0, 4.0],
                "factor": [1.0, None, 3.0, None],
            }
        )
        coverage = audit_factor_coverage(df, ["factor"])
        by_date = coverage["by_date"]
        self.assertAlmostEqual(float(by_date.loc[0, "coverage"]), 0.5)
        self.assertFalse(coverage["by_industry"].empty)
        self.assertFalse(coverage["by_size_bucket"].empty)
        self.assertEqual(int(coverage["missing_streaks"]["max_missing_streak"].max()), 1)


if __name__ == "__main__":
    unittest.main()

"""Offline regression tests for the stage-1D qfq-factor correction.

AkShare 1.18.64 ``stock_zh_a_daily(adjust='qfq-factor')`` returns the Sina
forward-adjustment *divisor* ``qfq_factor_raw``.  The project contract is
``adjusted_price = raw_price * adj_factor``, therefore
``adj_factor = 1 / qfq_factor_raw``.

These tests do not require network access.
"""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from ashare_factor_research.data.data_cleaner import add_adjusted_prices
from scripts.assemble_stage1d_staging import _convert_legacy_adj_factor
from scripts.fetch_stage1d_real import attach_adj_factor


class QfqFactorCorrectionTest(unittest.TestCase):
    def test_adj_factor_is_reciprocal_of_divisor(self):
        """``adj_factor`` must equal ``1 / qfq_factor_raw`` after merge."""
        bars = pd.DataFrame({
            "trade_date": pd.to_datetime(["2022-01-04", "2022-01-05", "2022-01-06"]),
            "ts_code": "000001.SZ",
            "close": [10.0, 10.2, 10.1],
        })
        factors = pd.DataFrame({
            "trade_date": pd.to_datetime(["2022-01-04", "2022-01-06"]),
            "qfq_factor_raw": [2.0, 1.9],
            "adj_factor": [0.5, 1.0 / 1.9],
        })
        merged = attach_adj_factor(bars, factors)
        self.assertIn("qfq_factor_raw", merged.columns)
        self.assertIn("adj_factor", merged.columns)
        expected_adj = 1.0 / merged["qfq_factor_raw"]
        np.testing.assert_allclose(merged["adj_factor"], expected_adj, rtol=1e-12)

    def test_forward_adjusted_return_across_split_is_flat(self):
        """A 1:2 split: raw close and divisor both halve; adjusted return is zero."""
        bars = pd.DataFrame({
            "trade_date": pd.to_datetime(["2022-01-04", "2022-01-05"]),
            "ts_code": "000001.SZ",
            "open": [10.0, 5.0],
            "high": [10.2, 5.1],
            "low": [9.8, 4.9],
            "close": [10.0, 5.0],
            "volume": [1000, 2000],
            "amount": [10000.0, 10000.0],
        })
        # Sina divisor drops from 2 to 1 after the split.
        factors = pd.DataFrame({
            "trade_date": pd.to_datetime(["2022-01-04", "2022-01-05"]),
            "qfq_factor_raw": [2.0, 1.0],
            "adj_factor": [0.5, 1.0],
        })
        merged = attach_adj_factor(bars, factors)
        merged["price_adjustment"] = "raw_close_with_sina_qfq_divisor_snapshot"
        with_adjusted = add_adjusted_prices(merged)
        # Adjusted close is flat at 5.0 both days.
        np.testing.assert_allclose(with_adjusted["adj_close"], [5.0, 5.0], rtol=1e-12)
        # 1-day return is zero.
        self.assertAlmostEqual(float(with_adjusted["return_1d"].iloc[1]), 0.0, places=12)

    def test_legacy_batches_are_converted_to_reciprocal(self):
        """Old batches stored the divisor under ``adj_factor``; assemble converts it."""
        legacy = pd.DataFrame({
            "trade_date": pd.to_datetime(["2022-01-04", "2022-01-05"]),
            "ts_code": "000001.SZ",
            "close": [10.0, 5.0],
            "adj_factor": [2.0, 1.0],
            "price_adjustment": "raw_close_with_sina_qfq_factor_snapshot",
        })
        converted = _convert_legacy_adj_factor(legacy, entry_semantics=None)
        self.assertEqual(converted["price_adjustment"].iloc[0], "raw_close_with_sina_qfq_divisor_snapshot")
        np.testing.assert_allclose(converted["qfq_factor_raw"], [2.0, 1.0], rtol=1e-12)
        np.testing.assert_allclose(converted["adj_factor"], [0.5, 1.0], rtol=1e-12)

    def test_legacy_conversion_rejects_present_invalid_divisor(self):
        """Zero, negative or infinite legacy divisors must raise."""
        for bad_value in [0.0, -1.0, np.inf]:
            with self.subTest(bad_value=bad_value):
                legacy = pd.DataFrame({
                    "trade_date": pd.to_datetime(["2022-01-04"]),
                    "ts_code": "000001.SZ",
                    "close": [10.0],
                    "adj_factor": [bad_value],
                    "price_adjustment": "raw_close_with_sina_qfq_factor_snapshot",
                })
                with self.assertRaises(ValueError):
                    _convert_legacy_adj_factor(legacy, entry_semantics=None)

    def test_legacy_conversion_preserves_missing_divisor_for_coverage_gate(self):
        legacy = pd.DataFrame({
            "trade_date": pd.to_datetime(["2022-01-04"]),
            "ts_code": "689009.SH",
            "close": [10.0],
            "adj_factor": [np.nan],
            "price_adjustment": "raw_close_with_sina_qfq_factor_snapshot",
        })
        converted = _convert_legacy_adj_factor(legacy, entry_semantics=None)
        self.assertTrue(converted["qfq_factor_raw"].isna().all())
        self.assertTrue(converted["adj_factor"].isna().all())

    def test_new_batches_are_not_double_converted(self):
        """Batches already carrying corrected semantics must pass through unchanged."""
        corrected = pd.DataFrame({
            "trade_date": pd.to_datetime(["2022-01-04"]),
            "ts_code": "000001.SZ",
            "close": [10.0],
            "qfq_factor_raw": [2.0],
            "adj_factor": [0.5],
            "price_adjustment": "raw_close_with_sina_qfq_divisor_snapshot",
        })
        out = _convert_legacy_adj_factor(
            corrected,
            entry_semantics="adj_factor = 1 / qfq_factor_raw (Sina qfq-factor divisor snapshot)",
        )
        pd.testing.assert_frame_equal(out, corrected)

    def test_assemble_script_detects_legacy_from_manifest(self):
        """The assemble main loop identifies legacy entries via missing adj_factor_semantics."""
        # We exercise the helper that the assemble loop uses; the manifest field
        # semantics are passed as entry_semantics=None for a legacy batch.
        legacy = pd.DataFrame({
            "trade_date": pd.to_datetime(["2022-01-04"]),
            "ts_code": "000001.SZ",
            "close": [10.0],
            "adj_factor": [2.0],
            "price_adjustment": "raw_close_with_sina_qfq_factor_snapshot",
        })
        converted = _convert_legacy_adj_factor(legacy, entry_semantics=None)
        self.assertIn("qfq_factor_raw", converted.columns)
        self.assertEqual(converted["price_adjustment"].iloc[0], "raw_close_with_sina_qfq_divisor_snapshot")


if __name__ == "__main__":
    unittest.main()

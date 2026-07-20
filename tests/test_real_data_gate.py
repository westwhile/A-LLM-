import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ashare_factor_research.data.data_loader import AkShareProvider
from ashare_factor_research.data.import_standard import import_standard_tables
from ashare_factor_research.data.pit_audit import write_real_data_gate
from ashare_factor_research.data.source_registry import validate_source_registry
from ashare_factor_research.governance.protocol import load_research_protocol


def approved_registry_entry(provider: str = "test-provider") -> dict:
    return {
        "source_type": "local_file",
        "provider": provider,
        "provider_version": "1.0",
        "endpoint_or_file": "recorded_fixture",
        "license_status": "approved_for_research",
        "pit_ready": True,
        "history_start": "2015-01-01",
        "units": {"value": "documented"},
        "evidence_path": "source_review.md",
    }


def valid_real_tables() -> dict[str, pd.DataFrame]:
    dates = pd.to_datetime(["2015-01-05", "2015-01-06", "2015-01-07"])
    codes = ["000001.SZ"] * len(dates)
    return {
        "trade_calendar": pd.DataFrame({"trade_date": dates, "is_open": True}),
        "stock_basic": pd.DataFrame({
            "ts_code": ["000001.SZ"], "name": ["A"],
            "list_date": pd.to_datetime(["2010-01-01"]), "delist_date": [pd.NaT], "exchange": ["SZ"],
        }),
        "daily_bar": pd.DataFrame({
            "trade_date": dates, "ts_code": codes, "open": [10.0, 10.1, 10.2],
            "high": [10.3, 10.4, 10.5], "low": [9.8, 9.9, 10.0], "close": [10.1, 10.2, 10.3],
            "volume": [1000, 1100, 1200], "amount": [10000.0, 11100.0, 12200.0], "adj_factor": [1.0, 1.0, 1.0],
        }),
        "daily_basic": pd.DataFrame({
            "trade_date": dates, "ts_code": codes, "pe_ttm": [10.0] * 3, "pb": [1.0] * 3,
            "total_mv": [1e9] * 3, "turnover_rate": [0.01] * 3, "net_mf_amount": [0.0] * 3,
        }),
        "industry": pd.DataFrame({
            "trade_date": dates, "ts_code": codes, "industry_code": ["I"] * 3, "industry_name": ["Industry"] * 3,
        }),
        "index_member": pd.DataFrame({
            "index_code": ["000905.SH"], "ts_code": ["000001.SZ"], "weight": [1.0],
            "in_date": pd.to_datetime(["2010-01-01"]), "out_date": [pd.NaT],
        }),
        "financial_indicator": pd.DataFrame({
            "report_period": pd.to_datetime(["2014-12-31"]), "ann_date": pd.to_datetime(["2015-01-05"]),
            "usable_date": pd.to_datetime(["2015-01-06"]), "revision_date": pd.to_datetime(["2015-01-05"]),
            "revision_id": [1], "source_id": ["filing-1"], "ts_code": ["000001.SZ"],
            "roe": [0.1], "gross_margin": [0.2], "debt_ratio": [0.3], "revenue_yoy": [0.04], "profit_yoy": [0.05],
        }),
        "suspension": pd.DataFrame(columns=["ts_code", "suspend_date", "resume_date"]),
        "st_status": pd.DataFrame(columns=["ts_code", "start_date", "end_date"]),
        "limit_price": pd.DataFrame({
            "trade_date": dates, "ts_code": codes, "up_limit": [11.0] * 3, "down_limit": [9.0] * 3,
        }),
        "benchmark_index": pd.DataFrame({
            "trade_date": dates, "index_code": ["000905.SH"] * 3, "close": [5000.0, 5010.0, 5020.0],
        }),
    }


class FakeAkShare:
    def __init__(self, fixture: dict):
        self.fixture = fixture
        self.index_symbol = None

    def stock_zh_a_hist(self, **_kwargs):
        return pd.DataFrame(self.fixture["daily_bar"])

    def stock_zh_index_daily_em(self, *, symbol):
        self.index_symbol = symbol
        return pd.DataFrame(self.fixture["benchmark_index"])


class FixtureProvider(AkShareProvider):
    def __init__(self, fake: FakeAkShare):
        super().__init__("2015-01-01", "2015-01-07", symbols=["000001.SZ"], index_code="000905.SH")
        self.fake = fake

    def _akshare(self):
        return self.fake


class RealDataGateTest(unittest.TestCase):
    def test_frozen_real_protocol_is_valid(self):
        protocol = load_research_protocol("config/research_protocol.real.yaml")
        self.assertEqual(protocol["data_start"], "2015-01-01")
        self.assertEqual(protocol["final_holdout_start"], "2024-01-01")
        self.assertEqual(protocol["minimum_oos_months"], 36)
        self.assertEqual(len(protocol["protocol_sha256"]), 64)

    def test_checked_in_source_registry_review_state(self):
        import yaml

        registry = yaml.safe_load(Path("config/data_source_registry.yaml").read_text(encoding="utf-8"))
        tables = registry["tables"]
        approved = {
            name for name, entry in tables.items() if entry.get("license_status") == "approved_for_research"
        }
        self.assertEqual(approved, {"trade_calendar", "benchmark_index", "daily_bar", "stock_basic"})
        self.assertEqual(registry.get("review_status"), "pending_user_review")
        for table in sorted(approved):
            result = validate_source_registry(
                registry, [table], evidence_base=Path("config")
            )
            self.assertTrue(result.is_valid, f"{table} should be import-ready: {result.errors}")
        for table in ["index_member", "daily_basic", "financial_indicator", "industry",
                      "suspension", "st_status", "limit_price"]:
            result = validate_source_registry(registry, [table])
            self.assertFalse(result.is_valid, f"{table} must remain blocked pending user data")
            self.assertTrue(any("license_status" in error for error in result.errors))

    def test_real_gate_writes_all_specialized_audits(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {
                "mode": "real", "import_gate_status": "ready_for_quality_audit",
                "source_registry_sha256": "abc", "source_registry_validation": {"valid": True, "errors": []},
                "review_status": "approved", "reviewed_by": "test-user", "reviewed_at": "2026-07-19T10:00:00",
            }
            summary = write_real_data_gate(valid_real_tables(), tmp, source_manifest=manifest)
            self.assertEqual(summary["status"], "passed")
            for name in [
                "pit_timing_audit.csv", "financial_revision_audit.csv", "survivorship_audit.csv",
                "universe_coverage.csv", "benchmark_alignment.csv", "data_gate_summary.json",
            ]:
                self.assertTrue((Path(tmp) / name).exists())

    def test_real_gate_blocks_when_registry_not_signed(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {
                "mode": "real", "import_gate_status": "ready_for_quality_audit",
                "source_registry_sha256": "abc", "source_registry_validation": {"valid": True, "errors": []},
                "review_status": "pending_user_review", "reviewed_by": None, "reviewed_at": None,
            }
            summary = write_real_data_gate(valid_real_tables(), tmp, source_manifest=manifest)
            self.assertEqual(summary["status"], "blocked_by_pit_quality")
            reasons = ";".join(summary["blocking_reasons"])
            self.assertIn("review_status", reasons)
            self.assertIn("reviewed_by", reasons)
            self.assertIn("reviewed_at", reasons)

    def test_real_gate_blocks_future_revision_and_low_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            tables = valid_real_tables()
            tables["financial_indicator"].loc[0, "revision_date"] = pd.Timestamp("2015-01-07")
            tables["daily_basic"] = tables["daily_basic"].iloc[:1]
            manifest = {
                "mode": "real", "import_gate_status": "ready_for_quality_audit",
                "source_registry_sha256": "abc", "source_registry_validation": {"valid": True, "errors": []},
                "review_status": "approved", "reviewed_by": "test-user", "reviewed_at": "2026-07-19T10:00:00",
            }
            summary = write_real_data_gate(tables, tmp, source_manifest=manifest)
            self.assertEqual(summary["status"], "blocked_by_pit_quality")
            self.assertTrue(any("pit_timing_audit" in reason for reason in summary["blocking_reasons"]))
            self.assertTrue(any("universe_coverage" in reason for reason in summary["blocking_reasons"]))

    def test_real_import_preserves_explicit_financial_revisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            financial = valid_real_tables()["financial_indicator"]
            second = financial.copy()
            second["revision_id"] = 2
            second["revision_date"] = pd.Timestamp("2015-01-06")
            second["usable_date"] = pd.Timestamp("2015-01-07")
            pd.concat([financial, second], ignore_index=True).to_csv(source / "financial_indicator.csv", index=False)
            registry_path = root / "registry.yaml"
            (root / "source_review.md").write_text("approved test fixture", encoding="utf-8")
            registry_path.write_text(json.dumps({
                "schema_version": 1, "tables": {"financial_indicator": approved_registry_entry()}
            }), encoding="utf-8")
            output = root / "standard"
            manifest = import_standard_tables(
                source, output, output_format="csv", mode="real", source_registry_path=registry_path
            )
            imported = pd.read_csv(output / "financial_indicator.csv")
            self.assertEqual(len(imported), 2)
            self.assertEqual(manifest["import_gate_status"], "blocked_by_missing_pit_tables")

    def test_real_import_blocks_unsigned_registry_when_all_tables_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            tables = valid_real_tables()
            for name, df in tables.items():
                if name == "news_event":
                    continue
                df.to_csv(source / f"{name}.csv", index=False)
            registry_path = root / "registry.yaml"
            (root / "source_review.md").write_text("approved test fixture", encoding="utf-8")
            entries = {name: approved_registry_entry() for name in tables if name != "news_event"}
            registry_path.write_text(json.dumps({
                "schema_version": 1,
                "review_status": "pending_user_review",
                "reviewed_by": None,
                "reviewed_at": None,
                "tables": entries,
            }), encoding="utf-8")
            output = root / "standard"
            with self.assertRaises(ValueError) as ctx:
                import_standard_tables(
                    source, output, output_format="csv", mode="real", source_registry_path=registry_path
                )
            self.assertIn("not signed", str(ctx.exception))

    def test_recorded_akshare_fixture_is_offline_and_schema_mapped(self):
        fixture = json.loads(Path("tests/fixtures/akshare_responses.json").read_text(encoding="utf-8"))
        fake = FakeAkShare(fixture)
        provider = FixtureProvider(fake)
        bars = provider.load_daily_bar()
        benchmark = provider.load_benchmark_index()
        self.assertEqual(list(bars["ts_code"]), ["000001.SZ"])
        self.assertEqual(bars.loc[0, "price_adjustment"], "unadjusted_placeholder_factor")
        self.assertEqual(fake.index_symbol, "csi000905")
        self.assertEqual(float(benchmark.loc[0, "close"]), 5030.0)


if __name__ == "__main__":
    unittest.main()

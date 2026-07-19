import csv
import json
from pathlib import Path
import unittest
import urllib.request

from ashare_factor_research.data.ifind_gate import (
    IFindGateError,
    ProbeScope,
    build_preflight_manifest,
    execute_http_probe,
    load_probe_scope,
)
from datetime import date


def make_scope(**overrides):
    values = {
        "endpoint": "https://quantapi.51ifind.com/api/v1/cmd_history_quotation",
        "codes": ("300033.SZ", "600030.SH"),
        "indicators": ("open", "close", "volume"),
        "start_date": date(2024, 1, 2),
        "end_date": date(2024, 1, 4),
        "function_parameters": {"CPS": "1", "Fill": "Omit", "Interval": "D"},
    }
    values.update(overrides)
    return ProbeScope(**values)


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self, _limit):
        return self.payload

    def getcode(self):
        return 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class IFindGateTest(unittest.TestCase):
    def test_checked_in_config_and_gap_matrix_are_gate_valid(self):
        scope = load_probe_scope("config/ifind_field_mapping.example.yaml")
        scope.validate()
        with Path("data_source_gap_matrix.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertTrue(rows)
        self.assertEqual(len({row["required_field"] for row in rows}), len(rows))
        allowed = {"open_source", "ifind_licensed", "unavailable", "rejected_for_pit"}
        self.assertTrue(all(row["decision"] in allowed for row in rows))
        self.assertTrue(all(row["evidence_path"] for row in rows))

    def test_scope_rejects_expansion(self):
        with self.assertRaises(IFindGateError):
            make_scope(codes=("300033.SZ", "600030.SH", "000001.SZ")).validate()
        with self.assertRaises(IFindGateError):
            make_scope(indicators=("open", "close", "volume", "amount")).validate()

    def test_preflight_never_serializes_token(self):
        token = "top-secret-access-token"
        manifest = build_preflight_manifest(make_scope(), env={"IFIND_ACCESS_TOKEN": token})
        encoded = json.dumps(manifest, ensure_ascii=False)
        self.assertNotIn(token, encoded)
        self.assertEqual(manifest["gate_status"], "ready_not_executed")
        self.assertFalse(manifest["execution"]["network_request_sent"])

    def test_http_probe_keeps_raw_data_out_of_result(self):
        token = "top-secret-access-token"
        raw = json.dumps(
            {
                "errorcode": 0,
                "errmsg": "",
                "dataVol": 18,
                "tables": [{"table": {"close": [99.99]}}],
            }
        ).encode("utf-8")
        captured = {}

        def fake_open(request: urllib.request.Request, timeout: float):
            captured["url"] = request.full_url
            captured["token"] = request.get_header("Access_token")
            captured["timeout"] = timeout
            return FakeResponse(raw)

        result = execute_http_probe(make_scope(), token, timeout=5.0, open_request=fake_open)
        self.assertEqual(result["status"], "success")
        self.assertEqual(captured["token"], token)
        self.assertEqual(captured["timeout"], 5.0)
        encoded = json.dumps(result, ensure_ascii=False)
        self.assertNotIn(token, encoded)
        self.assertNotIn("99.99", encoded)
        self.assertFalse(result["raw_response_persisted"])


if __name__ == "__main__":
    unittest.main()

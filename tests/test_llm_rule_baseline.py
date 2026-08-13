"""R1-E1 规则基准 artifact 与 TextDatasetManifest schema 草案的单元测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ashare_factor_research.data.provenance import dataframe_sha256
from ashare_factor_research.llm.client import RuleBasedEventLabeler, batch_label_events
from ashare_factor_research.llm.prompts import PROMPT_VERSION
from ashare_factor_research.llm.rule_baseline import (
    LABELS_FILENAME,
    MANIFEST_FILENAME,
    build_rule_baseline_artifact,
    validate_rule_baseline_artifact,
    write_rule_baseline_artifact,
)
from ashare_factor_research.llm.rule_lexicon import (
    RULE_LEXICON_VERSION,
    RuleLexicon,
    default_rule_lexicon,
    lexicon_sha256,
)
from ashare_factor_research.llm.text_manifest import (
    build_text_dataset_manifest,
    text_manifest_sha256,
    validate_text_dataset_manifest,
)


def _sample_raw() -> pd.DataFrame:
    return pd.DataFrame({
        "event_id": ["e1", "e2", "e3", "e4"],
        "stock_code": ["000001.SZ", "000001.SZ", "000002.SZ", "000002.SZ"],
        "title": ["年度利润增长", "净利润亏损", "重大诉讼公告", "例行会议通知"],
        "content": ["公司年度利润增长 30%", "公司净利润亏损扩大", "公司涉及重大诉讼", "公司召开例行会议"],
        "source": ["exchange"] * 4,
        "publish_time": ["2022-01-03 18:00:00", "2022-01-04 18:00:00", "2022-01-05 18:00:00", "2022-01-06 18:00:00"],
    })


def _valid_manifest_kwargs() -> dict:
    return {
        "dataset_id": "sample-news-v1",
        "source": {"provider": "sample", "collection": "sample_news", "access_channel": "local"},
        "license_info": {"category": "research_only", "approved": False, "restrictions": ["no redistribution"]},
        "pit": {
            "publish_time_field": "publish_time",
            "available_time_rule": "15:00 前当日可用，否则次一交易日",
            "revision_handling": "保留 first_seen，修订另行登记",
        },
        "dedup": {"dedup_key": ["event_id"], "near_dup_rule": None},
        "entity_mapping": {"stock_code_field": "stock_code", "mapping_source": "sample_registry"},
        "coverage": {"start_date": "2022-01-01", "end_date": "2022-12-31", "universe": "sample"},
    }


class RuleLexiconTest(unittest.TestCase):
    def test_default_lexicon_matches_legacy_labeler_behavior(self):
        labeler = RuleBasedEventLabeler()
        growth = labeler.label_event("", {"title": "利润增长", "content": ""})
        self.assertEqual(growth["event_type"], "earnings_growth")
        self.assertEqual(growth["sentiment"], "positive")
        decline = labeler.label_event("", {"title": "", "content": "净利润亏损"})
        self.assertEqual(decline["event_type"], "earnings_decline")
        litigation = labeler.label_event("", {"title": "重大诉讼", "content": ""})
        self.assertEqual(litigation["event_type"], "litigation")
        other = labeler.label_event("", {"title": "例行通知", "content": ""})
        self.assertEqual(other["event_type"], "other")
        self.assertEqual(other["sentiment"], "neutral")

    def test_lexicon_hash_is_stable_and_sensitive(self):
        lexicon = default_rule_lexicon()
        self.assertEqual(lexicon.version, RULE_LEXICON_VERSION)
        self.assertEqual(lexicon_sha256(lexicon), lexicon_sha256(default_rule_lexicon()))
        changed = RuleLexicon(
            version=lexicon.version,
            growth_keywords=lexicon.growth_keywords + ("超预期",),
            negative_keywords=lexicon.negative_keywords,
            litigation_keywords=lexicon.litigation_keywords,
        )
        self.assertNotEqual(lexicon_sha256(lexicon), lexicon_sha256(changed))

    def test_custom_lexicon_changes_labeling(self):
        lexicon = RuleLexicon(
            version="rule_lexicon_test",
            growth_keywords=("回购",),
            negative_keywords=("减持",),
            litigation_keywords=("仲裁",),
        )
        labeler = RuleBasedEventLabeler(lexicon=lexicon)
        payload = labeler.label_event("", {"title": "大额回购", "content": ""})
        self.assertEqual(payload["event_type"], "earnings_growth")
        payload = labeler.label_event("", {"title": "股东仲裁与减持", "content": ""})
        self.assertEqual(payload["event_type"], "litigation")


class TextDatasetManifestTest(unittest.TestCase):
    def test_build_and_validate_ok(self):
        manifest = build_text_dataset_manifest(**_valid_manifest_kwargs())
        validate_text_dataset_manifest(manifest)
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["status"], "draft")

    def test_approved_status_requires_signed_license(self):
        kwargs = _valid_manifest_kwargs()
        kwargs["status"] = "approved"
        with self.assertRaises(ValueError):
            build_text_dataset_manifest(**kwargs)
        kwargs["license_info"] = {**kwargs["license_info"], "approved": True}
        with self.assertRaises(ValueError):
            build_text_dataset_manifest(**kwargs)
        kwargs["license_info"] = {**kwargs["license_info"], "signoff_ref": "reports/data_sources/signoff_sheet_x.md"}
        manifest = build_text_dataset_manifest(**kwargs)
        self.assertEqual(manifest["status"], "approved")

    def test_missing_pit_and_dedup_keys_raise(self):
        kwargs = _valid_manifest_kwargs()
        del kwargs["pit"]["available_time_rule"]
        with self.assertRaises(ValueError):
            build_text_dataset_manifest(**kwargs)
        kwargs = _valid_manifest_kwargs()
        kwargs["dedup"] = {"dedup_key": []}
        with self.assertRaises(ValueError):
            build_text_dataset_manifest(**kwargs)

    def test_manifest_hash_ignores_created_at(self):
        manifest = build_text_dataset_manifest(**_valid_manifest_kwargs())
        digest = text_manifest_sha256(manifest)
        self.assertEqual(digest, text_manifest_sha256(manifest))
        shifted = {**manifest, "created_at": "2099-01-01T00:00:00"}
        self.assertEqual(digest, text_manifest_sha256(shifted))
        renamed = {**manifest, "dataset_id": "sample-news-v2"}
        self.assertNotEqual(digest, text_manifest_sha256(renamed))


class RuleBaselineArtifactTest(unittest.TestCase):
    def test_build_from_batch_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            labels = batch_label_events(_sample_raw(), cache_path=Path(tmp) / "cache.jsonl")
        artifact = build_rule_baseline_artifact(labels)
        validate_rule_baseline_artifact(artifact)
        self.assertEqual(artifact["artifact_type"], "r1_e1_rule_baseline")
        self.assertEqual(artifact["labels"]["rows"], 4)
        self.assertEqual(artifact["labels"]["sha256"], dataframe_sha256(labels))
        self.assertEqual(artifact["labels"]["event_type_distribution"]["earnings_growth"], 1)
        self.assertEqual(artifact["labels"]["event_type_distribution"]["litigation"], 1)
        self.assertEqual(artifact["labels"]["sentiment_distribution"]["neutral"], 1)
        self.assertEqual(artifact["model"], "rule-based-event-labeler-v1")
        self.assertEqual(artifact["prompt_version"], PROMPT_VERSION)
        self.assertEqual(artifact["rule_lexicon"]["version"], RULE_LEXICON_VERSION)
        self.assertEqual(artifact["rule_lexicon"]["sha256"], lexicon_sha256(default_rule_lexicon()))
        self.assertEqual(artifact["coverage"]["unique_stocks"], 2)
        self.assertEqual(artifact["coverage"]["first_publish_date"], "2022-01-03")
        self.assertIsNone(artifact["text_manifest_sha256"])
        self.assertFalse(artifact["quality"]["reviewed"])

    def test_write_artifact_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            labels = batch_label_events(_sample_raw(), cache_path=Path(tmp) / "cache.jsonl")
            out_dir = Path(tmp) / "artifact"
            manifest = write_rule_baseline_artifact(labels, out_dir, text_manifest=build_text_dataset_manifest(**_valid_manifest_kwargs()))
            self.assertTrue((out_dir / LABELS_FILENAME).exists())
            self.assertTrue((out_dir / MANIFEST_FILENAME).exists())
            on_disk = json.loads((out_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(on_disk, manifest)
            validate_rule_baseline_artifact(on_disk)
            self.assertIsNotNone(manifest["text_manifest_sha256"])

    def test_multi_model_labels_rejected(self):
        labels = batch_label_events(_sample_raw())
        labels.loc[labels.index[0], "model"] = "other-model"
        with self.assertRaises(ValueError):
            build_rule_baseline_artifact(labels)

    def test_empty_labels_produce_empty_artifact(self):
        artifact = build_rule_baseline_artifact(pd.DataFrame())
        validate_rule_baseline_artifact(artifact)
        self.assertEqual(artifact["labels"]["rows"], 0)
        self.assertEqual(artifact["labels"]["event_type_distribution"], {})
        self.assertEqual(artifact["coverage"]["unique_stocks"], 0)
        self.assertIsNone(artifact["coverage"]["first_publish_date"])


if __name__ == "__main__":
    unittest.main()

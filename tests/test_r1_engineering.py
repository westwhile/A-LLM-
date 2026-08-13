"""Engineering acceptance tests for the R1 text-representation boundary."""

from __future__ import annotations

from dataclasses import replace
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from ashare_factor_research.llm.aggregation import (
    aggregate_text_representation,
    build_text_feature_artifact,
)
from ashare_factor_research.llm.audit import build_stratified_review_queue
from ashare_factor_research.llm.client import RuleBasedEventLabeler, batch_label_events
from ashare_factor_research.llm.embedding import (
    EmbeddingSpec,
    batch_embed_events,
    embedding_cache_key,
    expand_embedding_features,
)
from ashare_factor_research.llm.evaluator import (
    FrozenLinearEvaluatorSpec,
    build_negative_control_features,
    evaluate_representation_increment,
    evaluator_spec_sha256,
    write_r1_evaluation_artifacts,
)
from ashare_factor_research.llm.r1_protocol import (
    load_r1_protocol,
    r1_protocol_sha256,
    validate_r1_protocol,
    write_r1_protocol_receipt,
)
from ashare_factor_research.llm.representation import (
    build_label_representation,
    build_text_representation_artifact,
    validate_text_representation_artifact,
    write_text_representation_artifact,
)
from ashare_factor_research.llm.rule_lexicon import RuleLexicon, default_rule_lexicon
from ashare_factor_research.llm.text_dataset import (
    find_near_duplicate_candidates,
    prepare_text_events,
    select_signal_ready_events,
    write_text_preparation_artifacts,
)
from ashare_factor_research.llm.text_manifest import (
    assess_text_manifest_research_readiness,
    build_text_dataset_manifest,
)


def _raw_events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_id": ["e1", "e2", "e3", "e4"],
            "stock_code": ["000001.SZ", "000001.SZ", "000001.SZ", "999999.SZ"],
            "title": ["年度利润增长", "年度 利润 增长", "年度利润增长30%", "重大诉讼"],
            "content": ["公司年度利润增长30%", "公司年度利润增长30%", "公司年度利润增长31%", "公司涉及诉讼"],
            "source": ["exchange"] * 4,
            "publish_time": [
                "2022-01-03 14:00:00",
                "2022-01-03 14:05:00",
                "2022-01-04 09:00:00",
                "2022-01-04 16:00:00",
            ],
            "available_time": [
                "2022-01-03 14:10:00",
                "2022-01-03 14:15:00",
                "2022-01-04 09:10:00",
                "2022-01-05 09:30:00",
            ],
        }
    )


def _draft_manifest() -> dict:
    return build_text_dataset_manifest(
        dataset_id="sample-news-v1",
        source={"provider": "sample", "collection": "sample_news", "access_channel": "local"},
        license_info={"category": "research_only", "approved": False, "restrictions": ["no redistribution"]},
        pit={
            "publish_time_field": "publish_time",
            "available_time_rule": "collector supplies reviewed available_time",
            "revision_handling": "retain every revision",
        },
        dedup={"dedup_key": ["event_id"]},
        entity_mapping={"stock_code_field": "stock_code", "mapping_source": "sample_registry"},
        coverage={"start_date": "2022-01-01", "end_date": "2022-12-31", "universe": "sample"},
    )


class CountingEmbedder:
    def __init__(self, spec: EmbeddingSpec) -> None:
        self.spec = spec
        self.calls = 0

    def encode(self, texts: list[str]) -> np.ndarray:
        self.calls += 1
        return np.asarray(
            [[float(len(text)), float(sum(ord(character) for character in text) % 101)] for text in texts],
            dtype=float,
        )


class TextPreparationTest(unittest.TestCase):
    def test_preparation_preserves_pit_and_builds_review_queues(self):
        result = prepare_text_events(
            _raw_events(),
            stock_registry=["000001.SZ"],
            near_duplicate_threshold=0.5,
        )
        self.assertEqual(len(result.events), 4)
        self.assertTrue(result.events["raw_text_sha256"].str.fullmatch(r"[0-9a-f]{64}").all())
        self.assertGreaterEqual(len(result.near_duplicate_candidates), 1)
        self.assertEqual(result.entity_review_queue["event_id"].tolist(), ["e4"])
        ready = select_signal_ready_events(result.events, "2022-01-04 12:00:00")
        self.assertNotIn("e4", set(ready["event_id"]))
        self.assertTrue((pd.to_datetime(ready["available_time"]) <= pd.Timestamp("2022-01-04 12:00:00")).all())
        self.assertEqual(result.quality_report["status"], "engineering_complete_human_review_pending")

    def test_preparation_rejects_inferred_or_impossible_availability(self):
        with self.assertRaises(ValueError):
            prepare_text_events(_raw_events().drop(columns="available_time"))
        invalid = _raw_events()
        invalid.loc[0, "available_time"] = "2022-01-03 13:59:00"
        with self.assertRaises(ValueError):
            prepare_text_events(invalid)

    def test_exact_duplicates_are_not_silently_deleted(self):
        raw = _raw_events()
        raw.loc[1, ["title", "content"]] = raw.loc[0, ["title", "content"]].to_numpy()
        result = prepare_text_events(raw, stock_registry=["000001.SZ"])
        self.assertEqual(len(result.events), 4)
        self.assertEqual(int(result.events["is_exact_duplicate"].sum()), 2)
        selected = select_signal_ready_events(result.events, "2022-01-06")
        self.assertEqual(len(selected[selected["stock_code"].eq("000001.SZ")]), 2)

    def test_artifact_writer_emits_all_review_files(self):
        result = prepare_text_events(_raw_events(), stock_registry=["000001.SZ"])
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_text_preparation_artifacts(result, tmp)
            self.assertEqual(set(paths), {"events", "near_duplicates", "entity_review", "quality"})
            self.assertTrue(all(Path(path).exists() for path in paths.values()))

    def test_near_duplicate_parameters_are_validated(self):
        prepared = prepare_text_events(_raw_events()).events
        with self.assertRaises(ValueError):
            find_near_duplicate_candidates(prepared, threshold=1.1)


class CacheAndEmbeddingTest(unittest.TestCase):
    def test_rule_lexicon_changes_cache_key_and_retains_old_cache_entry(self):
        raw = _raw_events().iloc[[0]].drop(columns="available_time")
        default = RuleBasedEventLabeler()
        changed_lexicon = RuleLexicon(
            version="custom-v1",
            growth_keywords=default.lexicon.growth_keywords + ("扩产",),
            negative_keywords=default.lexicon.negative_keywords,
            litigation_keywords=default.lexicon.litigation_keywords,
        )
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "labels.jsonl"
            first = batch_label_events(raw, labeler=default, cache_path=cache)
            second = batch_label_events(raw, labeler=RuleBasedEventLabeler(changed_lexicon), cache_path=cache)
            self.assertNotEqual(first.iloc[0]["cache_key"], second.iloc[0]["cache_key"])
            self.assertEqual(len(cache.read_text(encoding="utf-8").splitlines()), 2)

    def test_embedding_cache_invalidates_on_spec_change(self):
        prepared = prepare_text_events(_raw_events().iloc[:2], stock_registry=["000001.SZ"]).events
        spec = EmbeddingSpec(
            model_id="offline-test-encoder",
            model_revision="weights-sha-v1",
            tokenizer_revision="tokenizer-sha-v1",
            preprocessing_version="prep-v1",
            pooling="mean",
            dimension=2,
            max_length=128,
            license_status="research_only",
        )
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "embeddings.jsonl"
            first_embedder = CountingEmbedder(spec)
            first = batch_embed_events(prepared, first_embedder, cache_path=cache)
            self.assertEqual(first_embedder.calls, 1)
            second_embedder = CountingEmbedder(spec)
            second = batch_embed_events(prepared, second_embedder, cache_path=cache)
            self.assertEqual(second_embedder.calls, 0)
            self.assertEqual(first["cache_key"].tolist(), second["cache_key"].tolist())
            changed = replace(spec, pooling="cls")
            self.assertNotEqual(
                embedding_cache_key(prepared.iloc[0]["raw_text_sha256"], spec),
                embedding_cache_key(prepared.iloc[0]["raw_text_sha256"], changed),
            )

    def test_embedding_output_shape_and_feature_expansion(self):
        prepared = prepare_text_events(_raw_events().iloc[:2], stock_registry=["000001.SZ"]).events
        spec = EmbeddingSpec("test", "v1", "tok-v1", "prep-v1", "mean", 2, 64, "research_only")
        rows = batch_embed_events(prepared, CountingEmbedder(spec))
        features = expand_embedding_features(rows)
        self.assertIn("text_emb_0000", features)
        self.assertIn("text_emb_0001", features)

    def test_embedding_spec_rejects_none_disguised_as_text(self):
        spec = EmbeddingSpec("test", None, "tok", "prep", "mean", 2, 64, "research_only")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            embedding_cache_key("a" * 64, spec)


class RepresentationAndProtocolTest(unittest.TestCase):
    def test_label_representation_drops_raw_text_and_stays_draft(self):
        raw = _raw_events().iloc[:2]
        prepared = prepare_text_events(raw, stock_registry=["000001.SZ"]).events
        labels = batch_label_events(raw.drop(columns="available_time"))
        rows = build_label_representation(prepared, labels)
        self.assertNotIn("raw_text", rows)
        manifest = build_text_representation_artifact(
            rows,
            representation_id="R1-E1-rule-v1",
            model_card={
                "model_id": "rule-based-event-labeler-v1",
                "model_revision": "rule_lexicon_v1",
                "preprocessing_version": "r1_text_preparation_v1",
                "intended_use": "transparent R1 baseline",
                "license_status": "internal_only",
            },
            preprocessing={"normalization": "NFKC and whitespace collapse"},
            aggregation={"level": "event", "deduplication": "exact group keep first at signal cutoff"},
            text_manifest=_draft_manifest(),
            status="draft",
        )
        validate_text_representation_artifact(manifest)
        self.assertFalse(manifest["text_manifest_readiness"]["ready"])
        self.assertEqual(manifest["evaluation"]["status"], "not_run")
        with self.assertRaises(ValueError):
            build_text_representation_artifact(
                rows,
                representation_id="R1-E1-rule-v1",
                model_card=manifest["model_card"],
                preprocessing=manifest["preprocessing"],
                aggregation=manifest["aggregation"],
                text_manifest=_draft_manifest(),
                quality={"reviewed": True},
                evaluation={"status": "accepted"},
                status="accepted",
            )

    def test_representation_writer_round_trip(self):
        raw = _raw_events().iloc[:1]
        prepared = prepare_text_events(raw, stock_registry=["000001.SZ"]).events
        labels = batch_label_events(raw.drop(columns="available_time"))
        rows = build_label_representation(prepared, labels)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = write_text_representation_artifact(
                rows,
                tmp,
                representation_id="R1-E1-rule-v1",
                model_card={
                    "model_id": "rule-based-event-labeler-v1",
                    "model_revision": "rule_lexicon_v1",
                    "preprocessing_version": "r1_text_preparation_v1",
                    "intended_use": "transparent R1 baseline",
                    "license_status": "internal_only",
                },
                preprocessing={"normalization": "NFKC"},
                aggregation={"level": "event"},
            )
            self.assertEqual(manifest["status"], "draft")
            self.assertTrue((Path(tmp) / "text_representation.csv").exists())
            on_disk = json.loads((Path(tmp) / "text_representation_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(on_disk, manifest)

    def test_review_queue_is_deterministic_and_stratified(self):
        labels = batch_label_events(_raw_events().drop(columns="available_time"))
        first = build_stratified_review_queue(labels, sample_size=3, random_state=7)
        second = build_stratified_review_queue(labels, sample_size=3, random_state=7)
        self.assertEqual(first["event_id"].tolist(), second["event_id"].tolist())
        self.assertTrue(first["review_status"].eq("pending").all())
        self.assertIn("sampling_stratum", first)

    def test_draft_protocol_loads_and_freeze_requires_human_signoff(self):
        path = Path(__file__).parents[1] / "config" / "r1_protocol.template.yaml"
        protocol = load_r1_protocol(path)
        validate_r1_protocol(protocol)
        digest = r1_protocol_sha256(protocol)
        self.assertEqual(len(digest), 64)
        frozen = {**protocol, "status": "frozen"}
        with self.assertRaises(ValueError):
            validate_r1_protocol(frozen)
        with tempfile.TemporaryDirectory() as tmp:
            receipt = write_r1_protocol_receipt(protocol, Path(tmp) / "receipt.json")
            self.assertFalse(receipt["research_ready"])

    def test_completed_protocol_requires_final_holdout_access_receipt(self):
        path = Path(__file__).parents[1] / "config" / "r1_protocol.template.yaml"
        protocol = load_r1_protocol(path)
        completed = {
            **protocol,
            "status": "completed",
            "data": {
                **protocol["data"],
                "text_manifest_sha256": "a" * 64,
                "structured_feature_manifest_sha256": "b" * 64,
            },
            "split": {
                **protocol["split"],
                "final_holdout_start": "2024-01-01",
                "final_holdout_accessed": True,
            },
            "evaluator": {
                **protocol["evaluator"],
                "frozen_during_representation_comparison": True,
            },
            "human_signoff": {
                "approved_by": "researcher",
                "approved_at": "2026-08-13",
                "approval_ref": "protocol-signoff",
            },
        }
        with self.assertRaises(ValueError):
            validate_r1_protocol(completed)
        completed["split"]["final_holdout_access_ref"] = "holdout-access-receipt"
        validate_r1_protocol(completed)

    def test_manifest_readiness_separates_schema_from_human_acceptance(self):
        readiness = assess_text_manifest_research_readiness(_draft_manifest())
        self.assertFalse(readiness["ready"])
        self.assertIn("status must be approved or frozen", readiness["failures"])

    def test_representation_model_card_rejects_none_disguised_as_text(self):
        raw = _raw_events().iloc[:1]
        prepared = prepare_text_events(raw, stock_registry=["000001.SZ"]).events
        labels = batch_label_events(raw.drop(columns="available_time"))
        rows = build_label_representation(prepared, labels)
        with self.assertRaises(ValueError):
            build_text_representation_artifact(
                rows,
                representation_id="R1-E1-rule-v1",
                model_card={
                    "model_id": "rule",
                    "model_revision": None,
                    "preprocessing_version": "prep",
                    "intended_use": "test",
                    "license_status": "internal_only",
                },
                preprocessing={"normalization": "NFKC"},
                aggregation={"level": "event"},
            )


class FrozenEvaluatorTest(unittest.TestCase):
    @staticmethod
    def _panel() -> pd.DataFrame:
        rows = []
        dates = pd.date_range("2020-01-31", periods=14, freq="ME")
        for date_index, signal_date in enumerate(dates):
            for asset_index in range(5):
                base = float(asset_index - 2)
                text = float((asset_index + date_index) % 5 - 2)
                rows.append(
                    {
                        "signal_date": signal_date,
                        "label_end_date": signal_date + pd.Timedelta(days=20),
                        "ts_code": f"{asset_index:06d}.SZ",
                        "base_feature": base,
                        "text_feature": text,
                        "target_return": 0.01 * base + 0.02 * text,
                    }
                )
        return pd.DataFrame(rows)

    def test_fixed_evaluator_keeps_common_sample_and_purges_labels(self):
        spec = FrozenLinearEvaluatorSpec(
            evaluator_id="R1-LINEAR-TEST",
            train_months=8,
            embargo_days=5,
            ridge_alpha=0.1,
            min_train_dates=4,
            min_assets_per_test_date=3,
        )
        result = evaluate_representation_increment(
            self._panel(),
            base_features=["base_feature"],
            text_features=["text_feature"],
            spec=spec,
        )
        metrics = result["metrics"]
        predictions = result["predictions"]
        self.assertFalse(metrics.empty)
        self.assertTrue(metrics["leakage_check_passed"].all())
        self.assertTrue((metrics["train_label_end_max"] < metrics["purge_cutoff"]).all())
        counts = predictions.groupby(["test_date", "variant"]).size().unstack()
        self.assertTrue(counts["base"].eq(counts["base_plus_text"]).all())
        self.assertGreater(result["summary"]["increment"]["mean_mse_reduction"], 0)
        self.assertEqual(len(evaluator_spec_sha256(spec)), 64)
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_r1_evaluation_artifacts(result, tmp)
            self.assertTrue(all(Path(path).exists() for path in paths.values()))

    def test_fixed_evaluator_refuses_implicit_missingness_and_holdout_access(self):
        panel = self._panel()
        panel.loc[0, "text_feature"] = np.nan
        spec = FrozenLinearEvaluatorSpec(evaluator_id="R1-LINEAR-TEST", final_holdout_start="2021-01-01")
        with self.assertRaises(ValueError):
            evaluate_representation_increment(
                panel,
                base_features=["base_feature"],
                text_features=["text_feature"],
                spec=spec,
            )
        clean = self._panel()
        with self.assertRaises(ValueError):
            evaluate_representation_increment(
                clean,
                base_features=["base_feature"],
                text_features=["text_feature"],
                spec=spec,
                allow_final_holdout=True,
            )

    def test_negative_controls_are_deterministic_and_leave_target_untouched(self):
        panel = self._panel()
        permuted = build_negative_control_features(
            panel,
            feature_cols=["text_feature"],
            control="stock_mapping_permutation",
            random_state=7,
        )
        repeated = build_negative_control_features(
            panel,
            feature_cols=["text_feature"],
            control="stock_mapping_permutation",
            random_state=7,
        )
        self.assertEqual(permuted["text_feature"].tolist(), repeated["text_feature"].tolist())
        expected_targets = panel.sort_values(["signal_date", "ts_code"])["target_return"].tolist()
        self.assertEqual(permuted["target_return"].tolist(), expected_targets)
        shifted = build_negative_control_features(
            panel,
            feature_cols=["text_feature"],
            control="event_time_shift",
        )
        self.assertLess(shifted["signal_date"].nunique(), panel["signal_date"].nunique())


class TextAggregationTest(unittest.TestCase):
    def test_aggregation_uses_explicit_cutoff_and_keeps_missing_coverage_absent(self):
        raw = _raw_events().iloc[:3]
        prepared = prepare_text_events(raw, stock_registry=["000001.SZ"]).events
        labels = batch_label_events(raw.drop(columns="available_time"))
        rows = build_label_representation(prepared, labels)
        schedule = pd.DataFrame(
            {
                "signal_date": ["2022-01-03", "2022-01-04", "2022-01-04"],
                "signal_cutoff": ["2022-01-03 14:12:00", "2022-01-04 08:00:00", "2022-01-04 12:00:00"],
            }
        )
        with self.assertRaises(ValueError):
            aggregate_text_representation(rows, schedule, feature_cols=["sentiment_score", "confidence"])
        schedule = schedule.iloc[[0, 2]].copy()
        features = aggregate_text_representation(
            rows,
            schedule,
            feature_cols=["sentiment_score", "confidence"],
            lookback_days=5,
        )
        first = features[features["signal_date"].eq(pd.Timestamp("2022-01-03"))].iloc[0]
        self.assertEqual(int(first["text_event_count"]), 1)
        second = features[features["signal_date"].eq(pd.Timestamp("2022-01-04"))].iloc[0]
        self.assertEqual(int(second["text_event_count"]), 3)
        self.assertTrue((features["text_latest_available_time"] <= features["signal_cutoff"]).all())
        artifact = build_text_feature_artifact(
            features,
            representation_manifest_sha256="a" * 64,
            feature_cols=["sentiment_score", "confidence"],
            lookback_days=5,
            decay_half_life_days=None,
        )
        self.assertEqual(artifact["status"], "draft")
        self.assertIn("no implicit neutral fill", artifact["configuration"]["missingness_rule"])


if __name__ == "__main__":
    unittest.main()

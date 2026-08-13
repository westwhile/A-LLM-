"""Auditable, offline-first event labeling utilities."""

from ashare_factor_research.llm.audit import build_stratified_review_queue
from ashare_factor_research.llm.aggregation import (
    aggregate_text_representation,
    build_text_feature_artifact,
    write_text_feature_artifact,
)
from ashare_factor_research.llm.client import RuleBasedEventLabeler, batch_label_events
from ashare_factor_research.llm.embedding import (
    EmbeddingSpec,
    batch_embed_events,
    embedding_cache_key,
    embedding_spec_sha256,
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
    frozen_linear_spec_from_protocol,
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
from ashare_factor_research.llm.rule_baseline import (
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
from ashare_factor_research.llm.schema import validate_llm_event_labels
from ashare_factor_research.llm.text_manifest import (
    assess_text_manifest_research_readiness,
    assert_text_manifest_research_ready,
    build_text_dataset_manifest,
    text_manifest_sha256,
    validate_text_dataset_manifest,
)
from ashare_factor_research.llm.text_dataset import (
    prepare_text_events,
    select_signal_ready_events,
    write_text_preparation_artifacts,
)

__all__ = [
    "RULE_LEXICON_VERSION",
    "EmbeddingSpec",
    "FrozenLinearEvaluatorSpec",
    "RuleBasedEventLabeler",
    "RuleLexicon",
    "aggregate_text_representation",
    "assess_text_manifest_research_readiness",
    "assert_text_manifest_research_ready",
    "batch_embed_events",
    "batch_label_events",
    "build_label_representation",
    "build_negative_control_features",
    "build_rule_baseline_artifact",
    "build_stratified_review_queue",
    "build_text_dataset_manifest",
    "build_text_feature_artifact",
    "build_text_representation_artifact",
    "default_rule_lexicon",
    "embedding_cache_key",
    "embedding_spec_sha256",
    "evaluate_representation_increment",
    "evaluator_spec_sha256",
    "expand_embedding_features",
    "frozen_linear_spec_from_protocol",
    "lexicon_sha256",
    "load_r1_protocol",
    "prepare_text_events",
    "r1_protocol_sha256",
    "select_signal_ready_events",
    "text_manifest_sha256",
    "validate_llm_event_labels",
    "validate_rule_baseline_artifact",
    "validate_r1_protocol",
    "validate_text_dataset_manifest",
    "validate_text_representation_artifact",
    "write_r1_protocol_receipt",
    "write_r1_evaluation_artifacts",
    "write_rule_baseline_artifact",
    "write_text_preparation_artifacts",
    "write_text_feature_artifact",
    "write_text_representation_artifact",
]

"""Explicit, versioned rule lexicon for the R1-E1 transparent text baseline.

R1-E1（见 docs/plans/research_platform_v1/13_三大科研主线与AI工程分工.md）用
"规则/词典事件" 表示作为透明文本基准。透明基准的前提是规则本身可冻结、可 diff、
可哈希——因此词典从 RuleBasedEventLabeler 的硬编码中抽出为显式数据。

`default_rule_lexicon()` 与改造前 RuleBasedEventLabeler 的内置词表逐字一致，
保证既有标注行为（及缓存 key）完全不变。
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json


RULE_LEXICON_VERSION = "rule_lexicon_v1"


@dataclass(frozen=True)
class RuleLexicon:
    """Ordered keyword lexicon consumed by RuleBasedEventLabeler.

    Matching semantics (first match wins, evaluated by the labeler):
    1. growth_keywords  -> earnings_growth / positive / medium
    2. negative_keywords -> earnings_decline / negative / medium；
       若同时命中 litigation_keywords 则 event_type 改写为 litigation
    3. 兜底            -> other / neutral / unknown
    """

    version: str
    growth_keywords: tuple[str, ...]
    negative_keywords: tuple[str, ...]
    litigation_keywords: tuple[str, ...]


def default_rule_lexicon() -> RuleLexicon:
    """v1 词典：与 RuleBasedEventLabeler 历史硬编码词表逐字一致。"""
    return RuleLexicon(
        version=RULE_LEXICON_VERSION,
        growth_keywords=("增长", "预增", "中标", "突破", "growth", "win"),
        negative_keywords=("下滑", "亏损", "处罚", "诉讼", "decline", "loss", "fine"),
        litigation_keywords=("诉讼",),
    )


def lexicon_sha256(lexicon: RuleLexicon) -> str:
    """词典内容的稳定哈希，用于 artifact manifest 与缓存失效判断。"""
    payload = {
        "version": lexicon.version,
        "growth_keywords": list(lexicon.growth_keywords),
        "negative_keywords": list(lexicon.negative_keywords),
        "litigation_keywords": list(lexicon.litigation_keywords),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()

from __future__ import annotations

from pathlib import Path

import pandas as pd


REVIEW_COLUMNS = ["review_status", "error_type", "review_comment"]


def sample_labels_for_review(labels: pd.DataFrame, sample_size: int = 50, random_state: int = 42) -> pd.DataFrame:
    n = min(sample_size, len(labels))
    sample = labels.sample(n=n, random_state=random_state) if n else labels.copy()
    for col in REVIEW_COLUMNS:
        if col not in sample:
            sample[col] = "pending" if col == "review_status" else ""
    return sample.sort_values(["publish_date", "event_id"]).reset_index(drop=True)


def build_stratified_review_queue(
    labels: pd.DataFrame,
    sample_size: int = 100,
    random_state: int = 42,
) -> pd.DataFrame:
    """Build a deterministic gold-set candidate queue across key R1 strata.

    The queue is only a sampling aid.  ``review_status`` remains pending and
    final labels, disagreements and thresholds must be decided by humans.
    """

    if sample_size < 0:
        raise ValueError("sample_size must be non-negative")
    if labels.empty or sample_size == 0:
        empty = labels.head(0).copy()
        for column in (*REVIEW_COLUMNS, "sampling_stratum", "sample_rank"):
            if column not in empty:
                empty[column] = pd.Series(dtype="object")
        return empty
    work = labels.copy()
    publish = pd.to_datetime(work["publish_date"], errors="coerce")
    confidence = pd.to_numeric(work["confidence"], errors="coerce")
    work["_year"] = publish.dt.year.fillna(-1).astype(int).astype(str)
    work["_confidence_band"] = pd.cut(
        confidence,
        bins=[float("-inf"), 0.5, 0.8, float("inf")],
        labels=["low", "medium", "high"],
    ).astype("string").fillna("unknown")
    work["sampling_stratum"] = (
        work["_year"]
        + "|"
        + work["event_type"].fillna("unknown").astype(str)
        + "|"
        + work["sentiment"].fillna("unknown").astype(str)
        + "|"
        + work["_confidence_band"].astype(str)
    )
    groups = {
        str(name): group.sample(frac=1.0, random_state=random_state).reset_index(drop=True)
        for name, group in work.groupby("sampling_stratum", sort=True)
    }
    selected: list[pd.Series] = []
    position = 0
    limit = min(sample_size, len(work))
    while len(selected) < limit:
        added = False
        for name in sorted(groups):
            group = groups[name]
            if position < len(group):
                selected.append(group.iloc[position])
                added = True
                if len(selected) == limit:
                    break
        if not added:
            break
        position += 1
    queue = pd.DataFrame(selected).drop(columns=["_year", "_confidence_band"], errors="ignore")
    queue["sample_rank"] = range(1, len(queue) + 1)
    for column in REVIEW_COLUMNS:
        queue[column] = "pending" if column == "review_status" else ""
    return queue.sort_values("sample_rank").reset_index(drop=True)


def label_quality_passes(review: pd.DataFrame, threshold: float = 0.8) -> bool:
    if review.empty or "review_status" not in review:
        return False
    completed = review[review["review_status"].isin(["pass", "fail"])]
    return bool(len(completed) and completed["review_status"].eq("pass").mean() >= threshold)


def write_llm_event_audit_report(review: pd.DataFrame, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    completed = review[review["review_status"].isin(["pass", "fail"])] if "review_status" in review else pd.DataFrame()
    ratio = float(completed["review_status"].eq("pass").mean()) if not completed.empty else None
    lines = [
        "# LLM Event Label Audit", "", f"- sample_size: {len(review)}",
        f"- reviewed_count: {len(completed)}", f"- pass_ratio: {ratio:.4f}" if ratio is not None else "- pass_ratio: not_reviewed",
        "- role: auxiliary explanation and weak-signal research only; not trading instructions.", "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path

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


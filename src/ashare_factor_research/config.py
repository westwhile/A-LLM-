from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ashare_factor_research.backtest.cost_model import CostConfig
from ashare_factor_research.utils.io import load_yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROJECT_CONFIG = PROJECT_ROOT / "config" / "project_config.yaml"
DEFAULT_FACTOR_CONFIG = PROJECT_ROOT / "config" / "factor_config.yaml"
DEFAULT_BACKTEST_CONFIG = PROJECT_ROOT / "config" / "backtest_config.yaml"


@dataclass(frozen=True)
class ConfigBundle:
    project: dict[str, Any]
    factor: dict[str, Any]
    backtest: dict[str, Any]
    paths: dict[str, Path]

    @property
    def horizon(self) -> int:
        return int(self.project.get("research", {}).get("default_horizon", 20))

    @property
    def top_n(self) -> int:
        return int(self.backtest.get("portfolio", {}).get("top_n", 50))

    @property
    def max_weight(self) -> float:
        return float(self.backtest.get("portfolio", {}).get("max_weight", 0.05))

    @property
    def cost(self) -> CostConfig:
        values = self.backtest.get("cost", {})
        allowed = CostConfig.__dataclass_fields__
        return CostConfig(**{key: float(value) for key, value in values.items() if key in allowed})


def load_config_bundle(
    project_config: str | Path | None = None,
    factor_config: str | Path | None = None,
    backtest_config: str | Path | None = None,
) -> ConfigBundle:
    paths = {
        "project": Path(project_config or DEFAULT_PROJECT_CONFIG).resolve(),
        "factor": Path(factor_config or DEFAULT_FACTOR_CONFIG).resolve(),
        "backtest": Path(backtest_config or DEFAULT_BACKTEST_CONFIG).resolve(),
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Configuration files not found: {missing}")
    return ConfigBundle(
        project=load_yaml(paths["project"]),
        factor=load_yaml(paths["factor"]),
        backtest=load_yaml(paths["backtest"]),
        paths=paths,
    )


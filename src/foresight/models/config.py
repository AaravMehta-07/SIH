"""Configuration loading and validation for the FORESIGHT core.

The only default reference profile is ``configs/core.yaml`` (Build Spec Section 35,
reproduced verbatim). This module loads it strictly: the schema id must match, every
section must carry exactly the Section 35 key set, and YAML duplicate keys are
rejected (Build Spec T.1: "Reject duplicate keys, unknown fields and incompatible
overrides").

Cross-field consistency of the frozen dimensions (88/22/48 inputs; 152/192/256
downstream widths) is enforced here so an incompatible configuration cannot reach
model construction (Appendix T.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from foresight import SCHEMA_ID

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "core.yaml"

_EXPECTED_KEYS: dict[str, set[str]] = {
    "system": {"name", "offline", "action_mode"},
    "data": {
        "window_seconds",
        "history_windows",
        "modeled_horizon_bins",
        "evaluated_horizon_bins",
        "primary_horizon_bins",
        "max_nodes_per_graph",
        "split_unit",
        "split_proportions",
        "embargo_seconds",
        "retain_precursor_attack_history",
    },
    "features": {
        "node_values",
        "node_validity",
        "node_input",
        "edge_values",
        "edge_validity",
        "edge_input",
        "global_values",
        "global_validity",
        "global_input",
        "global_adapter_output",
    },
    "model": {
        "entity_embedding",
        "entity_gru_hidden",
        "global_lstm_input",
        "global_lstm_hidden",
        "global_lstm_layers",
        "endpoint_head_input",
        "edge_head_input",
        "latent_noise",
    },
    "training": {
        "epochs_max",
        "batch_clips",
        "optimizer",
        "learning_rate",
        "weight_decay",
        "gradient_clip",
        "rollout_curriculum",
        "loss",
        "seeds",
        "benign_pretraining",
    },
    "evaluation": {
        "alert_cooldown_seconds",
        "false_alerts_per_100_asset_hours_max",
        "primary_event_recall_min",
        "ece_max",
        "compute_to_ledger_p95_seconds_max",
        "compute_to_ledger_p99_seconds_max",
        "process_memory_gib_max",
        "final_test_model_selection",
    },
    "release": {
        "measured_results_required",
        "supported_tasks_from_manifest",
        "auto_promote_research",
    },
}


class ConfigError(ValueError):
    """Raised for invalid, incomplete or inconsistent configuration."""


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys."""


def _construct_mapping(loader: yaml.Loader, node: yaml.Node, deep: bool = False) -> dict:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConfigError(f"duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


@dataclass(frozen=True)
class FeatureDimensions:
    """Feature registry dimensions (Build Spec Section 10)."""

    node_values: int
    node_validity: int
    node_input: int
    edge_values: int
    edge_validity: int
    edge_input: int
    global_values: int
    global_validity: int
    global_input: int
    global_adapter_output: int

    def validate(self) -> None:
        if self.node_input != self.node_values + self.node_validity:
            raise ConfigError(
                f"node_input must equal node_values + node_validity, got "
                f"{self.node_input} != {self.node_values} + {self.node_validity}"
            )
        if self.edge_input != self.edge_values + self.edge_validity:
            raise ConfigError(
                f"edge_input must equal edge_values + edge_validity, got "
                f"{self.edge_input} != {self.edge_values} + {self.edge_validity}"
            )
        if self.global_input != self.global_values + self.global_validity:
            raise ConfigError(
                f"global_input must equal global_values + global_validity, got "
                f"{self.global_input} != {self.global_values} + {self.global_validity}"
            )


@dataclass(frozen=True)
class ModelDimensions:
    """Model dimensions (Build Spec Section 35, model block).

    The fields with defaults are implementation defaults recorded in ADR-001
    (Build Spec T.1 requires an explicit record for the normalization class and
    epsilon; attention dropout is fixed by Section 13).
    """

    entity_embedding: int
    entity_gru_hidden: int
    global_lstm_input: int
    global_lstm_hidden: int
    global_lstm_layers: int
    endpoint_head_input: int
    edge_head_input: int
    latent_noise: str
    attention_dropout: float = 0.1
    graph_norm_class: str = "GraphNorm"
    graph_norm_eps: float = 1e-5
    num_tactic_tags: int = 5
    log_scale_min: float = -5.0
    log_scale_max: float = 3.0

    def validate(self, features: FeatureDimensions) -> None:
        if self.latent_noise != "disabled":
            raise ConfigError(
                "latent_noise must be 'disabled' (Build Spec Section 35; no arbitrary "
                "rollout noise may be called uncertainty, Appendix A10)"
            )
        if self.entity_gru_hidden != self.entity_embedding:
            raise ConfigError(
                f"entity_gru_hidden must equal entity_embedding (H.1: GRUCell with "
                f"input 64 and hidden 64), got {self.entity_gru_hidden} != "
                f"{self.entity_embedding}"
            )
        if self.endpoint_head_input != self.entity_embedding + self.global_lstm_hidden:
            raise ConfigError(
                f"endpoint_head_input must equal entity_embedding + global_lstm_hidden "
                f"(H.2: [entity_memory || global_h_top]), got "
                f"{self.endpoint_head_input} != {self.entity_embedding} + "
                f"{self.global_lstm_hidden}"
            )
        if self.edge_head_input != (
            2 * self.entity_embedding + self.global_lstm_hidden
        ):
            raise ConfigError(
                f"edge_head_input must equal 2*entity_embedding + global_lstm_hidden "
                f"(H.2: [source_memory || target_memory || global_h_top]), got "
                f"{self.edge_head_input} != 2*{self.entity_embedding} + "
                f"{self.global_lstm_hidden}"
            )
        pooled_width = 2 * self.entity_embedding
        if self.global_lstm_input != pooled_width + features.global_adapter_output:
            raise ConfigError(
                f"global_lstm_input must equal 2*entity_embedding (masked mean+max "
                f"pooling) + global_adapter_output, got {self.global_lstm_input} != "
                f"{pooled_width} + {features.global_adapter_output}"
            )
        if self.graph_norm_class != "GraphNorm":
            raise ConfigError(
                f"graph_norm_class {self.graph_norm_class!r} is not a recorded "
                f"implementation default (ADR-001)"
            )


@dataclass(frozen=True)
class CoreConfig:
    """Validated view of ``configs/core.yaml``."""

    schema: str
    system: dict[str, Any]
    data: dict[str, Any]
    features: FeatureDimensions
    model: ModelDimensions
    training: dict[str, Any]
    evaluation: dict[str, Any]
    release: dict[str, Any]

    @property
    def window_seconds(self) -> int:
        return int(self.data["window_seconds"])

    @property
    def history_windows(self) -> int:
        return int(self.data["history_windows"])

    @property
    def modeled_horizon_bins(self) -> int:
        return int(self.data["modeled_horizon_bins"])


def load_core_config(path: str | Path = DEFAULT_CONFIG_PATH) -> CoreConfig:
    """Load and strictly validate a core configuration file."""
    path = Path(path)
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictLoader)
    except ConfigError:
        raise
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping")

    if raw.get("schema") != SCHEMA_ID:
        raise ConfigError(
            f"schema must be {SCHEMA_ID!r}, got {raw.get('schema')!r}"
        )

    for section, expected in _EXPECTED_KEYS.items():
        if section not in raw:
            raise ConfigError(f"missing config section: {section!r}")
        if not isinstance(raw[section], dict):
            raise ConfigError(f"config section {section!r} must be a mapping")
        actual = set(raw[section])
        unknown = actual - expected
        missing = expected - actual
        if unknown:
            raise ConfigError(f"unknown keys in section {section!r}: {sorted(unknown)}")
        if missing:
            raise ConfigError(f"missing keys in section {section!r}: {sorted(missing)}")

    features = FeatureDimensions(**raw["features"])
    features.validate()
    model = ModelDimensions(**raw["model"])
    model.validate(features)

    return CoreConfig(
        schema=raw["schema"],
        system=raw["system"],
        data=raw["data"],
        features=features,
        model=model,
        training=raw["training"],
        evaluation=raw["evaluation"],
        release=raw["release"],
    )

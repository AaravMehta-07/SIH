"""Config layer tests: Section 35 exact values and validation rules."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from foresight.models.config import (
    ConfigError,
    CoreConfig,
    FeatureDimensions,
    ModelDimensions,
    load_core_config,
)

from conftest import REPO_ROOT

CONFIG_PATH = REPO_ROOT / "configs" / "core.yaml"

EXPECTED = {
    "schema": "foresight.core.2026-09",
    "system": {"name": "FORESIGHT", "offline": True, "action_mode": "disabled"},
    "data": {
        "window_seconds": 30,
        "history_windows": 20,
        "modeled_horizon_bins": 60,
        "evaluated_horizon_bins": [10, 30, 60],
        "primary_horizon_bins": 10,
        "max_nodes_per_graph": 128,
        "split_unit": "campaign_episode",
        "split_proportions": [0.60, 0.15, 0.10, 0.15],
        "embargo_seconds": 2400,
        "retain_precursor_attack_history": True,
    },
    "features": {
        "node_values": 44,
        "node_validity": 44,
        "node_input": 88,
        "edge_values": 11,
        "edge_validity": 11,
        "edge_input": 22,
        "global_values": 24,
        "global_validity": 24,
        "global_input": 48,
        "global_adapter_output": 24,
    },
    "model": {
        "entity_embedding": 64,
        "entity_gru_hidden": 64,
        "global_lstm_input": 152,
        "global_lstm_hidden": 128,
        "global_lstm_layers": 2,
        "endpoint_head_input": 192,
        "edge_head_input": 256,
        "latent_noise": "disabled",
    },
    "training": {
        "epochs_max": 40,
        "batch_clips": 16,
        "optimizer": "AdamW",
        "learning_rate": 0.001,
        "weight_decay": 0.0001,
        "gradient_clip": 1.0,
        "rollout_curriculum": [1, 3, 10, 30, 60],
        "loss": {"survival": 1.0, "observable": 0.5, "edge": 0.2, "stage": 0.2},
        "seeds": [0, 1, 2, 3, 4],
        "benign_pretraining": "challenger_only",
    },
    "evaluation": {
        "alert_cooldown_seconds": 300,
        "false_alerts_per_100_asset_hours_max": 1.0,
        "primary_event_recall_min": 0.50,
        "ece_max": 0.05,
        "compute_to_ledger_p95_seconds_max": 2.0,
        "compute_to_ledger_p99_seconds_max": 5.0,
        "process_memory_gib_max": 8,
        "final_test_model_selection": "prohibited",
    },
    "release": {
        "measured_results_required": True,
        "supported_tasks_from_manifest": True,
        "auto_promote_research": False,
    },
}


def write_config(data: dict, path: Path) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


class TestSection35Exact:
    def test_yaml_matches_section_35_verbatim(self):
        raw = yaml.load(CONFIG_PATH.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
        assert raw == EXPECTED

    def test_load_core_config_values(self, core_config: CoreConfig):
        assert core_config.schema == "foresight.core.2026-09"
        assert core_config.system == EXPECTED["system"]
        assert core_config.data == EXPECTED["data"]
        assert core_config.features.node_input == 88
        assert core_config.features.edge_input == 22
        assert core_config.features.global_input == 48
        assert core_config.model.entity_embedding == 64
        assert core_config.model.global_lstm_hidden == 128
        assert core_config.model.global_lstm_layers == 2
        assert core_config.model.endpoint_head_input == 192
        assert core_config.model.edge_head_input == 256
        assert core_config.model.latent_noise == "disabled"

    def test_derived_properties(self, core_config: CoreConfig):
        d = core_config.data
        assert d["window_seconds"] == 30
        assert d["history_windows"] == 20
        assert d["modeled_horizon_bins"] == 60
        assert d["primary_horizon_bins"] == 10
        assert d["embargo_seconds"] == 2400
        assert d["max_nodes_per_graph"] == 128
        assert core_config.window_seconds == 30
        assert core_config.history_windows == 20
        assert core_config.modeled_horizon_bins == 60


class TestValidation:
    def test_wrong_schema_rejected(self, tmp_path):
        data = yaml.load(CONFIG_PATH.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
        data["schema"] = "foresight.core.2025-01"
        with pytest.raises(ConfigError, match="schema"):
            load_core_config(write_config(data, tmp_path / "bad.yaml"))

    def test_unknown_key_rejected(self, tmp_path):
        data = yaml.load(CONFIG_PATH.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
        data["model"]["extra_layer"] = 3
        with pytest.raises(ConfigError, match="unknown keys"):
            load_core_config(write_config(data, tmp_path / "bad.yaml"))

    def test_missing_key_rejected(self, tmp_path):
        data = yaml.load(CONFIG_PATH.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
        del data["features"]["node_input"]
        with pytest.raises(ConfigError, match="missing keys"):
            load_core_config(write_config(data, tmp_path / "bad.yaml"))

    def test_duplicate_yaml_key_rejected(self, tmp_path):
        text = CONFIG_PATH.read_text(encoding="utf-8")
        text = text.replace("schema: foresight.core.2026-09\n", "schema: a\nschema: b\n", 1)
        (tmp_path / "dup.yaml").write_text(text, encoding="utf-8")
        with pytest.raises(ConfigError, match="[Dd]uplicate"):
            load_core_config(tmp_path / "dup.yaml")

    def test_inconsistent_feature_dims_rejected(self, tmp_path):
        data = yaml.load(CONFIG_PATH.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
        data["features"]["node_input"] = 90  # != 44 + 44
        with pytest.raises(ConfigError, match="node_input"):
            load_core_config(write_config(data, tmp_path / "bad.yaml"))

    def test_inconsistent_model_dims_rejected(self, tmp_path):
        data = yaml.load(CONFIG_PATH.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
        data["model"]["endpoint_head_input"] = 128  # != 64 + 128
        with pytest.raises(ConfigError, match="endpoint_head_input"):
            load_core_config(write_config(data, tmp_path / "bad.yaml"))

    def test_latent_noise_must_be_disabled(self, tmp_path):
        data = yaml.load(CONFIG_PATH.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
        data["model"]["latent_noise"] = "gaussian"
        with pytest.raises(ConfigError, match="latent_noise"):
            load_core_config(write_config(data, tmp_path / "bad.yaml"))

    def test_direct_dim_validation(self):
        features = FeatureDimensions(
            node_values=44,
            node_validity=44,
            node_input=88,
            edge_values=11,
            edge_validity=11,
            edge_input=22,
            global_values=24,
            global_validity=24,
            global_input=48,
            global_adapter_output=24,
        )
        ModelDimensions(
            entity_embedding=64,
            entity_gru_hidden=64,
            global_lstm_input=152,
            global_lstm_hidden=128,
            global_lstm_layers=2,
            endpoint_head_input=192,
            edge_head_input=256,
            latent_noise="disabled",
        ).validate(features)

import json
import os
from typing import Dict, List
from pydantic import BaseModel, Field

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")

DEFAULT_THRESHOLDS: Dict[str, List[float]] = {
    "rssi_dbm":        [-70.0, -85.0, -100.0],
    "sinr_eff_db":     [20.0,  10.0,  0.0],
    "throughput_kbps": [1000.0, 500.0, 100.0],
    "bler":            [0.05, 0.15, 0.3],
}

DEFAULTS = {
    "center_lat": 35.6046,
    "center_lon": 139.6844,
    "origin_x": 0.0,
    "origin_y": 0.0,
    "watch_path": "simulation_dataset.csv",
    "watch_interval_ms": 500,
    "playback_speed": 1.0,
    "link_direction": "both",
}


class AppSettings(BaseModel):
    center_lat: float = 35.6046
    center_lon: float = 139.6844
    origin_x: float = 0.0
    origin_y: float = 0.0
    watch_path: str = "simulation_dataset.csv"
    watch_interval_ms: int = 500
    playback_speed: float = 1.0
    link_direction: str = "both"  # both | tx_only | rx_only | worst | best
    thresholds: Dict[str, List[float]] = Field(
        default_factory=lambda: {k: list(v) for k, v in DEFAULT_THRESHOLDS.items()}
    )


def load_settings() -> AppSettings:
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH) as f:
            data = json.load(f)
        return AppSettings(**{**DEFAULTS, **data})
    settings = AppSettings()
    save_settings(settings)
    return settings


def save_settings(settings: AppSettings) -> None:
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings.model_dump(), f, indent=2)

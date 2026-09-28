"""Config loading: config.yaml (detection constants) + .env (deployment settings).

SPEC.md section 2 calls for "config.yaml + .env (pydantic-settings)". The
split is: config.yaml holds the numeric constants every detection stage
uses (criticality, baseline/anomaly/severity/hipaa/incident/window), and is
plain data (loaded once, cached); .env holds environment-specific settings
(AWS mode, paths) via pydantic-settings so they can be overridden without
editing files.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/app -> backend -> repo root
# HEALTHTRACE_ROOT lets an installed copy of the package (e.g. in the Docker
# image) find config.yaml, data/ and the built frontend.
REPO_ROOT = Path(os.environ.get("HEALTHTRACE_ROOT") or Path(__file__).resolve().parents[2])
CONFIG_YAML_PATH = REPO_ROOT / "config.yaml"


class ServiceConfig(BaseModel):
    criticality: float
    label: Optional[str] = None
    depends_on: list[str] = []


class BaselineConfig(BaseModel):
    alpha: float
    warmup_windows: int


class AnomalyConfig(BaseModel):
    min_std: float
    error_rate_z_threshold: float
    error_rate_min_errors: int
    error_rate_min_rate: float
    latency_z_threshold: float
    latency_min_std_ms: float


class SeverityThresholds(BaseModel):
    low_max: float
    medium_max: float
    high_max: float


class SeverityConfig(BaseModel):
    deviation_z_cap: float
    patient_factor_cap: float
    criticality_weight: float
    patient_factor_weight: float
    thresholds: SeverityThresholds


class HipaaConfig(BaseModel):
    bulk_multiplier_high: float
    bulk_multiplier_critical: float
    bulk_min_threshold: float
    export_min_threshold: float
    export_critical_records: int
    off_hours_start: str
    off_hours_end: str
    off_hours_high_records: int
    region_mismatch_medium_max: int
    # IANA zone that business hours are judged in. UTC keeps the historical
    # behaviour for callers that don't set it; config.yaml sets the real one.
    timezone: str = "UTC"
    # Minimum event-time gap before re-alerting an unchanged HIPAA pattern for
    # the same user (an escalation in severity always alerts immediately).
    realert_seconds: float = 60


class IncidentConfig(BaseModel):
    cooldown_minutes: float
    service_auto_resolve_windows: int
    hipaa_auto_resolve_minutes: float


class WindowConfig(BaseModel):
    size_seconds: float
    step_seconds: float


class AppConfig(BaseModel):
    services: dict[str, ServiceConfig]
    priority_weight: dict[str, int]
    baseline: BaselineConfig
    anomaly: AnomalyConfig
    severity: SeverityConfig
    hipaa: HipaaConfig
    incident: IncidentConfig
    window: WindowConfig


@lru_cache
def load_config(path: Path = CONFIG_YAML_PATH) -> AppConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(data)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    aws_mode: Literal["off", "mock", "live"] = "off"
    aws_region: str = "us-east-1"
    cloudwatch_log_group: str = "/medguard/alerts"
    sns_topic_arn: str = ""
    demo_mode: bool = True

    # Deployment identity shown in the UI (single project/environment today).
    project_name: str = "Medicaid Pipeline"
    environment: str = "local"
    # Comma-separated browser origins allowed to call the API cross-origin.
    # Not needed when the built frontend is served by this app (same origin).
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # When set, state-changing endpoints (ack/resolve/demo/AWS test) require
    # header X-Operator-Token with this value. Read endpoints stay open;
    # put real sign-in (e.g. ALB + Cognito) in front for production.
    operator_token: str = ""
    # Built frontend to serve at "/", if present.
    static_dir: Path = REPO_ROOT / "frontend" / "dist"

    # Absolute by default so behavior doesn't depend on the process's cwd;
    # .env overrides these with its own (also ideally absolute) paths.
    log_dir: Path = REPO_ROOT / "data" / "logs"
    db_path: Path = REPO_ROOT / "data" / "medguard.db"
    control_file: Path = REPO_ROOT / "data" / "control.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()

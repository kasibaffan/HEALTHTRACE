"""Severity scoring (SPEC.md section 6.6).

Two formulas live here because the spec describes them as one component
("the severity engine"): a continuous score for service anomalies
(deviation x criticality/patient-impact), and a rule-based table for HIPAA
access anomalies (Milestone 4's access detector calls the latter). Both are
pure functions of their inputs and config.yaml's weights/thresholds.
"""

from __future__ import annotations

from app.config import HipaaConfig, SeverityConfig, SeverityThresholds
from app.models import Alert, Anomaly, Severity, WindowMetrics


def score_to_severity(score: float, thresholds: SeverityThresholds) -> Severity:
    if score < thresholds.low_max:
        return "LOW"
    if score < thresholds.medium_max:
        return "MEDIUM"
    if score < thresholds.high_max:
        return "HIGH"
    return "CRITICAL"


def score_service_anomaly(
    anomaly: Anomaly, metrics: WindowMetrics, criticality: float, config: SeverityConfig
) -> Alert:
    """deviation x (0.5 x criticality + 0.5 x patient_factor), per SPEC.md 6.6."""
    deviation = min(anomaly.z / config.deviation_z_cap, 1.0)
    patient_factor = min(
        (2 * metrics.affected_patients_urgent + metrics.affected_patients_routine) / config.patient_factor_cap,
        1.0,
    )
    score = deviation * (config.criticality_weight * criticality + config.patient_factor_weight * patient_factor)
    severity = score_to_severity(score, config.thresholds)

    explanation = _explain_service_anomaly(anomaly, metrics)

    return Alert(
        ts=anomaly.ts,
        kind=anomaly.kind,
        service=anomaly.service,
        severity=severity,
        score=score,
        explanation=explanation,
        metrics=metrics.model_dump(mode="json"),
    )


def _explain_service_anomaly(anomaly: Anomaly, metrics: WindowMetrics) -> str:
    baseline_mean = anomaly.baseline_mean or 0.0
    if anomaly.kind == "error_rate":
        metric_name = "error rate"
        current = f"{metrics.error_rate * 100:.0f}%"
        baseline = f"{baseline_mean * 100:.0f}%"
    else:
        metric_name = "p95 latency"
        current = f"{metrics.p95_latency_ms:.0f}ms"
        baseline = f"{baseline_mean:.0f}ms"

    if metrics.affected_patients_urgent:
        patients_clause = f"; {metrics.affected_patients_urgent} urgent patients affected"
    elif metrics.affected_patients_routine:
        patients_clause = f"; {metrics.affected_patients_routine} patients affected"
    else:
        patients_clause = ""

    return f"{anomaly.service} {metric_name} {current} vs baseline {baseline} (z={anomaly.z:.1f}){patients_clause}"


def score_hipaa_anomaly(anomaly: Anomaly, config: HipaaConfig) -> Alert:
    """Rule-based severity table (SPEC.md 6.6). ``anomaly.metrics`` carries
    whatever numbers each pattern needs (set by the access detector,
    Milestone 4): "multiplier" and "distinct_patients" for bulk access,
    "records" for exports/off-hours, "distinct_patients" for region mismatch.
    """
    kind = anomaly.kind
    m = anomaly.metrics

    if kind == "hipaa_bulk_access":
        multiplier = m.get("multiplier", 0.0)
        count = m.get("distinct_patients", 0)
        severity: Severity = "CRITICAL" if multiplier > config.bulk_multiplier_critical else "HIGH"
        explanation = f"user {anomaly.user_id} accessed {count} patients ({multiplier:.1f}x their baseline)"
    elif kind == "hipaa_bulk_export":
        count = m.get("records", 0)
        severity = "CRITICAL" if count > config.export_critical_records else "MEDIUM"
        explanation = f"user {anomaly.user_id} exported {count} patient records"
    elif kind == "hipaa_off_hours":
        count = m.get("records", 0)
        severity = "HIGH" if count > config.off_hours_high_records else "MEDIUM"
        explanation = (
            f"user {anomaly.user_id} accessed {count} records "
            f"outside {config.off_hours_start}-{config.off_hours_end}"
        )
    elif kind == "hipaa_region_mismatch":
        count = m.get("distinct_patients", 0)
        severity = "HIGH" if count > config.region_mismatch_medium_max else "MEDIUM"
        explanation = f"user {anomaly.user_id} accessed {count} patients outside their region"
    else:
        raise ValueError(f"not a HIPAA anomaly kind: {kind}")

    return Alert(
        ts=anomaly.ts,
        kind=kind,
        user_id=anomaly.user_id,
        severity=severity,
        score=0.0,  # rule-based, not a continuous score
        explanation=explanation,
        metrics=m,
    )

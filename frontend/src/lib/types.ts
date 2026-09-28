/** Wire types for the HEALTH TRACE backend (backend/app/api, backend/app/models.py). */

export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type IncidentState = "OPEN" | "ACKNOWLEDGED" | "RESOLVED";
export type AnomalyKind =
  | "error_rate"
  | "latency_degradation"
  | "hipaa_bulk_access"
  | "hipaa_off_hours"
  | "hipaa_region_mismatch"
  | "hipaa_bulk_export";

export interface WindowMetrics {
  service: string;
  window_end: string;
  total: number;
  errors: number;
  error_rate: number;
  p95_latency_ms: number;
  urgent_errors: number;
  affected_patients_urgent: number;
  affected_patients_routine: number;
  malformed_lines: number;
  /** The error-rate baseline this window was judged against (null while learning). */
  baseline_mean?: number | null;
  baseline_std?: number | null;
}

export interface ServiceState {
  service: string;
  window_end: string | null;
  total: number;
  errors: number;
  error_rate: number;
  p95_latency_ms: number;
  urgent_errors: number;
  baseline_mean: number | null;
  baseline_std: number | null;
  z: number | null;
  latency_baseline_mean: number | null;
  baseline_is_fallback: boolean;
  affected_patients_urgent: number;
  affected_patients_routine: number;
}

export interface ServiceRow extends ServiceState {
  criticality: number | null;
  label: string;
  depends_on: string[];
  active_incidents: number;
  worst_severity: Severity | null;
  baseline_ready: boolean;
  requests_per_second: number;
}

export interface Alert {
  id: number | null;
  ts: string;
  kind: AnomalyKind;
  service: string | null;
  user_id: string | null;
  severity: Severity;
  score: number;
  explanation: string;
  metrics: Record<string, number | string | null>;
  incident_id: number | null;
}

export interface Incident {
  id: number;
  fingerprint: string;
  kind: AnomalyKind;
  service: string | null;
  user_id: string | null;
  state: IncidentState;
  peak_severity: Severity;
  alert_count: number;
  opened_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  mttr_seconds: number | null;
  muted_until: string | null;
}

export type IncidentEventType =
  | "opened"
  | "alert_attached"
  | "escalated"
  | "acknowledged"
  | "resolved"
  | "auto_resolved"
  | "muted";

export interface IncidentEvent {
  id: number | null;
  incident_id: number;
  ts: string;
  event_type: IncidentEventType;
  severity: Severity | null;
  detail: string | null;
}

export interface AppLogRecord {
  seq: number;
  ts: string;
  type: "app";
  service: string;
  level: "INFO" | "WARN" | "ERROR";
  priority: "urgent" | "routine";
  request_id: string;
  patient_id: string | null;
  status: number;
  latency_ms: number;
  msg: string;
  is_error: boolean;
}

export interface AuditLogRecord {
  seq: number;
  ts: string;
  type: "audit";
  user_id: string;
  role: string;
  action: string;
  patient_id: string;
  patient_region: string;
  user_region: string;
  region_mismatch: boolean;
  level: "INFO" | "WARN";
  msg: string;
}

export type LogRecord = AppLogRecord | AuditLogRecord;

export interface ThroughputSample {
  ts: string;
  app_eps: number;
  audit_eps: number;
}

export interface ReplayStatus {
  active: boolean;
  progress: number;
  event_clock: string | null;
  events_processed: number;
}

export interface Health {
  status: "ok" | "replaying";
  queue_depth: number;
  malformed_lines: number;
  aws_mode: "off" | "mock" | "live";
  notifier_queue_depth: number;
  demo_mode: boolean;
  started_at: string | null;
  uptime_seconds: number;
  event_clock: string | null;
  event_lag_seconds: number | null;
  events_processed: { app: number; audit: number };
  alerts_emitted: number;
  ws_clients: number;
  throughput: ThroughputSample | { app_eps: number; audit_eps: number };
  throughput_history: ThroughputSample[];
  replay: ReplayStatus;
  tailers: { path: string; offset: number; size: number; caught_up: boolean }[];
}

export interface Snapshot {
  type: "snapshot";
  services: ServiceRow[];
  alerts: Alert[];
  incidents: Incident[];
  metrics: Record<string, ServiceState>;
  health: Health;
  logs: LogRecord[];
}

export type LiveMessage =
  | Snapshot
  | ({ type: "metric" } & ServiceState & WindowMetrics)
  | ({ type: "alert" } & Alert)
  | ({ type: "incident_update"; incident: Incident } & IncidentEvent)
  | { type: "logs"; events: LogRecord[]; dropped: number }
  | ({ type: "replay" } & ReplayStatus)
  | { type: "heartbeat"; ts: string };

export interface IncidentDetail {
  incident: Incident;
  events: IncidentEvent[];
  alerts: Alert[];
  detection: DetectionRule;
}

export interface DetectionRule {
  metric: string;
  z_threshold?: number;
  min_errors?: number;
  min_rate?: number;
  min_std?: number;
  window_seconds?: number;
  step_seconds?: number;
  rolling_window_minutes?: number;
  severity?: SeverityConfig;
  hipaa?: HipaaConfig;
}

export interface SeverityConfig {
  deviation_z_cap: number;
  patient_factor_cap: number;
  criticality_weight: number;
  patient_factor_weight: number;
  thresholds: { low_max: number; medium_max: number; high_max: number };
}

export interface HipaaConfig {
  bulk_multiplier_high: number;
  bulk_multiplier_critical: number;
  bulk_min_threshold: number;
  export_min_threshold: number;
  export_critical_records: number;
  off_hours_start: string;
  off_hours_end: string;
  off_hours_high_records: number;
  region_mismatch_medium_max: number;
  timezone: string;
  realert_seconds: number;
}

export interface BaselineCell {
  hour_of_day: number;
  mean: number;
  std: number;
  count: number;
  ready: boolean;
}

export interface ServiceDetail extends ServiceRow {
  baselines: { error_rate: BaselineCell[]; p95_latency_ms: BaselineCell[] };
  incidents: Incident[];
  alerts: Alert[];
}

export interface LogSearchResult {
  events: LogRecord[];
  buffer_size: number;
  buffer_capacity: number;
}

export interface LogContext {
  event: LogRecord;
  before: LogRecord[];
  after: LogRecord[];
  related_alerts: Alert[];
}

export interface HipaaUser {
  user_id: string;
  distinct_patients: number;
  events: number;
  exports: number;
  off_hours_events: number;
  region_mismatch_patients: number;
  baseline: number | null;
  bulk_threshold: number;
  last_seen: string;
}

type SeverityCounts = Record<Severity, number>;

export interface Analytics {
  hours: number;
  since: string;
  alerts_per_hour: ({ hour: string } & SeverityCounts)[];
  alerts_by_service: Record<string, SeverityCounts>;
  alerts_by_kind: Record<string, number>;
  volume_per_hour: {
    hour: string;
    events: number;
    errors: number;
    error_rate: number;
    services: Record<string, { events: number; errors: number; error_rate: number; p95_latency_ms: number }>;
  }[];
  incidents: { total: number; active: number; resolved: number; by_severity: SeverityCounts };
  mttr_seconds: Record<string, { mean: number; count: number; max: number }>;
  recurring: { fingerprint: string; count: number }[];
  detection_lag_seconds: number | null;
}

export interface AppConfigResponse {
  detection: {
    services: Record<string, { criticality: number; label: string | null; depends_on: string[] }>;
    priority_weight: Record<string, number>;
    baseline: { alpha: number; warmup_windows: number };
    anomaly: {
      min_std: number;
      error_rate_z_threshold: number;
      error_rate_min_errors: number;
      error_rate_min_rate: number;
      latency_z_threshold: number;
      latency_min_std_ms: number;
    };
    severity: SeverityConfig;
    hipaa: HipaaConfig;
    incident: { cooldown_minutes: number; service_auto_resolve_windows: number; hipaa_auto_resolve_minutes: number };
    window: { size_seconds: number; step_seconds: number };
  };
  deployment: {
    project_name: string;
    environment: string;
    demo_mode: boolean;
    aws_mode: "off" | "mock" | "live";
    log_sources: { name: string; path: string; size_bytes: number; offset: number }[];
    operator_token_required: boolean;
  };
}

export interface ChannelStatus {
  sent: number;
  failed: number;
  skipped: number;
  retries: number;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_error: string | null;
  recent: { ts: string; outcome: "sent" | "failed" | "skipped"; subject: string; error: string | null }[];
}

export interface AwsStatus {
  mode: "off" | "mock" | "live";
  region: string;
  cloudwatch: { log_group: string } & ChannelStatus;
  sns: { topic_arn: string | null; configured: boolean } & ChannelStatus;
  queue_depth: number;
  credentials_source: string | null;
}

export interface AwsCheckResult {
  mode: string;
  cloudwatch: { ok: boolean; detail: string };
  sns: { ok: boolean; detail: string };
}

export interface DemoScenario {
  name: string;
  label: string;
  target: string | null;
  family: "service" | "hipaa" | "recovery";
  effect: string;
  expected: string;
}

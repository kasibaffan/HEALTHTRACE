import type {
  Alert,
  Analytics,
  AppConfigResponse,
  AwsCheckResult,
  AwsStatus,
  DemoScenario,
  Health,
  HipaaUser,
  Incident,
  IncidentDetail,
  LogContext,
  LogSearchResult,
  ServiceDetail,
  ServiceRow,
  WindowMetrics,
} from "./types";

const TOKEN_KEY = "healthtrace.operatorToken";

export function getOperatorToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setOperatorToken(token: string): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: token lives for this page only */
  }
}

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body) headers.set("Content-Type", "application/json");
  const token = getOperatorToken();
  if (token) headers.set("X-Operator-Token", token);

  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "The HEALTH TRACE backend is unreachable.");
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = "The request was rejected as invalid.";
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

const qs = (params: Record<string, string | number | undefined | null>) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
};

export const api = {
  health: () => request<Health>("/health"),
  services: () => request<ServiceRow[]>("/services"),
  service: (name: string) => request<ServiceDetail>(`/services/${encodeURIComponent(name)}`),
  metrics: (service: string, minutes: number) =>
    request<WindowMetrics[]>(`/metrics${qs({ service, minutes })}`),
  alerts: (params: { limit?: number; severity?: string; service?: string; kind?: string; incident_id?: number } = {}) =>
    request<Alert[]>(`/alerts${qs(params)}`),
  incidents: (params: { state?: string; limit?: number } = {}) => request<Incident[]>(`/incidents${qs(params)}`),
  incident: (id: number) => request<IncidentDetail>(`/incidents/${id}`),
  ack: (id: number) => request<Incident>(`/incidents/${id}/ack`, { method: "POST" }),
  resolve: (id: number) => request<Incident>(`/incidents/${id}/resolve`, { method: "POST" }),
  mute: (id: number, minutes: number) =>
    request<Incident>(`/incidents/${id}/mute`, { method: "POST", body: JSON.stringify({ minutes }) }),
  logs: (q: string, limit = 200) => request<LogSearchResult>(`/logs${qs({ q, limit })}`),
  logContext: (seq: number) => request<LogContext>(`/logs/${seq}/context`),
  hipaaUsers: () => request<HipaaUser[]>("/hipaa/users"),
  analytics: (hours: number) => request<Analytics>(`/analytics${qs({ hours })}`),
  config: () => request<AppConfigResponse>("/config"),
  awsStatus: () => request<AwsStatus>("/aws/status"),
  awsTestConnection: () => request<AwsCheckResult>("/aws/test-connection", { method: "POST" }),
  awsTestAlert: () => request<AwsCheckResult>("/aws/test-alert", { method: "POST" }),
  scenarios: () => request<{ enabled: boolean; scenarios: DemoScenario[] }>("/demo/scenarios"),
  inject: (scenario: string, duration_s: number) =>
    request<{ scenario: string; duration_s: number }>("/demo/inject", {
      method: "POST",
      body: JSON.stringify({ scenario, duration_s }),
    }),
};

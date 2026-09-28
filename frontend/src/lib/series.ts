import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLive, type SeriesPoint } from "./live";
import { api } from "./api";
import type { TsMarker, TsPoint } from "@/components/charts";
import type { Alert, WindowMetrics } from "./types";
import { KIND_LABEL, SEVERITY_ORDER, subjectOf } from "./format";

/** Must match anomaly.min_std / error_rate_z_threshold in config.yaml. */
export const MIN_STD = 0.01;
export const Z_THRESHOLD = 3;
const MAX_POINTS = 480;
const LIVE_HISTORY_MINUTES = 60;

export type SeriesMetric = "error_rate" | "errors" | "events" | "p95";

const toPoint = (m: WindowMetrics): SeriesPoint => ({
  t: new Date(m.window_end).getTime(),
  rate: m.error_rate,
  errors: m.errors,
  total: m.total,
  p95: m.p95_latency_ms,
  mean: m.baseline_mean ?? null,
  std: m.baseline_std ?? null,
});

/**
 * Bucket one or more services' 5s windows onto a shared time grid. Services
 * emit on their own 5s phase, and long ranges hold thousands of windows, so
 * both the fleet view and 6h/24h views go through here.
 */
function bucketize(sources: SeriesPoint[][], since: number, end: number): SeriesPoint[] {
  const bucketMs = Math.max(5000, Math.ceil((end - since) / MAX_POINTS / 5000) * 5000);
  const buckets = new Map<number, {
    errors: number; total: number; expected: number; covered: number; stdSum: number; stdN: number; p95: number; windows: number;
  }>();
  for (const list of sources) {
    for (let i = list.length - 1; i >= 0; i--) {
      const p = list[i];
      if (p.t < since) break;
      if (p.t > end) continue;
      const key = Math.floor(p.t / bucketMs) * bucketMs;
      const b = buckets.get(key) ?? { errors: 0, total: 0, expected: 0, covered: 0, stdSum: 0, stdN: 0, p95: 0, windows: 0 };
      b.errors += p.errors;
      b.total += p.total;
      b.p95 = Math.max(b.p95, p.p95);
      b.windows += 1;
      if (p.mean != null) {
        b.expected += p.mean * p.total;
        b.covered += p.total;
      }
      if (p.std != null) {
        b.stdSum += p.std;
        b.stdN += 1;
      }
      buckets.set(key, b);
    }
  }
  return [...buckets.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([t, b]) => {
      // Counts are per 60s window: average over the windows each service
      // contributed to this bucket, summed across services.
      const perService = Math.max(1, b.windows / sources.length);
      return {
      t,
      rate: b.total ? b.errors / b.total : 0,
      errors: b.errors / perService,
      total: b.total / perService,
      p95: b.p95,
      mean: b.covered ? b.expected / b.covered : null,
      std: sources.length === 1 && b.stdN ? b.stdSum / b.stdN : null,
      };
    });
}

function toTs(p: SeriesPoint, metric: SeriesMetric): TsPoint {
  if (metric === "error_rate") {
    const std = p.std != null ? Math.max(p.std, MIN_STD) : null;
    return {
      t: p.t,
      v: p.rate,
      mean: p.mean,
      lo: p.mean != null && std != null ? p.mean - Z_THRESHOLD * std : null,
      hi: p.mean != null && std != null ? p.mean + Z_THRESHOLD * std : null,
    };
  }
  if (metric === "errors") return { t: p.t, v: p.errors };
  if (metric === "events") return { t: p.t, v: p.total / 60 };
  return { t: p.t, v: p.p95 };
}

/** Longer ranges than the live buffer holds come from the metrics table. */
function useStoredHistory(names: string[], minutes: number) {
  const enabled = minutes > LIVE_HISTORY_MINUTES && names.length > 0;
  return useQuery({
    queryKey: ["history", names.join(","), minutes],
    enabled,
    staleTime: 30_000,
    queryFn: async () => {
      const results = await Promise.all(names.map((n) => api.metrics(n, minutes)));
      const out: Record<string, SeriesPoint[]> = {};
      names.forEach((n, i) => (out[n] = results[i].map(toPoint)));
      return out;
    },
  });
}

export function useSeries(service: string | "all", minutes: number, metric: SeriesMetric, anchor?: number, frozen?: number) {
  const series = useLive((s) => s.series);
  const names = useMemo(() => (service === "all" ? Object.keys(series) : [service]), [series, service]);
  const history = useStoredHistory(names, minutes);

  return useMemo(() => {
    const end = frozen ?? anchor ?? Date.now();
    const since = end - minutes * 60_000;
    const sources = names.map((n) => {
      const live = series[n] ?? [];
      const stored = history.data?.[n];
      if (!stored?.length) return live;
      const cutoff = stored[stored.length - 1].t;
      return [...stored, ...live.filter((p) => p.t > cutoff)];
    });
    const raw = service !== "all" && minutes <= LIVE_HISTORY_MINUTES
      ? (sources[0] ?? []).filter((p) => p.t >= since && p.t <= end)
      : bucketize(sources, since, end);
    return {
      points: raw.map((p) => toTs(p, metric)),
      domain: [since, end] as [number, number],
      raw,
      loading: history.isLoading && minutes > LIVE_HISTORY_MINUTES,
    };
  }, [series, names, history.data, history.isLoading, service, minutes, metric, anchor, frozen]);
}

/** One marker per burst: alerts within 45s of each other collapse to the worst one. */
export function alertMarkers(alerts: Alert[], service: string | "all", since: number, windowMs = 45_000): TsMarker[] {
  const relevant = alerts
    .filter((a) => (service === "all" ? a.service !== null : a.service === service))
    .map((a) => ({ a, t: new Date(a.ts).getTime() }))
    .filter((x) => x.t >= since)
    .sort((x, y) => x.t - y.t);
  const out: (TsMarker & { count: number })[] = [];
  for (const { a, t } of relevant) {
    const last = out[out.length - 1];
    if (last && t - last.t < windowMs) {
      last.count += 1;
      if (SEVERITY_ORDER[a.severity] > SEVERITY_ORDER[last.severity]) last.severity = a.severity;
      last.label = `${last.count} alerts, worst ${last.severity}`;
      continue;
    }
    out.push({ t, severity: a.severity, label: `${subjectOf(a)}: ${KIND_LABEL[a.kind]}`, count: 1 });
  }
  return out;
}

/** The latest point's age decides whether "now" is the wall clock or replayed history. */
export function useSeriesAnchor(): number {
  const series = useLive((s) => s.series);
  return useMemo(() => {
    let latest = 0;
    for (const list of Object.values(series)) {
      const last = list[list.length - 1];
      if (last && last.t > latest) latest = last.t;
    }
    const now = Date.now();
    return latest && now - latest > 5 * 60_000 ? latest : now;
  }, [series]);
}

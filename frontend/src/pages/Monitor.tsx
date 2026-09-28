import { useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { ArrowsOut, GearSix, Pause, Play } from "@phosphor-icons/react";
import { useLive } from "@/lib/live";
import { alertMarkers, useSeries, useSeriesAnchor, MIN_STD, Z_THRESHOLD, type SeriesMetric } from "@/lib/series";
import { SEVERITY_HEX, SIGNAL_HEX, TONE_HEX, deviation, ms, num, pct, serviceTone } from "@/lib/format";
import { Beacon, Button, EmptyState, PageHeader, Panel, PanelHeader, Segmented, cx } from "@/components/ui";
import { TimeSeries } from "@/components/charts";
import { LogLine } from "@/components/domain";

const RANGES = [
  { value: "5", label: "5m" },
  { value: "15", label: "15m" },
  { value: "60", label: "1h" },
  { value: "360", label: "6h" },
  { value: "1440", label: "24h" },
] as const;

const METRICS: { value: SeriesMetric; label: string }[] = [
  { value: "error_rate", label: "Error rate" },
  { value: "errors", label: "Errors" },
  { value: "events", label: "Events/s" },
  { value: "p95", label: "p95 latency" },
];

const FORMAT: Record<SeriesMetric, (v: number) => string> = {
  error_rate: (v) => `${(v * 100).toFixed(v < 0.1 ? 1 : 0)}%`,
  errors: (v) => num(v),
  events: (v) => num(v, 1),
  p95: (v) => ms(v),
};

function ConnectionLine() {
  const connection = useLive((s) => s.connection);
  const lastMessageAt = useLive((s) => s.lastMessageAt);
  const live = connection === "live";
  return (
    <div className="flex items-center gap-2.5 text-[12.5px]">
      <Beacon color={live ? SIGNAL_HEX : connection === "offline" ? SEVERITY_HEX.CRITICAL : SEVERITY_HEX.MEDIUM} pulse={live} size={8} />
      <span className="font-mono text-[11px] font-medium tracking-[0.14em]" style={{ color: live ? SIGNAL_HEX : SEVERITY_HEX.MEDIUM }}>
        {live ? "LIVE" : connection.toUpperCase()}
      </span>
      <span className="text-fg-dim">
        {live ? "WebSocket connected" : connection === "offline" ? "Backend unreachable" : "Reconnecting with backoff"}
        {lastMessageAt && live ? `, last message ${Math.max(0, Math.round((Date.now() - lastMessageAt) / 1000))}s ago` : ""}
      </span>
    </div>
  );
}

function WindowReadout({ service }: { service: string }) {
  const services = useLive((s) => s.services);
  const row = service === "all" ? null : services[service];
  if (!row) {
    const all = Object.values(services);
    const total = all.reduce((s, r) => s + r.total, 0);
    const errors = all.reduce((s, r) => s + r.errors, 0);
    return (
      <dl className="grid grid-cols-2 gap-x-6 gap-y-5 p-5 sm:grid-cols-3 xl:grid-cols-2">
        <Readout label="Events in window" value={num(total)} sub="last 60s, all services" />
        <Readout label="Errors in window" value={num(errors)} sub="level ERROR or status 5xx" />
        <Readout label="Error rate" value={pct(total ? errors / total : 0, 2)} />
        <Readout label="Services reporting" value={`${all.filter((r) => r.total > 0).length} of ${all.length}`} />
      </dl>
    );
  }
  const stdEff = row.baseline_std != null ? Math.max(row.baseline_std, MIN_STD) : null;
  const upper = row.baseline_mean != null && stdEff != null ? row.baseline_mean + Z_THRESHOLD * stdEff : null;
  const tone = serviceTone(row);
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-5 p-5 sm:grid-cols-3 xl:grid-cols-2">
      <Readout label="Current error rate" value={pct(row.error_rate, 2)} accent={TONE_HEX[tone]} sub={`${row.errors} of ${row.total} events`} />
      <Readout label="Baseline" value={row.baseline_mean != null ? pct(row.baseline_mean, 2) : "learning"}
        sub={row.baseline_is_fallback ? "all-hours fallback" : "this hour of day"} />
      <Readout label="Normal band" value={upper != null ? `≤ ${pct(upper, 1)}` : "-"} sub="mean + 3 std" />
      <Readout label="z-score" value={row.z != null ? row.z.toFixed(1) : "-"} sub={`anomaly at z ≥ ${Z_THRESHOLD}`} />
      <Readout label="Deviation" value={deviation(row.error_rate, row.baseline_mean)} />
      <Readout label="p95 latency" value={ms(row.p95_latency_ms)} sub={row.latency_baseline_mean != null ? `baseline ${ms(row.latency_baseline_mean)}` : undefined} />
    </dl>
  );
}

function Readout({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: string }) {
  return (
    <div>
      <dt className="text-[12px] text-fg-dim">{label}</dt>
      <dd className="mt-1 font-mono text-[19px] tracking-tight tabular" style={{ color: accent ?? "var(--color-fg)" }}>{value}</dd>
      {sub && <dd className="mt-0.5 text-[11.5px] text-fg-dim">{sub}</dd>}
    </div>
  );
}

export default function Monitor() {
  const services = useLive((s) => s.services);
  const alerts = useLive((s) => s.alerts);
  const logs = useLive((s) => s.logs);
  const logsPaused = useLive((s) => s.logsPaused);
  const setLogsPaused = useLive((s) => s.setLogsPaused);
  const [range, setRange] = useState<(typeof RANGES)[number]["value"]>("15");
  const [metric, setMetric] = useState<SeriesMetric>("error_rate");
  const [service, setService] = useState<string>("all");
  const [frozenAt, setFrozenAt] = useState<number | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const anchor = useSeriesAnchor();
  const minutes = Number(range);
  const { points, domain, loading } = useSeries(service, minutes, metric, anchor, frozenAt ?? undefined);
  const markers = useMemo(
    () => alertMarkers(alerts, service, domain[0], Math.max(45_000, (minutes * 60_000) / 120)),
    [alerts, service, domain, minutes],
  );

  const paused = frozenAt !== null;
  const togglePause = () => {
    const next = !paused;
    setFrozenAt(next ? Date.now() : null);
    setLogsPaused(next);
  };
  const fullscreen = () => {
    const el = chartRef.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen?.();
  };

  const serviceOptions = [{ value: "all", label: "All services" }, ...Object.values(services).map((s) => ({ value: s.service, label: s.label }))];

  return (
    <div>
      <PageHeader
        title="Live monitor"
        description={<ConnectionLine />}
        actions={
          <>
            <Button variant={paused ? "primary" : "secondary"} icon={paused ? <Play size={15} /> : <Pause size={15} />} onClick={togglePause}>
              {paused ? "Resume" : "Pause"}
            </Button>
            <Button icon={<ArrowsOut size={15} />} onClick={fullscreen}>
              Fullscreen
            </Button>
            <Link to="/app/settings#detection">
              <Button variant="ghost" icon={<GearSix size={15} />}>Configure</Button>
            </Link>
          </>
        }
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Panel className="overflow-hidden">
          <div ref={chartRef} className="flex h-full flex-col bg-ink-850">
            <div className="flex flex-wrap items-center gap-3 border-b border-[var(--hairline)] px-5 py-3.5">
              <label className="sr-only" htmlFor="svc">Service</label>
              <select
                id="svc"
                value={service}
                onChange={(e) => setService(e.target.value)}
                className="h-8 rounded-[var(--radius-control)] bg-ink-800 px-2.5 text-[12.5px] text-fg shadow-[inset_0_0_0_1px_var(--hairline-strong)] outline-none"
              >
                {serviceOptions.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
              <Segmented label="Metric" size="sm" value={metric} options={METRICS} onChange={setMetric} />
              <div className="flex-1" />
              <Segmented label="Range" size="sm" value={range} options={RANGES.map((r) => ({ value: r.value, label: r.label }))} onChange={setRange} />
            </div>
            <div className="relative flex-1 px-3 pb-4 pt-5">
              {paused && (
                <p className="absolute right-5 top-2 z-10 rounded-full bg-[#e3b35a18] px-2.5 py-1 text-[11px] font-medium text-sev-medium">
                  Paused. New windows are buffered.
                </p>
              )}
              {loading ? (
                <div className="skeleton h-[380px] w-full" />
              ) : points.length > 1 ? (
                <TimeSeries
                  points={points}
                  markers={markers}
                  xDomain={domain}
                  height={380}
                  yFormat={FORMAT[metric]}
                  showBand={metric === "error_rate"}
                  color={SIGNAL_HEX}
                  ariaLabel={`${METRICS.find((m) => m.value === metric)?.label} over the last ${RANGES.find((r) => r.value === range)?.label}`}
                />
              ) : (
                <EmptyState title="No windows in this range yet" body="Windows are emitted every 5 seconds of log time." className="h-[380px]" />
              )}
              <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 px-2 text-[11.5px] text-fg-dim">
                <span className="flex items-center gap-2"><span className="h-[2px] w-4 rounded-full bg-signal" /> {METRICS.find((m) => m.value === metric)?.label}</span>
                {metric === "error_rate" && (
                  <>
                    <span className="flex items-center gap-2"><span className="h-[1px] w-4 border-t border-dashed border-steel" /> Baseline</span>
                    <span className="flex items-center gap-2"><span className="h-2.5 w-4 rounded-sm bg-steel/20" /> Normal operating band</span>
                  </>
                )}
                <span className="flex items-center gap-2"><span className="size-2 rounded-full bg-sev-high" /> Anomaly markers, coloured by severity</span>
              </div>
            </div>
          </div>
        </Panel>

        <Panel>
          <PanelHeader title="Detection window" description="What the detector sees for the most recent 60 second window." />
          <div className="border-t border-[var(--hairline)]">
            <WindowReadout service={service} />
          </div>
        </Panel>
      </div>

      <Panel className="mt-5">
        <PanelHeader
          title="Event stream"
          description={logsPaused ? "Paused. Resume to continue streaming." : "Streaming parsed events as the tailer reads them."}
          actions={
            <Button size="sm" variant="ghost" icon={logsPaused ? <Play size={14} /> : <Pause size={14} />} onClick={() => setLogsPaused(!logsPaused)}>
              {logsPaused ? "Resume stream" : "Pause stream"}
            </Button>
          }
        />
        <div className={cx("h-[360px] overflow-y-auto border-t border-[var(--hairline)] py-1.5")}>
          {logs.length === 0 ? (
            <EmptyState title="No events yet" body="Start the generator or point LOG_DIR at a growing log file." className="py-20" />
          ) : (
            logs
              .filter((r) => service === "all" || (r.type === "app" && r.service === service))
              .slice(0, 120)
              .map((r) => <LogLine key={r.seq} record={r} />)
          )}
        </div>
      </Panel>
    </div>
  );
}

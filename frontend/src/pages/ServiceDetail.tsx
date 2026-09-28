import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import * as Tabs from "@radix-ui/react-tabs";
import { ArrowLeft, ShieldCheck } from "@phosphor-icons/react";
import { api } from "@/lib/api";
import { useLive } from "@/lib/live";
import { alertMarkers, useSeries, useSeriesAnchor } from "@/lib/series";
import type { BaselineCell } from "@/lib/types";
import { TONE_HEX, TONE_LABEL, ms, num, pct, serviceLabel, serviceTone } from "@/lib/format";
import { Bezel, EmptyState, ErrorState, Panel, PanelHeader, Segmented, Skeleton, SkeletonRows, cx } from "@/components/ui";
import { TimeSeries, useElementSize } from "@/components/charts";
import { AlertRow, IncidentItem, LogLine } from "@/components/domain";
import TelemetryCanvas from "@/three/TelemetryCanvas";

const tabClass =
  "h-9 rounded-[var(--radius-control)] px-3.5 text-[13px] font-medium text-fg-dim transition-colors hover:text-fg-muted data-[state=active]:bg-ink-750 data-[state=active]:text-fg data-[state=active]:shadow-[inset_0_0_0_1px_var(--hairline-strong)]";

/** The time-aware baseline: one learned mean (and spread) per hour of day. */
function BaselineProfile({ cells, currentHour, format, label }: { cells: BaselineCell[]; currentHour: number; format: (v: number) => string; label: string }) {
  const [ref, { width }] = useElementSize<HTMLDivElement>();
  const hourly = cells.filter((c) => c.hour_of_day >= 0);
  const global = cells.find((c) => c.hour_of_day === -1);
  const top = Math.max(1e-9, ...hourly.map((c) => c.mean + c.std));
  const h = 150;
  const colW = width / 24;
  return (
    <div>
      <div ref={ref} className="relative w-full" style={{ height: h + 22 }}>
        {width > 0 && (
          <svg width={width} height={h + 22} role="img" aria-label={`${label} baseline by hour of day`}>
            {Array.from({ length: 24 }, (_, hour) => {
              const c = hourly.find((x) => x.hour_of_day === hour);
              const x = hour * colW + colW * 0.2;
              const w = colW * 0.6;
              const active = hour === currentHour;
              if (!c) return <rect key={hour} x={x} y={h - 1} width={w} height={1} fill="var(--hairline-strong)" />;
              const y = h - (c.mean / top) * (h - 8);
              const ySpread = h - ((c.mean + c.std) / top) * (h - 8);
              return (
                <g key={hour}>
                  <title>{`${String(hour).padStart(2, "0")}:00  mean ${format(c.mean)}, spread ${format(c.std)}, ${c.count} windows${c.ready ? "" : " (warming up)"}`}</title>
                  <rect x={x} y={ySpread} width={w} height={Math.max(1, y - ySpread)} fill="var(--color-steel)" opacity={0.18} rx={2} />
                  <rect x={x} y={y} width={w} height={Math.max(1, h - y)} rx={2} fill={active ? "var(--color-signal)" : "var(--color-ink-600)"} opacity={c.ready ? 1 : 0.4} />
                </g>
              );
            })}
            {[0, 6, 12, 18, 23].map((hour) => (
              <text key={hour} x={hour * colW + colW / 2} y={h + 16} textAnchor="middle" className="fill-fg-dim font-mono text-[10px]">
                {String(hour).padStart(2, "0")}
              </text>
            ))}
          </svg>
        )}
      </div>
      <p className="mt-2 text-[12px] leading-relaxed text-fg-dim">
        Highlighted: the current hour (UTC), the bucket new windows are judged against. Faded bars are still warming up.
        {global && ` All-hours fallback: ${format(global.mean)}.`}
      </p>
    </div>
  );
}

export default function ServiceDetail() {
  const { name = "" } = useParams();
  const row = useLive((s) => s.services[name]);
  const alerts = useLive((s) => s.alerts);
  const incidents = useLive((s) => s.incidents);
  const [range, setRange] = useState("30");
  const anchor = useSeriesAnchor();
  const detail = useQuery({ queryKey: ["service", name], queryFn: () => api.service(name), refetchInterval: 15_000 });
  const logs = useQuery({ queryKey: ["service-logs", name], queryFn: () => api.logs(`service:${name}`, 150), refetchInterval: 4000 });
  const rate = useSeries(name, Number(range), "error_rate", anchor);
  const p95 = useSeries(name, Number(range), "p95", anchor);
  const events = useSeries(name, Number(range), "events", anchor);
  const markers = useMemo(() => alertMarkers(alerts, name, rate.domain[0]), [alerts, name, rate.domain]);

  if (detail.error) return <ErrorState error={detail.error} onRetry={() => detail.refetch()} />;
  const data = detail.data;
  const tone = row ? serviceTone(row) : "learning";
  const color = TONE_HEX[tone];
  const active = Object.values(incidents).filter((i) => i.service === name && i.state !== "RESOLVED");
  const history = (data?.incidents ?? []).filter((i) => !active.some((a) => a.id === i.id));
  const allRows = useLive.getState().services;
  const dependents = Object.values(allRows).filter((r) => r.depends_on.includes(name));
  const currentHour = new Date(anchor).getUTCHours();

  return (
    <div className="space-y-5">
      <Link to="/app/services" className="inline-flex items-center gap-1.5 text-[12.5px] text-fg-dim hover:text-fg">
        <ArrowLeft size={14} /> Services
      </Link>
      <Bezel coreClassName="overflow-hidden">
        <div className="grid lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="p-6 md:p-8">
            <div className="flex items-center gap-2.5">
              <span className="size-2.5 rounded-full" style={{ background: color, boxShadow: `0 0 0 4px ${color}22` }} />
              <span className="text-[12.5px] font-medium" style={{ color }}>{TONE_LABEL[tone]}</span>
            </div>
            <h1 className="mt-3 text-[30px] font-semibold tracking-[-0.025em] text-fg md:text-[36px]">{serviceLabel(name, row ? { [name]: row.label } : undefined)}</h1>
            <p className="mt-1 font-mono text-[12px] text-fg-dim">{name}  criticality {row?.criticality ?? "-"}</p>
            <dl className="mt-7 grid grid-cols-2 gap-6 sm:grid-cols-3 xl:grid-cols-6">
              {[
                ["Health", TONE_LABEL[tone]],
                ["Error rate", row ? pct(row.error_rate, 2) : "-"],
                ["Baseline", row?.baseline_mean != null ? pct(row.baseline_mean, 2) : "learning"],
                ["p95 latency", row ? ms(row.p95_latency_ms) : "-"],
                ["Requests / sec", row ? num(row.requests_per_second, 1) : "-"],
                ["Active anomalies", String(active.length)],
              ].map(([k, v]) => (
                <div key={k}>
                  <dt className="text-[12px] text-fg-dim">{k}</dt>
                  <dd className="mt-1 font-mono text-[17px] text-fg">{v}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="relative h-[240px] border-t border-[var(--hairline)] lg:h-auto lg:border-l lg:border-t-0">
            <TelemetryCanvas mode="map" focus={name} className="absolute inset-0" />
          </div>
        </div>
      </Bezel>

      <Tabs.Root defaultValue="overview">
        <Tabs.List aria-label="Service views" className="mb-4 flex flex-wrap gap-1.5">
          {["overview", "logs", "metrics", "anomalies", "alerts", "dependencies"].map((t) => (
            <Tabs.Trigger key={t} value={t} className={tabClass}>{t.charAt(0).toUpperCase() + t.slice(1)}</Tabs.Trigger>
          ))}
        </Tabs.List>

        <Tabs.Content value="overview" className="space-y-5 outline-none">
          <Panel>
            <PanelHeader
              title="Error rate against baseline"
              description="The band is the normal operating range the detector allows before it alerts."
              actions={<Segmented label="Range" size="sm" value={range} onChange={setRange} options={[{ value: "15", label: "15m" }, { value: "30", label: "30m" }, { value: "60", label: "1h" }, { value: "360", label: "6h" }]} />}
            />
            <div className="px-3 pb-4">
              {rate.points.length > 1 ? (
                <TimeSeries points={rate.points} markers={markers} xDomain={rate.domain} height={260} yFormat={(v) => `${(v * 100).toFixed(v < 0.1 ? 1 : 0)}%`} ariaLabel="Error rate" />
              ) : (
                <EmptyState title="No windows yet" className="h-[260px]" />
              )}
            </div>
          </Panel>
          <div className="grid gap-5 xl:grid-cols-2">
            <Panel>
              <PanelHeader title="Error-rate baseline by hour" description="Baselines are learned per hour of day, only from windows judged normal." />
              <div className="px-5 pb-5">
                {detail.isLoading ? <Skeleton className="h-40" /> : data?.baselines.error_rate.length ? (
                  <BaselineProfile cells={data.baselines.error_rate} currentHour={currentHour} format={(v) => pct(v, 2)} label="Error rate" />
                ) : <EmptyState title="Baseline still learning" body="It needs 12 normal windows per hour." className="py-10" />}
              </div>
            </Panel>
            <Panel>
              <PanelHeader title="Latency baseline by hour" description="p95 latency, learned the same way." />
              <div className="px-5 pb-5">
                {detail.isLoading ? <Skeleton className="h-40" /> : data?.baselines.p95_latency_ms.length ? (
                  <BaselineProfile cells={data.baselines.p95_latency_ms} currentHour={currentHour} format={ms} label="p95 latency" />
                ) : <EmptyState title="Baseline still learning" className="py-10" />}
              </div>
            </Panel>
          </div>
        </Tabs.Content>

        <Tabs.Content value="logs" className="outline-none">
          <Panel>
            <PanelHeader title="Recent log events" actions={<Link to={`/app/logs?q=service:${name}`} className="text-[12px] font-medium text-fg-muted hover:text-signal">Open in logs</Link>} />
            <div className="max-h-[560px] overflow-y-auto border-t border-[var(--hairline)] py-1.5">
              {logs.isLoading ? <SkeletonRows rows={8} /> : logs.data?.events.length ? logs.data.events.map((r) => <LogLine key={r.seq} record={r} />) : <EmptyState title="No recent events" className="py-12" />}
            </div>
          </Panel>
        </Tabs.Content>

        <Tabs.Content value="metrics" className="grid gap-5 outline-none xl:grid-cols-2">
          <Panel>
            <PanelHeader title="p95 latency" />
            <div className="px-3 pb-4">
              {p95.points.length > 1 ? <TimeSeries points={p95.points} xDomain={p95.domain} height={240} showBand={false} color="#8ea3bf" yFormat={ms} ariaLabel="p95 latency" /> : <EmptyState title="No windows yet" className="h-[240px]" />}
            </div>
          </Panel>
          <Panel>
            <PanelHeader title="Requests per second" />
            <div className="px-3 pb-4">
              {events.points.length > 1 ? <TimeSeries points={events.points} xDomain={events.domain} height={240} showBand={false} color="#8ea3bf" yFormat={(v) => num(v, 1)} ariaLabel="Requests per second" /> : <EmptyState title="No windows yet" className="h-[240px]" />}
            </div>
          </Panel>
        </Tabs.Content>

        <Tabs.Content value="anomalies" className="outline-none">
          <Panel>
            <PanelHeader title="Anomalies" description={`${active.length} active, ${history.length} earlier.`} />
            <div className="divide-y divide-[var(--hairline)] border-t border-[var(--hairline)]">
              {active.length + history.length === 0 ? (
                <EmptyState icon={<ShieldCheck size={20} />} title="No anomalies for this service" body="It has stayed within its expected range." />
              ) : (
                [...active, ...history].slice(0, 50).map((i) => <IncidentItem key={i.id} incident={i} />)
              )}
            </div>
          </Panel>
        </Tabs.Content>

        <Tabs.Content value="alerts" className="outline-none">
          <Panel>
            <PanelHeader title="Alerts" />
            <div className="divide-y divide-[var(--hairline)] border-t border-[var(--hairline)]">
              {detail.isLoading ? <SkeletonRows rows={5} /> : data?.alerts.length ? data.alerts.map((a) => <AlertRow key={a.id ?? a.ts} alert={a} />) : <EmptyState title="No alerts for this service" className="py-12" />}
            </div>
          </Panel>
        </Tabs.Content>

        <Tabs.Content value="dependencies" className="grid gap-5 outline-none lg:grid-cols-2">
          {[
            { title: "Calls", description: "Services this one depends on.", list: (row?.depends_on ?? []).map((d) => allRows[d]).filter(Boolean) },
            { title: "Called by", description: "Services that depend on this one.", list: dependents },
          ].map((group) => (
            <Panel key={group.title}>
              <PanelHeader title={group.title} description={group.description} />
              <div className="divide-y divide-[var(--hairline)] border-t border-[var(--hairline)]">
                {group.list.length === 0 ? (
                  <EmptyState title="None declared" className="py-10" />
                ) : (
                  group.list.map((dep) => {
                    const t = serviceTone(dep);
                    return (
                      <Link key={dep.service} to={`/app/services/${dep.service}`} className={cx("flex items-center gap-3 px-5 py-3.5 hover:bg-ink-800/60")}>
                        <span className="size-2 rounded-full" style={{ background: TONE_HEX[t] }} />
                        <span className="flex-1 text-[13.5px] text-fg">{dep.label}</span>
                        <span className="text-[12px] text-fg-dim">{TONE_LABEL[t]}</span>
                        <span className="font-mono text-[12.5px] text-fg-muted">{pct(dep.error_rate, 2)}</span>
                      </Link>
                    );
                  })
                )}
              </div>
            </Panel>
          ))}
        </Tabs.Content>
      </Tabs.Root>
    </div>
  );
}

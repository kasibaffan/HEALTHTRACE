import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { ShieldCheck, UserFocus } from "@phosphor-icons/react";
import * as Tabs from "@radix-ui/react-tabs";
import { api } from "@/lib/api";
import { useLive } from "@/lib/live";
import type { Incident, Severity } from "@/lib/types";
import { SEVERITIES, SEVERITY_ORDER, ago, isHipaaKind, num, serviceLabel } from "@/lib/format";
import { EmptyState, ErrorState, PageHeader, Panel, PanelHeader, Segmented, SkeletonRows, cx } from "@/components/ui";
import { IncidentItem } from "@/components/domain";

type View = "live" | "history" | "resolved" | "access";
const RANGE_HOURS: Record<string, number> = { "1h": 1, "6h": 6, "24h": 24, all: 24 * 365 };

const tabClass =
  "relative h-9 rounded-[var(--radius-control)] px-3.5 text-[13px] font-medium text-fg-dim transition-colors hover:text-fg-muted data-[state=active]:bg-ink-750 data-[state=active]:text-fg data-[state=active]:shadow-[inset_0_0_0_1px_var(--hairline-strong)]";

function useMergedIncidents() {
  const live = useLive((s) => s.incidents);
  const query = useQuery({ queryKey: ["incidents"], queryFn: () => api.incidents({ limit: 1000 }), refetchInterval: 15_000 });
  const merged = useMemo(() => {
    const byId = new Map<number, Incident>();
    for (const inc of query.data ?? []) byId.set(inc.id, inc);
    for (const inc of Object.values(live)) byId.set(inc.id, inc);
    return [...byId.values()];
  }, [live, query.data]);
  return { incidents: merged, query };
}

function Filters({
  severity, setSeverity, family, setFamily, service, setService, range, setRange, services, showRange,
}: {
  severity: Severity | "all"; setSeverity: (s: Severity | "all") => void;
  family: string; setFamily: (s: string) => void;
  service: string; setService: (s: string) => void;
  range: string; setRange: (s: string) => void;
  services: string[]; showRange: boolean;
}) {
  const select =
    "h-8 rounded-[var(--radius-control)] bg-ink-800 px-2.5 text-[12.5px] text-fg shadow-[inset_0_0_0_1px_var(--hairline-strong)] outline-none";
  return (
    <div className="flex flex-wrap items-center gap-2.5 border-b border-[var(--hairline)] px-5 py-3.5">
      <Segmented
        label="Severity"
        size="sm"
        value={severity}
        onChange={setSeverity}
        options={[{ value: "all" as const, label: "All" }, ...SEVERITIES.map((s) => ({ value: s, label: s.charAt(0) + s.slice(1).toLowerCase() }))]}
      />
      <label className="sr-only" htmlFor="family">Family</label>
      <select id="family" className={select} value={family} onChange={(e) => setFamily(e.target.value)}>
        <option value="all">All families</option>
        <option value="service">Service health</option>
        <option value="hipaa">HIPAA access</option>
      </select>
      <label className="sr-only" htmlFor="service">Service</label>
      <select id="service" className={select} value={service} onChange={(e) => setService(e.target.value)}>
        <option value="all">All services</option>
        {services.map((s) => (
          <option key={s} value={s}>{serviceLabel(s)}</option>
        ))}
      </select>
      {showRange && (
        <Segmented
          label="Time range"
          size="sm"
          value={range}
          onChange={setRange}
          options={[{ value: "1h", label: "1h" }, { value: "6h", label: "6h" }, { value: "24h", label: "24h" }, { value: "all", label: "All" }]}
        />
      )}
    </div>
  );
}

function AccessPatterns() {
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["hipaa-users"], queryFn: api.hipaaUsers, refetchInterval: 5000 });
  const config = useQuery({ queryKey: ["config"], queryFn: api.config, staleTime: 60_000 });
  const hipaa = config.data?.detection.hipaa;
  if (isLoading) return <SkeletonRows rows={6} />;
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data?.length)
    return (
      <EmptyState
        icon={<UserFocus size={20} />}
        title="No record access in the last 10 minutes"
        body={hipaa ? `Staff traffic follows business hours (${hipaa.off_hours_start} to ${hipaa.off_hours_end}, ${hipaa.timezone}). Access patterns appear as audit events arrive.` : undefined}
      />
    );
  return (
    <div>
      <p className="px-5 pb-3 pt-4 text-[12.5px] leading-relaxed text-fg-dim">
        Rolling 10 minute view per user. Bulk access fires above each user's threshold: three times their own baseline, never below {hipaa ? num(hipaa.bulk_min_threshold) : "the floor"} distinct patients.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-[12.5px]">
          <thead className="text-[11px] text-fg-dim">
            <tr className="border-y border-[var(--hairline)]">
              <th className="px-5 py-2.5 font-normal">User</th>
              <th className="px-3 py-2.5 font-normal">Distinct patients</th>
              <th className="px-3 py-2.5 font-normal">Threshold</th>
              <th className="px-3 py-2.5 font-normal">Exports</th>
              <th className="px-3 py-2.5 font-normal">Off-hours</th>
              <th className="px-3 py-2.5 font-normal">Out of region</th>
              <th className="px-5 py-2.5 text-right font-normal">Last seen</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--hairline)] font-mono">
            {data.map((u) => {
              const ratio = u.distinct_patients / u.bulk_threshold;
              const hot = ratio > 1 || u.region_mismatch_patients > 0 || u.off_hours_events > 0;
              return (
                <tr key={u.user_id} className={cx("transition-colors hover:bg-ink-800/60", hot && "text-fg")}>
                  <td className="px-5 py-2.5 text-fg">{u.user_id}</td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2.5">
                      <span className={ratio > 1 ? "text-sev-critical" : "text-fg-muted"}>{u.distinct_patients}</span>
                      <span className="relative h-1 w-20 overflow-hidden rounded-full" aria-hidden>
                        <span
                          className="absolute inset-y-0 left-0 rounded-full"
                          style={{ width: `${Math.min(100, ratio * 100)}%`, background: ratio > 1 ? "var(--color-sev-critical)" : "var(--color-signal-soft)" }}
                        />
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-fg-dim">{num(u.bulk_threshold)}</td>
                  <td className="px-3 py-2.5 text-fg-muted">{u.exports}</td>
                  <td className={cx("px-3 py-2.5", u.off_hours_events ? "text-sev-medium" : "text-fg-dim")}>{u.off_hours_events}</td>
                  <td className={cx("px-3 py-2.5", u.region_mismatch_patients ? "text-sev-high" : "text-fg-dim")}>{u.region_mismatch_patients}</td>
                  <td className="px-5 py-2.5 text-right text-fg-dim">{ago(u.last_seen)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function Anomalies() {
  const [params, setParams] = useSearchParams();
  const view = (params.get("view") as View) ?? "live";
  const setView = (v: string) => setParams((p) => { p.set("view", v); return p; }, { replace: true });
  const [severity, setSeverity] = useState<Severity | "all">("all");
  const [family, setFamily] = useState("all");
  const [service, setService] = useState("all");
  const [range, setRange] = useState("24h");
  const { incidents, query } = useMergedIncidents();
  const services = useLive((s) => s.services);

  const filtered = useMemo(() => {
    const since = Date.now() - RANGE_HOURS[range] * 3600_000;
    return incidents
      .filter((i) => (view === "live" ? i.state !== "RESOLVED" : view === "resolved" ? i.state === "RESOLVED" : true))
      .filter((i) => view === "live" || new Date(i.opened_at).getTime() >= since)
      .filter((i) => severity === "all" || i.peak_severity === severity)
      .filter((i) => family === "all" || (family === "hipaa" ? isHipaaKind(i.kind) : !isHipaaKind(i.kind)))
      .filter((i) => service === "all" || i.service === service)
      .sort((a, b) =>
        view === "live"
          ? SEVERITY_ORDER[b.peak_severity] - SEVERITY_ORDER[a.peak_severity] || b.opened_at.localeCompare(a.opened_at)
          : b.opened_at.localeCompare(a.opened_at),
      );
  }, [incidents, view, severity, family, service, range]);

  const counts = {
    live: incidents.filter((i) => i.state !== "RESOLVED").length,
    resolved: incidents.filter((i) => i.state === "RESOLVED").length,
    history: incidents.length,
  };

  return (
    <div>
      <PageHeader
        title="Anomalies"
        description="Alerts are de-duplicated into anomalies by fingerprint. Each one moves from active to acknowledged to resolved, and resolves itself once its service is back within range."
      />
      <Tabs.Root value={view} onValueChange={setView}>
        <Tabs.List aria-label="Anomaly views" className="mb-4 flex flex-wrap gap-1.5">
          <Tabs.Trigger value="live" className={tabClass}>Live <span className="ml-1 font-mono text-fg-dim">{counts.live}</span></Tabs.Trigger>
          <Tabs.Trigger value="history" className={tabClass}>Historical <span className="ml-1 font-mono text-fg-dim">{counts.history}</span></Tabs.Trigger>
          <Tabs.Trigger value="resolved" className={tabClass}>Resolved <span className="ml-1 font-mono text-fg-dim">{counts.resolved}</span></Tabs.Trigger>
          <Tabs.Trigger value="access" className={tabClass}>Access patterns</Tabs.Trigger>
        </Tabs.List>

        {(["live", "history", "resolved"] as const).map((v) => (
          <Tabs.Content key={v} value={v} className="outline-none">
            <Panel>
              <Filters
                severity={severity} setSeverity={setSeverity}
                family={family} setFamily={setFamily}
                service={service} setService={setService}
                range={range} setRange={setRange}
                services={Object.keys(services)}
                showRange={v !== "live"}
              />
              {query.isLoading && filtered.length === 0 ? (
                <SkeletonRows rows={5} />
              ) : query.error && filtered.length === 0 ? (
                <ErrorState error={query.error} onRetry={() => query.refetch()} />
              ) : filtered.length === 0 ? (
                <EmptyState
                  icon={<ShieldCheck size={20} />}
                  title={v === "live" ? "No active anomalies" : "Nothing matches these filters"}
                  body={v === "live" ? "Your systems are currently operating within their expected range." : "Widen the time range or clear a filter."}
                />
              ) : (
                <div className="divide-y divide-[var(--hairline)]">
                  {filtered.slice(0, 200).map((inc) => <IncidentItem key={inc.id} incident={inc} />)}
                </div>
              )}
            </Panel>
          </Tabs.Content>
        ))}

        <Tabs.Content value="access" className="outline-none">
          <Panel>
            <PanelHeader title="HIPAA access patterns" description="Per-user record access in the current rolling window. Patient identifiers are never shown." />
            <AccessPatterns />
          </Panel>
        </Tabs.Content>
      </Tabs.Root>
    </div>
  );
}

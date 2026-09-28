import { useQuery } from "@tanstack/react-query";
import { Database, FileText, Info, Stack } from "@phosphor-icons/react";
import { api } from "@/lib/api";
import { useLive } from "@/lib/live";
import { bytes, num, pct } from "@/lib/format";
import { ErrorState, PageHeader, Panel, PanelHeader, Skeleton } from "@/components/ui";

export default function Projects() {
  const config = useQuery({ queryKey: ["config"], queryFn: api.config, refetchInterval: 10_000 });
  const health = useLive((s) => s.health);
  if (config.isLoading) return <Skeleton className="h-80" />;
  if (config.error || !config.data) return <ErrorState error={config.error} onRetry={() => config.refetch()} />;
  const dep = config.data.deployment;
  const services = config.data.detection.services;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Projects"
        description="A project is one monitored system; an environment is one deployment of it. Each HEALTH TRACE deployment watches exactly one project environment."
      />

      <Panel>
        <div className="grid gap-6 p-6 md:grid-cols-[1.2fr_1fr_1fr_1fr] md:items-center">
          <div className="flex items-center gap-4">
            <span className="grid size-12 place-items-center rounded-[14px] bg-signal-deep font-mono text-[15px] font-semibold text-signal">
              {dep.project_name.slice(0, 2).toUpperCase()}
            </span>
            <div>
              <p className="text-[18px] font-semibold tracking-tight text-fg">{dep.project_name}</p>
              <p className="text-[12.5px] text-fg-dim">{Object.keys(services).length} services, 1 audit stream</p>
            </div>
          </div>
          <div><p className="text-[12px] text-fg-dim">Environment</p><p className="mt-1 font-mono text-[15px] text-fg">{dep.environment}</p></div>
          <div><p className="text-[12px] text-fg-dim">AWS mode</p><p className="mt-1 font-mono text-[15px] text-fg">{dep.aws_mode}</p></div>
          <div><p className="text-[12px] text-fg-dim">Demo scenarios</p><p className="mt-1 font-mono text-[15px] text-fg">{dep.demo_mode ? "enabled" : "disabled"}</p></div>
        </div>
      </Panel>

      <Panel>
        <PanelHeader title="Data sources" description="Continuously growing log files, tailed incrementally. Offsets are saved so a restart resumes where it stopped." />
        <div className="divide-y divide-[var(--hairline)] border-t border-[var(--hairline)]">
          {dep.log_sources.map((src) => {
            const tail = health?.tailers.find((t) => t.path === src.name);
            const read = src.size_bytes ? src.offset / src.size_bytes : 1;
            return (
              <div key={src.path} className="grid gap-3 px-5 py-4 md:grid-cols-[1.4fr_1fr_1fr_1fr] md:items-center">
                <div className="flex items-center gap-3">
                  <FileText size={18} className="text-fg-dim" />
                  <div className="min-w-0">
                    <p className="text-[13.5px] font-medium text-fg">{src.name === "app.log" ? "Application logs" : "Access audit logs"}</p>
                    <p className="truncate font-mono text-[11.5px] text-fg-dim">{src.path}</p>
                  </div>
                </div>
                <p className="text-[12.5px] text-fg-muted"><span className="font-mono text-fg">{bytes(src.size_bytes)}</span> on disk</p>
                <p className="text-[12.5px] text-fg-muted"><span className="font-mono text-fg">{pct(read, 1)}</span> read</p>
                <p className="text-[12.5px]" style={{ color: tail?.caught_up ? "#56dcc8" : "#e3b35a" }}>
                  {tail ? (tail.caught_up ? "Caught up, tailing" : "Replaying backlog") : "Waiting"}
                </p>
              </div>
            );
          })}
        </div>
      </Panel>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel>
          <PanelHeader title="Services in this project" />
          <ul className="divide-y divide-[var(--hairline)] border-t border-[var(--hairline)]">
            {Object.entries(services).map(([name, s]) => (
              <li key={name} className="flex items-center gap-3 px-5 py-3 text-[13px]">
                <Stack size={16} className="text-fg-dim" />
                <span className="flex-1 text-fg">{s.label ?? name}</span>
                <span className="font-mono text-[12px] text-fg-dim">criticality {s.criticality}</span>
              </li>
            ))}
          </ul>
        </Panel>
        <Panel>
          <PanelHeader title="Adding projects and environments" />
          <div className="space-y-3 border-t border-[var(--hairline)] px-5 py-4 text-[13px] leading-relaxed text-fg-muted">
            <p className="flex gap-2.5"><Info size={16} className="mt-0.5 shrink-0 text-signal" /> Deploy another HEALTH TRACE service per project environment (for example Production and Staging), each with its own PROJECT_NAME, ENVIRONMENT, LOG_DIR and SNS topic.</p>
            <p className="flex gap-2.5"><Database size={16} className="mt-0.5 shrink-0 text-signal" /> Each deployment keeps its own baselines and anomaly history, so a noisy staging environment never skews production's notion of normal.</p>
            <p className="text-fg-dim">A single console spanning several deployments is not part of this release.</p>
          </div>
        </Panel>
      </div>
      <p className="text-[11.5px] text-fg-dim">Events processed this session: {num((health?.events_processed.app ?? 0) + (health?.events_processed.audit ?? 0))}.</p>
    </div>
  );
}

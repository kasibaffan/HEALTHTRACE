import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { ArrowRight } from "@phosphor-icons/react";
import TelemetryCanvas from "@/three/TelemetryCanvas";
import { useLive } from "@/lib/live";
import { TONE_HEX, TONE_LABEL, ms, num, pct, serviceLabel, serviceTone } from "@/lib/format";
import { Bezel, PageHeader, Panel, PanelHeader, SkeletonRows } from "@/components/ui";

export default function Services() {
  const services = useLive((s) => s.services);
  const navigate = useNavigate();
  const [focus, setFocus] = useState<string | null>(null);
  const rows = Object.values(services).sort((a, b) => (b.criticality ?? 0) - (a.criticality ?? 0));
  const dependents = (name: string) => rows.filter((r) => r.depends_on.includes(name)).map((r) => r.service);

  const select = (name: string) => {
    setFocus(name);
    window.setTimeout(() => navigate(`/app/services/${name}`), 650);
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Services"
        description="Each node is a service streaming log events into detection. Colour is its health, links are declared dependencies. Select a node to zoom into it."
      />
      <Bezel coreClassName="overflow-hidden">
        <div className="relative h-[min(560px,64vh)]">
          <TelemetryCanvas mode="map" focus={focus} onSelect={select} className="absolute inset-0" />
          <div className="pointer-events-none absolute left-5 top-5 flex flex-wrap gap-x-5 gap-y-2 text-[11.5px] text-fg-muted">
            {(["healthy", "learning", "MEDIUM", "HIGH", "CRITICAL"] as const).map((t) => (
              <span key={t} className="flex items-center gap-2">
                <span className="size-2 rounded-full" style={{ background: TONE_HEX[t] }} />
                {TONE_LABEL[t]}
              </span>
            ))}
          </div>
        </div>
      </Bezel>

      <Panel>
        <PanelHeader title="Topology" description="Dependencies are declared per service in config.yaml." />
        <div className="divide-y divide-[var(--hairline)] border-t border-[var(--hairline)]">
          {rows.length === 0 ? (
            <SkeletonRows rows={5} />
          ) : (
            rows.map((row) => {
              const tone = serviceTone(row);
              const color = TONE_HEX[tone];
              return (
                <Link
                  key={row.service}
                  to={`/app/services/${row.service}`}
                  onMouseEnter={() => setFocus(null)}
                  className="group grid gap-3 px-5 py-4 transition-colors hover:bg-ink-800/60 md:grid-cols-[1.2fr_1fr_1fr_1.4fr_auto] md:items-center"
                >
                  <div className="flex items-center gap-3">
                    <span className="size-2.5 rounded-full" style={{ background: color, boxShadow: `0 0 0 4px ${color}1f` }} />
                    <div>
                      <p className="text-[14px] font-medium text-fg group-hover:text-signal">{row.label}</p>
                      <p className="text-[11.5px] text-fg-dim">{TONE_LABEL[tone]}, criticality {row.criticality ?? "-"}</p>
                    </div>
                  </div>
                  <p className="font-mono text-[12.5px] text-fg-muted">
                    {pct(row.error_rate, 2)} <span className="text-fg-dim">err</span>
                  </p>
                  <p className="font-mono text-[12.5px] text-fg-muted">
                    {num(row.requests_per_second, 1)} <span className="text-fg-dim">req/s</span>
                    <span className="ml-3">{ms(row.p95_latency_ms)}</span> <span className="text-fg-dim">p95</span>
                  </p>
                  <p className="text-[12px] text-fg-dim">
                    {row.depends_on.length ? <>calls {row.depends_on.map((d) => serviceLabel(d)).join(", ")}</> : "no upstream dependencies"}
                    {dependents(row.service).length > 0 && <><br />called by {dependents(row.service).map((d) => serviceLabel(d)).join(", ")}</>}
                  </p>
                  <ArrowRight size={14} className="hidden text-fg-dim transition-transform group-hover:translate-x-0.5 group-hover:text-signal md:block" />
                </Link>
              );
            })
          )}
        </div>
      </Panel>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { Check, Eye, Info, Minus } from "@phosphor-icons/react";
import { api } from "@/lib/api";
import type { IncidentEvent } from "@/lib/types";
import { KIND_LABEL, stamp, subjectOf } from "@/lib/format";
import { EmptyState, PageHeader, Panel, PanelHeader, SkeletonRows } from "@/components/ui";

const ROLES = ["Owner", "Admin", "Engineer", "Viewer"] as const;
const PERMISSIONS: { action: string; roles: (typeof ROLES)[number][] }[] = [
  { action: "View dashboards, logs and anomalies", roles: ["Owner", "Admin", "Engineer", "Viewer"] },
  { action: "Acknowledge, resolve and mute anomalies", roles: ["Owner", "Admin", "Engineer"] },
  { action: "Inject demo scenarios", roles: ["Owner", "Admin", "Engineer"] },
  { action: "Send AWS test alerts", roles: ["Owner", "Admin"] },
  { action: "Change detection configuration", roles: ["Owner", "Admin"] },
  { action: "Manage members and roles", roles: ["Owner"] },
];

const OPERATOR_EVENTS: IncidentEvent["event_type"][] = ["acknowledged", "resolved", "muted"];

function Activity() {
  // Operator actions are recorded on each anomaly's timeline; surface the recent ones.
  const { data, isLoading } = useQuery({
    queryKey: ["team-activity"],
    queryFn: async () => {
      const incidents = await api.incidents({ limit: 40 });
      const details = await Promise.all(
        incidents.filter((i) => i.acknowledged_at || i.state === "RESOLVED" || i.muted_until).slice(0, 15).map((i) => api.incident(i.id)),
      );
      return details
        .flatMap((d) => d.events.filter((e) => OPERATOR_EVENTS.includes(e.event_type)).map((e) => ({ e, incident: d.incident })))
        .sort((a, b) => b.e.ts.localeCompare(a.e.ts))
        .slice(0, 12);
    },
    refetchInterval: 30_000,
  });
  if (isLoading) return <SkeletonRows rows={4} />;
  if (!data?.length) return <EmptyState title="No operator activity yet" body="Acknowledgements, resolutions and mutes appear here." className="py-10" />;
  return (
    <ul className="divide-y divide-[var(--hairline)]">
      {data.map(({ e, incident }) => (
        <li key={`${e.id}-${e.ts}`} className="flex items-center gap-3 px-5 py-3 text-[12.5px]">
          <span className="w-24 shrink-0 text-fg">{e.event_type === "muted" ? "Changed mute" : e.event_type === "acknowledged" ? "Acknowledged" : "Resolved"}</span>
          <span className="flex-1 truncate text-fg-muted">#{incident.id} {subjectOf(incident)}: {KIND_LABEL[incident.kind]}</span>
          <span className="font-mono text-[11.5px] text-fg-dim">{stamp(e.ts)}</span>
        </li>
      ))}
    </ul>
  );
}

export default function Team() {
  return (
    <div className="space-y-5">
      <PageHeader title="Team" description="Who can do what in HEALTH TRACE." />
      <Panel>
        <div className="flex gap-3 p-5 text-[13px] leading-relaxed text-fg-muted">
          <Info size={18} className="mt-0.5 shrink-0 text-signal" />
          <div>
            <p className="text-fg">Member management is not available in this release.</p>
            <p className="mt-1">
              Sign-in happens in front of the app (recommended: an Application Load Balancer with Amazon Cognito), and state-changing actions can additionally require an operator token. The role model below is the planned permission scheme; the backend does not enforce per-user roles yet.
            </p>
          </div>
        </div>
      </Panel>

      <Panel>
        <PanelHeader title="Roles and permissions" description="Planned scheme." />
        <div className="overflow-x-auto border-t border-[var(--hairline)]">
          <table className="w-full min-w-[620px] text-left text-[12.5px]">
            <thead className="text-[11.5px] text-fg-dim">
              <tr className="border-b border-[var(--hairline)]">
                <th className="px-5 py-3 font-normal">Permission</th>
                {ROLES.map((r) => <th key={r} className="px-3 py-3 text-center font-normal">{r}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--hairline)]">
              {PERMISSIONS.map((p) => (
                <tr key={p.action}>
                  <td className="px-5 py-3 text-fg-muted">{p.action}</td>
                  {ROLES.map((r) => (
                    <td key={r} className="px-3 py-3 text-center">
                      {p.roles.includes(r) ? <Check size={15} className="inline text-signal" aria-label="allowed" /> : <Minus size={15} className="inline text-fg-faint" aria-label="not allowed" />}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel>
        <PanelHeader title="Operator activity" description={<span className="inline-flex items-center gap-1.5"><Eye size={13} /> Recorded on each anomaly's timeline.</span>} />
        <div className="border-t border-[var(--hairline)]"><Activity /></div>
      </Panel>
    </div>
  );
}

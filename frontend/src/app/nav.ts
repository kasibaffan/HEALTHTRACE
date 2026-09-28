import {
  BellRinging,
  ChartLineUp,
  Cloud,
  FolderSimple,
  GearSix,
  Graph,
  Pulse,
  SquaresFour,
  Terminal,
  UsersThree,
  Waveform,
  type Icon,
} from "@phosphor-icons/react";

export interface NavItem {
  to: string;
  label: string;
  icon: Icon;
  group: "observe" | "platform";
  keywords?: string;
}

export const NAV: NavItem[] = [
  { to: "/app", label: "Dashboard", icon: SquaresFour, group: "observe", keywords: "home overview health" },
  { to: "/app/monitor", label: "Monitoring", icon: Pulse, group: "observe", keywords: "live monitor error rate chart" },
  { to: "/app/anomalies", label: "Anomalies", icon: Waveform, group: "observe", keywords: "incidents hipaa investigate" },
  { to: "/app/alerts", label: "Alerts", icon: BellRinging, group: "observe", keywords: "alert feed rules" },
  { to: "/app/logs", label: "Logs", icon: Terminal, group: "observe", keywords: "search explorer events" },
  { to: "/app/analytics", label: "Analytics", icon: ChartLineUp, group: "observe", keywords: "trends mttr" },
  { to: "/app/services", label: "Services", icon: Graph, group: "observe", keywords: "topology map dependencies" },
  { to: "/app/aws", label: "AWS", icon: Cloud, group: "platform", keywords: "cloudwatch sns integration" },
  { to: "/app/projects", label: "Projects", icon: FolderSimple, group: "platform", keywords: "environments data sources" },
  { to: "/app/team", label: "Team", icon: UsersThree, group: "platform", keywords: "members roles" },
  { to: "/app/settings", label: "Settings", icon: GearSix, group: "platform", keywords: "detection baseline config token" },
];

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { motion, useReducedMotion, useScroll, useSpring, useTransform, type MotionValue } from "motion/react";
import { ArrowRight, ArrowUpRight, BellRinging, Cloud, Cpu, Database, ShieldCheck } from "@phosphor-icons/react";
import TelemetryCanvas from "@/three/TelemetryCanvas";
import { Logo } from "@/app/Logo";
import { startLive, useLive, fleetRate } from "@/lib/live";
import { useSeries, useSeriesAnchor } from "@/lib/series";
import { KIND_LABEL, SEVERITY_HEX, SIGNAL_HEX, clock, num, pct, subjectOf } from "@/lib/format";
import { SeverityBadge, cx } from "@/components/ui";
import { TimeSeries } from "@/components/charts";

const STAGES = [
  { id: "read", label: "Read" },
  { id: "window", label: "Window" },
  { id: "baseline", label: "Baseline" },
  { id: "detect", label: "Detect" },
  { id: "severity", label: "Severity" },
  { id: "push", label: "Push" },
] as const;

const ease = [0.16, 1, 0.3, 1] as const;

function Reveal({ children, delay = 0, className }: { children: ReactNode; delay?: number; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, y: 28, filter: "blur(8px)" }}
      whileInView={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      viewport={{ once: true, amount: 0.35 }}
      transition={{ duration: 0.9, delay, ease }}
    >
      {children}
    </motion.div>
  );
}

function Nav() {
  return (
    <header className="fixed inset-x-0 top-4 z-40 flex justify-center px-4">
      <nav
        aria-label="Primary"
        className="flex h-12 w-full max-w-[880px] items-center gap-6 rounded-full bg-ink-900/60 pl-4 pr-1.5 shadow-[inset_0_0_0_1px_var(--hairline-strong),inset_0_1px_0_rgb(255_255_255/0.05),0_20px_50px_-20px_rgb(0_0_0/0.8)] backdrop-blur-xl"
      >
        <Link to="/" className="flex items-center gap-2.5" aria-label="HEALTH TRACE">
          <Logo size={24} />
          <span className="text-[12.5px] font-semibold tracking-[0.16em] text-fg">HEALTH TRACE</span>
        </Link>
        <div className="hidden flex-1 items-center gap-6 text-[13px] text-fg-muted md:flex">
          <a href="#read" className="transition-colors hover:text-fg">Pipeline</a>
          <a href="#severity" className="transition-colors hover:text-fg">Severity</a>
          <a href="#push" className="transition-colors hover:text-fg">AWS</a>
        </div>
        <div className="flex-1 md:hidden" />
        <Link
          to="/app"
          className="inline-flex h-9 items-center rounded-full bg-fg px-4 text-[13px] font-medium text-ink-950 transition-transform active:scale-[0.98]"
        >
          Open console
        </Link>
      </nav>
    </header>
  );
}

function Hero() {
  const reduce = useReducedMotion();
  const item = (i: number) =>
    reduce ? {} : { initial: { opacity: 0, y: 24 }, animate: { opacity: 1, y: 0 }, transition: { duration: 1, delay: 0.15 + i * 0.12, ease } };
  return (
    <section className="relative flex min-h-[100dvh] items-end px-5 pb-20 pt-24 md:px-12 md:pb-28 lg:px-20">
      <div className="max-w-[1040px]">
        <motion.h1 {...item(0)} className="max-w-[20ch] text-[40px] font-semibold leading-[1.04] tracking-[-0.035em] text-fg sm:text-[52px] lg:text-[64px] xl:max-w-none">
          Continuous intelligence for your application logs.
        </motion.h1>
        <motion.p {...item(1)} className="mt-6 max-w-[46ch] text-[16px] leading-relaxed text-fg-muted md:text-[18px]">
          Detect abnormal behaviour before it becomes a major incident.
        </motion.p>
        <motion.div {...item(2)} className="mt-9 flex flex-wrap items-center gap-3">
          <Link
            to="/app"
            className="group inline-flex h-12 items-center gap-3 rounded-full bg-signal py-1.5 pl-6 pr-1.5 text-[14.5px] font-medium text-ink-950 shadow-[0_18px_50px_-18px_rgb(86_220_200/0.7)] transition-transform active:scale-[0.98]"
          >
            Start Monitoring
            <span className="grid size-9 place-items-center rounded-full bg-ink-950/12 transition-transform duration-500 ease-[var(--ease-spring)] group-hover:-translate-y-px group-hover:translate-x-0.5">
              <ArrowRight size={16} weight="bold" />
            </span>
          </Link>
          <a
            href="#read"
            className="inline-flex h-12 items-center rounded-full px-6 text-[14.5px] font-medium text-fg shadow-[inset_0_0_0_1px_var(--hairline-strong)] backdrop-blur transition-colors hover:bg-ink-800/60"
          >
            Explore Demo
          </a>
        </motion.div>
      </div>
    </section>
  );
}

function StageRail({ progress }: { progress: MotionValue<number> }) {
  const [active, setActive] = useState<string | null>(null);
  useEffect(() => {
    const els = STAGES.map((s) => document.getElementById(s.id)).filter((el): el is HTMLElement => !!el);
    const io = new IntersectionObserver(
      (entries) => {
        const hit = entries.filter((e) => e.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (hit) setActive(hit.target.id);
      },
      { threshold: [0.25, 0.5, 0.75] },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
  const height = useTransform(progress, [0.08, 0.92], ["0%", "100%"]);
  const opacity = useTransform(progress, [0.04, 0.1, 0.78, 0.83], [0, 1, 1, 0]);
  return (
    <motion.aside style={{ opacity }} className="pointer-events-none fixed right-8 top-1/2 z-30 hidden -translate-y-1/2 xl:block" aria-hidden>
      <div className="relative pl-5">
        <div className="absolute bottom-1 left-0 top-1 w-px bg-[var(--hairline-strong)]">
          <motion.div className="w-px bg-signal" style={{ height }} />
        </div>
        <ol className="space-y-4">
          {STAGES.map((s) => (
            <li key={s.id} className={cx("font-mono text-[11px] tracking-[0.18em] transition-colors duration-500", active === s.id ? "text-signal" : "text-fg-faint")}>
              {s.label.toUpperCase()}
            </li>
          ))}
        </ol>
      </div>
    </motion.aside>
  );
}

function Chapter({ id, title, body, children, align = "left" }: { id: string; title: string; body: ReactNode; children?: ReactNode; align?: "left" | "right" | "wide" }) {
  return (
    <section id={id} className="relative flex min-h-[100dvh] items-center px-5 py-28 md:px-12 lg:px-20 xl:pr-44">
      <div
        className={cx(
          "w-full",
          align === "wide" ? "mx-auto max-w-[1180px]" : "grid gap-10 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] lg:items-center",
        )}
      >
        <Reveal className={cx(align === "right" && "lg:order-2", align === "wide" && "max-w-[640px]")}>
          <h2 className="text-[34px] font-semibold leading-[1.06] tracking-[-0.03em] text-fg md:text-[46px]">{title}</h2>
          <div className="mt-5 max-w-[48ch] text-[15.5px] leading-relaxed text-fg-muted">{body}</div>
        </Reveal>
        {children && (
          <Reveal delay={0.12} className={cx(align === "right" && "lg:order-1", align === "wide" && "mt-12")}>
            {children}
          </Reveal>
        )}
      </div>
    </section>
  );
}

function Glass({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cx("rounded-[22px] bg-ink-900/55 p-1.5 shadow-[inset_0_0_0_1px_var(--hairline-strong)] backdrop-blur-md", className)}>
      <div className="h-full rounded-[17px] bg-ink-900/70 shadow-[inset_0_1px_0_rgb(255_255_255/0.05)]">{children}</div>
    </div>
  );
}

function LiveLogs() {
  const logs = useLive((s) => s.logs);
  const connection = useLive((s) => s.connection);
  return (
    <Glass>
      <div className="flex items-center justify-between border-b border-[var(--hairline)] px-4 py-3 text-[11.5px] text-fg-dim">
        <span className="font-mono">data/logs/app.log, audit.log</span>
        <span className="font-mono" style={{ color: connection === "live" ? SIGNAL_HEX : undefined }}>{connection === "live" ? "tailing" : "offline"}</span>
      </div>
      <div className="h-[300px] overflow-hidden px-4 py-3 font-mono text-[11.5px] leading-[1.9]">
        {logs.length === 0 ? (
          <p className="text-fg-dim">Waiting for log lines from the backend.</p>
        ) : (
          logs.slice(0, 14).map((r) => (
            <p key={r.seq} className="truncate">
              <span className="text-fg-dim">{clock(r.ts)} </span>
              <span style={{ color: r.level === "ERROR" ? SEVERITY_HEX.CRITICAL : r.level === "WARN" ? SEVERITY_HEX.MEDIUM : "var(--color-fg-dim)" }}>
                {r.level.padEnd(5, " ")}
              </span>
              <span className="text-fg-muted"> {r.type === "app" ? r.service : r.user_id} </span>
              <span className="text-fg">{r.msg}</span>
            </p>
          ))
        )}
      </div>
    </Glass>
  );
}

/** A literal picture of the sliding window: events drift left, the bracket is the last 60 seconds. */
function WindowDiagram() {
  const services = useLive((s) => s.services);
  const fleet = fleetRate(services);
  const errors = Object.values(services).reduce((s, r) => s + r.errors, 0);
  const reduce = useReducedMotion();
  const ticks = useMemo(() => Array.from({ length: 90 }, (_, i) => ({ x: i * 13 + ((i * 37) % 7), err: i % 17 === 5 || i % 23 === 11, h: 18 + ((i * 53) % 22) })), []);
  return (
    <Glass>
      <div className="p-6">
        <div className="relative h-[120px] overflow-hidden">
          <div className={cx("absolute inset-y-0 left-0 flex w-[2340px] items-end", !reduce && "animate-[window-drift_24s_linear_infinite]")}>
            {[0, 1].map((copy) => (
              <svg key={copy} width="1170" height="120" aria-hidden>
                {ticks.map((t, i) => (
                  <rect key={i} x={t.x} y={120 - t.h} width={2} height={t.h} rx={1} fill={t.err ? SEVERITY_HEX.CRITICAL : "#3a4a60"} />
                ))}
              </svg>
            ))}
          </div>
          <div className="absolute inset-y-0 right-0 w-[46%] rounded-[12px] bg-signal/5 shadow-[inset_0_0_0_1px_rgb(86_220_200/0.45)]">
            <span className="absolute -top-0 left-3 top-2 font-mono text-[10.5px] text-signal">last 60s</span>
          </div>
        </div>
        <dl className="mt-6 grid grid-cols-3 gap-4 border-t border-[var(--hairline)] pt-5">
          <div><dt className="text-[11.5px] text-fg-dim">events in window</dt><dd className="mt-1 font-mono text-[20px] text-fg">{fleet.total ? num(fleet.total) : "-"}</dd></div>
          <div><dt className="text-[11.5px] text-fg-dim">errors</dt><dd className="mt-1 font-mono text-[20px] text-fg">{fleet.total ? num(errors) : "-"}</dd></div>
          <div><dt className="text-[11.5px] text-fg-dim">error rate</dt><dd className="mt-1 font-mono text-[20px] text-signal">{fleet.total ? pct(fleet.rate, 2) : "-"}</dd></div>
        </dl>
      </div>
    </Glass>
  );
}

function BaselinePreview() {
  const services = useLive((s) => s.services);
  const name = Object.keys(services).includes("prior_auth") ? "prior_auth" : Object.keys(services)[0] ?? "prior_auth";
  const anchor = useSeriesAnchor();
  const { points, domain } = useSeries(name, 30, "error_rate", anchor);
  return (
    <Glass>
      <div className="flex items-center justify-between px-5 pt-4 text-[12px] text-fg-dim">
        <span>{services[name]?.label ?? "Prior Authorization"}, last 30 minutes</span>
        <span className="font-mono">live</span>
      </div>
      <div className="px-2 pb-4 pt-2">
        {points.length > 1 ? (
          <TimeSeries points={points} xDomain={domain} height={240} yFormat={(v) => `${(v * 100).toFixed(1)}%`} ariaLabel="Live error rate with its baseline band" />
        ) : (
          <div className="grid h-[240px] place-items-center text-[13px] text-fg-dim">Connect the backend to see its live baseline band.</div>
        )}
      </div>
    </Glass>
  );
}

function SeverityComparison() {
  const rows = [
    { label: "Batch jobs", detail: "60% of batch runs failing, no patients waiting", score: 0.18, severity: "LOW" as const },
    { label: "Claims", detail: "error rate drifts to 9%, routine work", score: 0.36, severity: "MEDIUM" as const },
    { label: "Prior authorization", detail: "35% failing, mostly urgent requests, dozens of patients", score: 0.86, severity: "CRITICAL" as const },
  ];
  return (
    <Glass>
      <div className="space-y-5 p-6">
        {rows.map((r) => (
          <div key={r.label}>
            <div className="flex items-baseline justify-between gap-4">
              <p className="text-[14px] font-medium text-fg">{r.label}</p>
              <SeverityBadge severity={r.severity} size="sm" />
            </div>
            <p className="mt-0.5 text-[12.5px] text-fg-dim">{r.detail}</p>
            <div className="mt-2.5 h-1.5">
              <motion.div
                className="h-full rounded-full"
                style={{ background: SEVERITY_HEX[r.severity] }}
                initial={{ width: 0 }}
                whileInView={{ width: `${r.score * 100}%` }}
                viewport={{ once: true }}
                transition={{ duration: 1.2, ease }}
              />
            </div>
          </div>
        ))}
        <p className="border-t border-[var(--hairline)] pt-4 font-mono text-[12px] leading-relaxed text-fg-muted">
          score = deviation x (0.5 criticality + 0.5 patient impact)
        </p>
      </div>
    </Glass>
  );
}

function AlertPreview() {
  const alerts = useLive((s) => s.alerts);
  const latest = alerts.find((a) => a.severity === "HIGH" || a.severity === "CRITICAL") ?? alerts[0];
  return (
    <Glass>
      <div className="p-6">
        {latest ? (
          <>
            <div className="flex items-center gap-2.5">
              <SeverityBadge severity={latest.severity} />
              <span className="text-[12px] text-fg-dim">most recent alert, {clock(latest.ts)}</span>
            </div>
            <p className="mt-4 text-[20px] font-medium tracking-tight text-fg">{subjectOf(latest)}: {KIND_LABEL[latest.kind].toLowerCase()}</p>
            <p className="mt-2 font-mono text-[12.5px] leading-relaxed text-fg-muted">{latest.explanation}</p>
          </>
        ) : (
          <>
            <SeverityBadge severity="CRITICAL" />
            <p className="mt-4 text-[20px] font-medium tracking-tight text-fg">Prior Authorization: error rate spike</p>
            <p className="mt-2 font-mono text-[12.5px] leading-relaxed text-fg-muted">prior_auth error rate 35% vs baseline 2% (z=32.6); 127 urgent patients affected</p>
            <p className="mt-3 text-[11.5px] text-fg-dim">Example. Live alerts appear here when the backend is connected.</p>
          </>
        )}
      </div>
    </Glass>
  );
}

function AwsGrid() {
  const cells = [
    { icon: Cloud, title: "CloudWatch Logs", body: "Every alert, one log stream per day, created on first use.", tone: "bg-[radial-gradient(circle_at_20%_0%,rgb(86_220_200/0.14),transparent_60%)]" },
    { icon: BellRinging, title: "Amazon SNS", body: "HIGH and CRITICAL anomalies page on open and on escalation, never on every alert.", tone: "bg-[radial-gradient(circle_at_80%_0%,rgb(240_90_115/0.12),transparent_60%)]" },
    { icon: Cpu, title: "ECS on Fargate", body: "One container serves the API, the WebSocket and this interface behind an HTTPS load balancer.", tone: "" },
    { icon: ShieldCheck, title: "No keys in the app", body: "Credentials come from the task role. The browser never sees an AWS secret.", tone: "" },
    { icon: Database, title: "Durable state", body: "Baselines, anomalies and read positions persist, so a redeploy resumes where it stopped.", tone: "bg-[radial-gradient(circle_at_50%_120%,rgb(142_163_191/0.14),transparent_60%)]" },
  ];
  return (
    <div className="grid grid-flow-dense gap-3 md:grid-cols-6">
      {cells.map((c, i) => (
        <Glass key={c.title} className={cx(i === 0 || i === 1 ? "md:col-span-3" : "md:col-span-2")}>
          <div className={cx("h-full rounded-[17px] p-6", c.tone)}>
            <c.icon size={22} weight="light" className="text-signal" />
            <p className="mt-6 text-[16px] font-medium tracking-tight text-fg">{c.title}</p>
            <p className="mt-1.5 text-[13.5px] leading-relaxed text-fg-muted">{c.body}</p>
          </div>
        </Glass>
      ))}
    </div>
  );
}

export default function Landing() {
  const containerRef = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll();
  const smooth = useSpring(scrollYProgress, { stiffness: 60, damping: 20, mass: 0.6 });
  const veil = useTransform(scrollYProgress, [0, 0.06, 0.9, 1], [0.1, 0.55, 0.55, 0.3]);

  useEffect(() => {
    startLive();
    document.title = "HEALTH TRACE";
  }, []);

  return (
    <div ref={containerRef} className="grain relative bg-ink-950">
      <style>{"@keyframes window-drift { from { transform: translateX(0) } to { transform: translateX(-1170px) } }"}</style>
      <div className="fixed inset-0 z-0">
        <TelemetryCanvas mode="landing" progress={smooth} className="absolute inset-0" />
        <motion.div className="absolute inset-0 bg-ink-950" style={{ opacity: veil }} />
        <div className="absolute inset-0 bg-[linear-gradient(90deg,rgb(5_8_13/0.85)_0%,rgb(5_8_13/0.2)_55%,transparent_100%)]" />
      </div>

      <Nav />
      <StageRail progress={scrollYProgress} />

      <main className="relative z-10 overflow-x-hidden">
        <Hero />

        <Chapter
          id="read"
          title="Every line, as it is written."
          body="HEALTH TRACE tails your application and access-audit logs incrementally. It survives rotation and truncation, and remembers its read position, so a restart neither skips nor repeats a line."
        >
          <LiveLogs />
        </Chapter>

        <Chapter
          id="window"
          align="right"
          title="A rolling view, not a snapshot."
          body="Each service gets a 60 second sliding window, re-evaluated every 5 seconds of log time. Error rate, p95 latency and the patients affected are recomputed on every step."
        >
          <WindowDiagram />
        </Chapter>

        <Chapter
          id="baseline"
          title="Normal is learned, per hour."
          body="Baselines are kept per service and per hour of day, so a quiet night is never compared with a busy morning. They learn only from windows judged normal, so an outage cannot teach itself to look healthy."
        >
          <BaselinePreview />
        </Chapter>

        <Chapter
          id="detect"
          align="wide"
          title="Deviation, with a reason attached."
          body={
            <>
              A window is anomalous when it sits three standard deviations above its baseline with enough errors to rule out noise. A second detector watches record access for bulk reads, exports, off-hours activity and out-of-region patients.
            </>
          }
        />

        <Chapter
          id="severity"
          align="right"
          title="Severity follows patient impact."
          body="How far a metric moved is only one input. Service criticality and the number of patients affected, with urgent requests counted twice, decide how loudly HEALTH TRACE speaks."
        >
          <SeverityComparison />
        </Chapter>

        <Chapter
          id="push"
          title="The right people, in seconds."
          body="Alerts stream to the console over a WebSocket the moment they fire, are grouped into anomalies with a lifecycle, and leave the building through AWS."
        >
          <AlertPreview />
        </Chapter>

        <section className="relative px-5 pb-32 md:px-12 lg:px-20">
          <div className="mx-auto max-w-[1180px]">
            <Reveal>
              <h2 className="max-w-[18ch] text-[34px] font-semibold leading-[1.06] tracking-[-0.03em] text-fg md:text-[46px]">Built to run on AWS.</h2>
            </Reveal>
            <Reveal delay={0.1} className="mt-10">
              <AwsGrid />
            </Reveal>
          </div>
        </section>

        <section className="relative flex min-h-[80dvh] items-center px-5 md:px-12 lg:px-20">
          <div className="mx-auto w-full max-w-[1180px]">
            <Reveal>
              <h2 className="max-w-[16ch] text-[40px] font-semibold leading-[1.02] tracking-[-0.035em] text-fg md:text-[64px]">See your system the way detection sees it.</h2>
              <Link
                to="/app"
                className="group mt-10 inline-flex h-12 items-center gap-3 rounded-full bg-signal py-1.5 pl-6 pr-1.5 text-[14.5px] font-medium text-ink-950 transition-transform active:scale-[0.98]"
              >
                Start Monitoring
                <span className="grid size-9 place-items-center rounded-full bg-ink-950/12 transition-transform duration-500 group-hover:translate-x-0.5">
                  <ArrowUpRight size={16} weight="bold" />
                </span>
              </Link>
            </Reveal>
          </div>
        </section>

        <footer className="relative border-t border-[var(--hairline)] px-5 py-8 md:px-12 lg:px-20">
          <div className="mx-auto flex max-w-[1180px] flex-col gap-4 text-[12.5px] text-fg-dim sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2.5">
              <Logo size={20} />
              <span>HEALTH TRACE. Synthetic data only; no real patient information.</span>
            </div>
            <div className="flex gap-5">
              <Link to="/app" className="hover:text-fg">Console</Link>
              <Link to="/app/monitor" className="hover:text-fg">Live monitor</Link>
              <Link to="/app/aws" className="hover:text-fg">AWS</Link>
            </div>
          </div>
        </footer>
      </main>
    </div>
  );
}

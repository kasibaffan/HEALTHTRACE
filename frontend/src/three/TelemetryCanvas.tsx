import { Component, Suspense, lazy, useEffect, useRef, useState, type ReactNode } from "react";
import { useReducedMotion } from "motion/react";
import type { TelemetrySceneProps } from "./TelemetryScene";
import { cx } from "@/components/ui";

const TelemetryScene = lazy(() => import("./TelemetryScene"));

function webglAvailable(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return !!(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

class SceneBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    console.warn("health-trace: 3D scene disabled", error);
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function StaticFallback() {
  return (
    <div className="relative h-full w-full overflow-hidden bg-ink-950">
      <div className="grid-backdrop absolute inset-0 opacity-60" />
      <div className="absolute left-1/2 top-1/2 size-40 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(circle,rgb(86_220_200/0.28),transparent_65%)]" />
    </div>
  );
}

/**
 * Mounts the WebGL scene only when it can be seen: the render loop stops while
 * the canvas is scrolled away or the tab is hidden, and the three.js bundle is
 * fetched lazily so routes without a scene never pay for it.
 */
export default function TelemetryCanvas({ className, ...props }: Omit<TelemetrySceneProps, "active" | "reducedMotion"> & { className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion() ?? false;
  const [inView, setInView] = useState(false);
  const [visible, setVisible] = useState(() => document.visibilityState === "visible");
  const [supported] = useState(webglAvailable);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { rootMargin: "120px" });
    io.observe(el);
    const onVis = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", onVis);
    return () => {
      io.disconnect();
      document.removeEventListener("visibilitychange", onVis);
    };
  }, []);

  return (
    <div ref={ref} className={cx("overflow-hidden", className ?? "relative")}>
      {supported ? (
        <SceneBoundary fallback={<StaticFallback />}>
          <Suspense fallback={<StaticFallback />}>
            <TelemetryScene {...props} active={inView && visible} reducedMotion={reduce} />
          </Suspense>
        </SceneBoundary>
      ) : (
        <StaticFallback />
      )}
    </div>
  );
}

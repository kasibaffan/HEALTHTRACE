# Frontend

`frontend/` is a Vite + React 19 + TypeScript app.

## Structure

| Path | Contents |
|---|---|
| `src/lib/live.ts` | WebSocket client and Zustand store (services, series, alerts, incidents, logs) |
| `src/lib/api.ts`, `types.ts` | Typed REST client mirroring the backend models |
| `src/lib/series.ts` | Chart series, fleet aggregation, downsampling for long ranges |
| `src/lib/explain.ts` | "Why was this detected" and severity-score breakdowns |
| `src/three/` | Telemetry scene (React Three Fiber), lazy-loaded, paused when off screen |
| `src/components/` | UI primitives, SVG charts, shared domain rows |
| `src/app/` | Shell, sidebar, top bar, command palette (`Ctrl K`), toasts |
| `src/pages/` | Landing, Dashboard, Monitor, Anomalies, Investigation, Alerts, Logs, Analytics, Services, Service detail, AWS, Projects, Team, Settings |

## Notes

- The 3D scene reads live values inside the render loop, so React does not
  re-render the canvas on every metric.
- Charts are hand-built SVG on `d3-scale`/`d3-shape`; the error-rate band is
  exactly the detector's normal range (baseline mean plus/minus 3 standard
  deviations, with the same 1% spread floor).
- Controls that the backend does not support (rule editing, member
  management, multiple projects per deployment) are shown as unavailable
  rather than simulated.
- `prefers-reduced-motion` disables motion and freezes the scene.
- `npm run build` runs the TypeScript check and produces `dist/`, which the
  backend serves at `/`.

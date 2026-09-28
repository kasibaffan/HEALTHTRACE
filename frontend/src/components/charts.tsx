import { memo, useCallback, useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { scaleLinear, scaleTime } from "d3-scale";
import { area, curveMonotoneX, line } from "d3-shape";
import { max as d3max } from "d3-array";
import type { Severity } from "@/lib/types";
import { SEVERITY_HEX, SIGNAL_HEX, clock } from "@/lib/format";

export function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize((prev) => (prev.width === width && prev.height === height ? prev : { width, height }));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size] as const;
}

export interface TsPoint {
  t: number;
  v: number;
  /** Detection band for this point (baseline mean +- threshold), if a baseline existed. */
  lo?: number | null;
  hi?: number | null;
  mean?: number | null;
}

export interface TsMarker {
  t: number;
  severity: Severity;
  label: string;
}

interface TimeSeriesProps {
  points: TsPoint[];
  markers?: TsMarker[];
  height: number;
  yFormat: (v: number) => string;
  color?: string;
  xDomain?: [number, number];
  yMin?: number;
  showBand?: boolean;
  ariaLabel: string;
  tooltipExtra?: (p: TsPoint) => ReactNode;
}

const M = { top: 12, right: 12, bottom: 22, left: 46 };

export const TimeSeries = memo(function TimeSeries({
  points,
  markers = [],
  height,
  yFormat,
  color = SIGNAL_HEX,
  xDomain,
  yMin = 0,
  showBand = true,
  ariaLabel,
  tooltipExtra,
}: TimeSeriesProps) {
  const [ref, { width }] = useElementSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const gradientId = `ts-${useId().replace(/:/g, "")}`;

  const model = useMemo(() => {
    if (width <= 0 || points.length === 0) return null;
    const innerW = Math.max(10, width - M.left - M.right);
    const innerH = Math.max(10, height - M.top - M.bottom);
    const domain = xDomain ?? [points[0].t, points[points.length - 1].t];
    const x = scaleTime().domain(domain).range([0, innerW]);
    const yTop = Math.max(
      d3max(points, (p) => Math.max(p.v, showBand && p.hi != null ? p.hi : 0)) ?? 0,
      yMin + 1e-6,
    );
    const y = scaleLinear().domain([yMin, yTop * 1.12]).range([innerH, 0]).nice(4);

    const visible = points.filter((p) => p.t >= domain[0] - 10000 && p.t <= domain[1] + 10000);
    const lineGen = line<TsPoint>().x((p) => x(p.t)).y((p) => y(p.v)).curve(curveMonotoneX);
    const areaGen = area<TsPoint>().x((p) => x(p.t)).y0(innerH).y1((p) => y(p.v)).curve(curveMonotoneX);
    const bandPts = visible.filter((p) => p.lo != null && p.hi != null);
    const bandGen = area<TsPoint>()
      .x((p) => x(p.t))
      .y0((p) => y(Math.max(yMin, p.lo as number)))
      .y1((p) => y(p.hi as number))
      .curve(curveMonotoneX)
      .defined((p) => p.lo != null && p.hi != null);
    const meanGen = line<TsPoint>()
      .x((p) => x(p.t))
      .y((p) => y(p.mean as number))
      .curve(curveMonotoneX)
      .defined((p) => p.mean != null);

    return {
      innerW,
      innerH,
      x,
      y,
      visible,
      line: lineGen(visible) ?? "",
      area: areaGen(visible) ?? "",
      band: showBand && bandPts.length ? bandGen(visible) ?? "" : "",
      mean: showBand ? meanGen(visible) ?? "" : "",
      yTicks: y.ticks(4),
      xTicks: x.ticks(Math.max(2, Math.floor(innerW / 110))),
    };
  }, [width, height, points, xDomain, yMin, showBand]);

  const onMove = useCallback(
    (e: React.PointerEvent<SVGRectElement>) => {
      if (!model || model.visible.length === 0) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const t = model.x.invert(e.clientX - rect.left).getTime();
      let lo = 0;
      let hi = model.visible.length - 1;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (model.visible[mid].t < t) lo = mid + 1;
        else hi = mid;
      }
      const prev = model.visible[Math.max(0, lo - 1)];
      const idx = prev && Math.abs(prev.t - t) < Math.abs(model.visible[lo].t - t) ? lo - 1 : lo;
      setHover(idx);
    },
    [model],
  );

  const hovered = model && hover != null ? model.visible[hover] : null;

  return (
    <div ref={ref} className="relative w-full" style={{ height }}>
      {model ? (
        <svg width={width} height={height} role="img" aria-label={ariaLabel} className="overflow-visible">
          <defs>
            <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.22} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <g transform={`translate(${M.left},${M.top})`}>
            {model.yTicks.map((tick) => (
              <g key={tick} transform={`translate(0,${model.y(tick)})`}>
                <line x2={model.innerW} stroke="var(--hairline)" />
                <text x={-10} dy="0.32em" textAnchor="end" className="fill-fg-dim font-mono text-[10px]">
                  {yFormat(tick)}
                </text>
              </g>
            ))}
            {model.xTicks.map((tick) => (
              <text
                key={tick.getTime()}
                x={model.x(tick)}
                y={model.innerH + 16}
                textAnchor="middle"
                className="fill-fg-dim font-mono text-[10px]"
              >
                {clock(tick.toISOString()).slice(0, 5)}
              </text>
            ))}
            {model.band && <path d={model.band} fill="var(--color-steel)" fillOpacity={0.09} />}
            {model.mean && (
              <path d={model.mean} fill="none" stroke="var(--color-steel)" strokeOpacity={0.55} strokeDasharray="3 4" strokeWidth={1} />
            )}
            <path d={model.area} fill={`url(#${gradientId})`} />
            <path d={model.line} fill="none" stroke={color} strokeWidth={1.6} strokeLinejoin="round" />
            {markers.map((m, i) => {
              const px = model.x(m.t);
              if (px < 0 || px > model.innerW) return null;
              return (
                <g key={`${m.t}-${i}`} transform={`translate(${px},0)`}>
                  <line y1={0} y2={model.innerH} stroke={SEVERITY_HEX[m.severity]} strokeOpacity={0.35} strokeDasharray="2 3" />
                  <circle cy={4} r={3.5} fill={SEVERITY_HEX[m.severity]}>
                    <title>{m.label}</title>
                  </circle>
                </g>
              );
            })}
            {hovered && (
              <g transform={`translate(${model.x(hovered.t)},0)`} pointerEvents="none">
                <line y1={0} y2={model.innerH} stroke="var(--color-fg-dim)" strokeOpacity={0.6} />
                <circle cy={model.y(hovered.v)} r={3.5} fill={color} stroke="var(--color-ink-900)" strokeWidth={2} />
              </g>
            )}
            <rect
              width={model.innerW}
              height={model.innerH}
              fill="transparent"
              onPointerMove={onMove}
              onPointerLeave={() => setHover(null)}
            />
          </g>
        </svg>
      ) : (
        <div className="skeleton h-full w-full" />
      )}
      {hovered && model && (
        <div
          className="pointer-events-none absolute top-1 z-10 min-w-[150px] rounded-[10px] bg-ink-750/95 px-3 py-2 text-[11.5px] shadow-[inset_0_0_0_1px_var(--hairline-strong),0_12px_30px_-10px_rgb(0_0_0/0.6)] backdrop-blur"
          style={{
            left: Math.min(Math.max(M.left + model.x(hovered.t) + 12, 0), width - 170),
          }}
        >
          <p className="font-mono text-fg-dim">{clock(new Date(hovered.t).toISOString())}</p>
          <p className="mt-1 font-mono text-[13px] text-fg">{yFormat(hovered.v)}</p>
          {hovered.mean != null && (
            <p className="mt-0.5 text-fg-dim">
              baseline <span className="font-mono text-fg-muted">{yFormat(hovered.mean)}</span>
            </p>
          )}
          {tooltipExtra?.(hovered)}
        </div>
      )}
    </div>
  );
});

export const Sparkline = memo(function Sparkline({
  values,
  width = 96,
  height = 28,
  color = SIGNAL_HEX,
  ariaLabel,
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  ariaLabel: string;
}) {
  const d = useMemo(() => {
    if (values.length < 2) return "";
    const top = Math.max(...values, 1e-9);
    const x = scaleLinear().domain([0, values.length - 1]).range([1, width - 1]);
    const y = scaleLinear().domain([0, top]).range([height - 2, 2]);
    return line<number>().x((_, i) => x(i)).y((v) => y(v)).curve(curveMonotoneX)(values) ?? "";
  }, [values, width, height]);
  return (
    <svg width={width} height={height} role="img" aria-label={ariaLabel}>
      <path d={d} fill="none" stroke={color} strokeWidth={1.4} strokeLinecap="round" />
    </svg>
  );
});

/** Stacked columns, e.g. alerts per hour by severity. */
export function StackedColumns({
  rows,
  keys,
  colors,
  height,
  label,
  ariaLabel,
}: {
  rows: { key: string; values: Record<string, number> }[];
  keys: string[];
  colors: Record<string, string>;
  height: number;
  label: (key: string) => string;
  ariaLabel: string;
}) {
  const [ref, { width }] = useElementSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const totals = rows.map((r) => keys.reduce((s, k) => s + (r.values[k] ?? 0), 0));
  const top = Math.max(1, ...totals);
  const innerH = height - 22;
  const gap = 3;
  const barW = rows.length ? Math.max(2, (width - gap * (rows.length - 1)) / rows.length) : 0;

  return (
    <div ref={ref} className="relative w-full" style={{ height }}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel}>
          {rows.map((row, i) => {
            let y = innerH;
            const x = i * (barW + gap);
            return (
              <g key={row.key} onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)}>
                <rect x={x} y={0} width={barW} height={innerH} fill="transparent" />
                {totals[i] === 0 && <rect x={x} y={innerH - 1} width={barW} height={1} fill="var(--hairline-strong)" />}
                {keys.map((k) => {
                  const v = row.values[k] ?? 0;
                  if (!v) return null;
                  const h = Math.max(1.5, (v / top) * (innerH - 6));
                  y -= h;
                  return (
                    <rect key={k} x={x} y={y} width={barW} height={h} rx={Math.min(2, barW / 3)} fill={colors[k]}
                      opacity={hover === null || hover === i ? 0.9 : 0.35} />
                  );
                })}
              </g>
            );
          })}
          {rows.length > 0 && (
            <>
              <text x={0} y={height - 4} className="fill-fg-dim font-mono text-[10px]">{label(rows[0].key)}</text>
              <text x={width} y={height - 4} textAnchor="end" className="fill-fg-dim font-mono text-[10px]">
                {label(rows[rows.length - 1].key)}
              </text>
            </>
          )}
        </svg>
      )}
      {hover !== null && rows[hover] && (
        <div
          className="pointer-events-none absolute -top-2 z-10 rounded-[10px] bg-ink-750/95 px-3 py-2 text-[11.5px] shadow-[inset_0_0_0_1px_var(--hairline-strong)]"
          style={{ left: Math.min(hover * (barW + gap), Math.max(0, width - 150)) }}
        >
          <p className="font-mono text-fg-dim">{label(rows[hover].key)}</p>
          {keys.filter((k) => rows[hover].values[k]).map((k) => (
            <p key={k} className="mt-0.5 flex justify-between gap-4">
              <span style={{ color: colors[k] }}>{k}</span>
              <span className="font-mono text-fg">{rows[hover].values[k]}</span>
            </p>
          ))}
          {!totals[hover] && <p className="mt-0.5 text-fg-dim">none</p>}
        </div>
      )}
    </div>
  );
}

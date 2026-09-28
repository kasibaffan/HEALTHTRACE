import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, events as createEvents, useFrame, useThree, type DomEvent, type RootState, type ThreeEvent } from "@react-three/fiber";
import * as THREE from "three";
import type { MotionValue } from "motion/react";
import { useLive, type Pulse } from "@/lib/live";
import { SEVERITY_HEX, SIGNAL_HEX, TONE_HEX, serviceTone, pct, serviceLabel } from "@/lib/format";
import type { ServiceRow, Severity } from "@/lib/types";

export type SceneMode = "dashboard" | "landing" | "map";

export interface TelemetrySceneProps {
  mode: SceneMode;
  /** Landing only: 0..1 scroll progress through the story. */
  progress?: MotionValue<number>;
  focus?: string | null;
  onSelect?: (service: string) => void;
  active: boolean;
  reducedMotion: boolean;
}

const MAX_LANES = 8;
const PARTICLES = 2600;
const CORE = new THREE.Vector3(0, 0, 0);
const DEFAULT_SERVICES = ["prior_auth", "eligibility", "pharmacy", "claims", "batch"];

// Synthetic "idle" telemetry for the landing page when no backend is attached.
const IDLE = { rps: 6, err: 0.015 };

function nodePositions(count: number, mode: SceneMode): THREE.Vector3[] {
  const radius = mode === "map" ? 3.6 : 3.2;
  return Array.from({ length: count }, (_, i) => {
    const a = (i / count) * Math.PI * 2 - Math.PI / 2 + 0.35;
    return new THREE.Vector3(Math.cos(a) * radius, Math.sin(i * 1.7) * 0.45, Math.sin(a) * radius * 0.72);
  });
}

// -- particle lanes: service -> detection core ------------------------------------

const laneVertex = /* glsl */ `
  uniform float uTime;
  uniform vec3 uNodes[${MAX_LANES}];
  uniform float uRate[${MAX_LANES}];
  uniform float uErr[${MAX_LANES}];
  uniform float uAgitation[${MAX_LANES}];
  uniform vec3 uErrColor[${MAX_LANES}];
  uniform vec3 uColor;
  uniform float uPixelRatio;
  uniform float uLanes;
  attribute float aLane;
  attribute float aSeed;
  attribute float aOffset;
  attribute vec2 aJitter;
  varying vec3 vColor;
  varying float vAlpha;

  float hash(float n) { return fract(sin(n) * 43758.5453123); }

  void main() {
    int idx = int(aLane);
    vec3 p0 = uNodes[idx];
    vec3 p2 = vec3(0.0);
    vec3 dir = normalize(p2 - p0);
    vec3 side = normalize(cross(dir, vec3(0.0, 1.0, 0.0)));
    vec3 p1 = mix(p0, p2, 0.45) + vec3(0.0, 0.9 + aJitter.y * 0.5, 0.0) + side * aJitter.x * 0.9;

    float rate = uRate[idx];
    float speed = 0.07 + rate * 0.16;
    float t = fract(aOffset + uTime * speed * (0.8 + aSeed * 0.4));
    float it = 1.0 - t;
    vec3 pos = it * it * p0 + 2.0 * it * t * p1 + t * t * p2;

    float agitation = uAgitation[idx];
    pos += vec3(
      sin(uTime * 7.0 + aSeed * 61.0),
      cos(uTime * 9.0 + aSeed * 37.0),
      sin(uTime * 5.0 + aSeed * 17.0)
    ) * agitation * 0.18 * sin(t * 3.14159);

    float visible = step(aSeed, 0.12 + rate * 0.88) * step(float(idx) + 0.5, uLanes);
    float isErr = step(hash(aSeed * 91.7 + floor(uTime * speed + aOffset) * 3.1), clamp(uErr[idx] * 5.0, 0.0, 1.0));
    vColor = mix(uColor, uErrColor[idx], isErr);
    vAlpha = visible * sin(t * 3.14159) * (0.55 + isErr * 0.45);

    vec4 mv = modelViewMatrix * vec4(pos, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = visible * (1.6 + isErr * 1.8 + aSeed * 1.2) * uPixelRatio * (14.0 / -mv.z);
  }
`;

const laneFragment = /* glsl */ `
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c);
    if (d > 0.5) discard;
    float soft = smoothstep(0.5, 0.0, d);
    gl_FragColor = vec4(vColor, vAlpha * soft);
  }
`;

function Lanes({ nodes, rows, reduced }: { nodes: THREE.Vector3[]; rows: React.MutableRefObject<LaneData[]>; reduced: boolean }) {
  const material = useRef<THREE.ShaderMaterial>(null);
  const { gl } = useThree();

  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const lane = new Float32Array(PARTICLES);
    const seed = new Float32Array(PARTICLES);
    const offset = new Float32Array(PARTICLES);
    const jitter = new Float32Array(PARTICLES * 2);
    const rand = mulberry32(7);
    for (let i = 0; i < PARTICLES; i++) {
      lane[i] = i % MAX_LANES;
      seed[i] = rand();
      offset[i] = rand();
      jitter[i * 2] = (rand() - 0.5) * 2;
      jitter[i * 2 + 1] = (rand() - 0.5) * 2;
    }
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(PARTICLES * 3), 3));
    g.setAttribute("aLane", new THREE.BufferAttribute(lane, 1));
    g.setAttribute("aSeed", new THREE.BufferAttribute(seed, 1));
    g.setAttribute("aOffset", new THREE.BufferAttribute(offset, 1));
    g.setAttribute("aJitter", new THREE.BufferAttribute(jitter, 2));
    g.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 12);
    return g;
  }, []);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uNodes: { value: Array.from({ length: MAX_LANES }, () => new THREE.Vector3()) },
      uRate: { value: new Array(MAX_LANES).fill(0) },
      uErr: { value: new Array(MAX_LANES).fill(0) },
      uAgitation: { value: new Array(MAX_LANES).fill(0) },
      uErrColor: { value: Array.from({ length: MAX_LANES }, () => new THREE.Color(SEVERITY_HEX.MEDIUM)) },
      uColor: { value: new THREE.Color(SIGNAL_HEX) },
      uPixelRatio: { value: Math.min(gl.getPixelRatio(), 2) },
      uLanes: { value: 0 },
    }),
    [gl],
  );

  useEffect(() => () => geometry.dispose(), [geometry]);

  useFrame((_, delta) => {
    const u = material.current?.uniforms;
    if (!u) return;
    if (!reduced) u.uTime.value += Math.min(delta, 0.05);
    u.uLanes.value = nodes.length;
    nodes.forEach((n, i) => (u.uNodes.value[i] as THREE.Vector3).copy(n));
    const maxRps = Math.max(4, ...rows.current.map((r) => r.rps));
    rows.current.forEach((r, i) => {
      if (i >= MAX_LANES) return;
      u.uRate.value[i] = THREE.MathUtils.lerp(u.uRate.value[i], Math.min(1, r.rps / maxRps), 0.05);
      u.uErr.value[i] = THREE.MathUtils.lerp(u.uErr.value[i], r.err, 0.05);
      u.uAgitation.value[i] = THREE.MathUtils.lerp(u.uAgitation.value[i], r.agitation, 0.04);
      (u.uErrColor.value[i] as THREE.Color).set(r.severity ? SEVERITY_HEX[r.severity] : SEVERITY_HEX.MEDIUM);
    });
  });

  return (
    <points geometry={geometry} frustumCulled={false}>
      <shaderMaterial
        ref={material}
        vertexShader={laneVertex}
        fragmentShader={laneFragment}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}

// -- detection core -------------------------------------------------------------------

function Core({ pulsesRef, reduced }: { pulsesRef: React.MutableRefObject<Pulse[]>; reduced: boolean }) {
  const shell = useRef<THREE.LineSegments>(null);
  const inner = useRef<THREE.Mesh>(null);
  const glow = useRef<THREE.MeshBasicMaterial>(null);
  const edges = useMemo(() => new THREE.EdgesGeometry(new THREE.IcosahedronGeometry(0.72, 1)), []);
  const color = useMemo(() => new THREE.Color(SIGNAL_HEX), []);
  useEffect(() => () => edges.dispose(), [edges]);

  useFrame((state, delta) => {
    if (!reduced && shell.current) {
      shell.current.rotation.y += delta * 0.12;
      shell.current.rotation.x += delta * 0.04;
    }
    const now = Date.now();
    const recent = pulsesRef.current.filter((p) => now - p.at < 2500);
    const energy = recent.reduce((e, p) => e + (1 - (now - p.at) / 2500) * (p.severity === "CRITICAL" ? 1 : 0.6), 0);
    const target = recent.length ? SEVERITY_HEX[recent[recent.length - 1].severity] : SIGNAL_HEX;
    color.lerp(new THREE.Color(target), 0.05);
    if (inner.current) {
      const breathe = reduced ? 1 : 1 + Math.sin(state.clock.elapsedTime * 1.4) * 0.04;
      inner.current.scale.setScalar(breathe + Math.min(energy, 1.5) * 0.18);
    }
    if (glow.current) {
      glow.current.color.copy(color);
      glow.current.opacity = 0.16 + Math.min(energy, 1.5) * 0.18;
    }
    if (shell.current) (shell.current.material as THREE.LineBasicMaterial).color.copy(color);
  });

  return (
    <group>
      <lineSegments ref={shell} geometry={edges}>
        <lineBasicMaterial color={SIGNAL_HEX} transparent opacity={0.55} />
      </lineSegments>
      <mesh ref={inner}>
        <sphereGeometry args={[0.34, 32, 32]} />
        <meshBasicMaterial ref={glow} color={SIGNAL_HEX} transparent opacity={0.2} depthWrite={false} blending={THREE.AdditiveBlending} />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.16, 24, 24]} />
        <meshBasicMaterial color="#d9fff8" />
      </mesh>
    </group>
  );
}

// -- service nodes ----------------------------------------------------------------------

interface LaneData {
  name: string;
  rps: number;
  err: number;
  agitation: number;
  severity: Severity | null;
  tone: string;
}

function ServiceNode({
  position,
  data,
  index,
  rows,
  interactive,
  onSelect,
  hovered,
  setHovered,
}: {
  position: THREE.Vector3;
  data: LaneData;
  index: number;
  rows: React.MutableRefObject<LaneData[]>;
  interactive: boolean;
  onSelect?: (name: string) => void;
  hovered: boolean;
  setHovered: (name: string | null) => void;
}) {
  const ring = useRef<THREE.Mesh>(null);
  const ringMat = useRef<THREE.MeshBasicMaterial>(null);
  const body = useRef<THREE.Mesh>(null);
  const color = useMemo(() => new THREE.Color(data.tone), []); // eslint-disable-line react-hooks/exhaustive-deps

  useFrame((state) => {
    const live = rows.current[index];
    if (!live) return;
    color.lerp(new THREE.Color(live.tone), 0.08);
    if (ringMat.current) ringMat.current.color.copy(color);
    if (ring.current) {
      ring.current.lookAt(state.camera.position);
      const s = hovered ? 1.25 : 1;
      ring.current.scale.lerp(new THREE.Vector3(s, s, s), 0.15);
    }
    if (body.current) {
      const target = live.severity ? 1.15 + Math.sin(state.clock.elapsedTime * 4) * 0.06 : 1;
      body.current.scale.lerp(new THREE.Vector3(target, target, target), 0.1);
    }
  });

  const handlers = interactive
    ? {
        onPointerOver: (e: ThreeEvent<PointerEvent>) => {
          e.stopPropagation();
          setHovered(data.name);
          document.body.style.cursor = "pointer";
        },
        onPointerOut: () => {
          setHovered(null);
          document.body.style.cursor = "";
        },
        onClick: (e: ThreeEvent<MouseEvent>) => {
          e.stopPropagation();
          onSelect?.(data.name);
        },
      }
    : {};

  return (
    <group position={position}>
      {/* Generous invisible hit target: the visible node is small and moving. */}
      <mesh {...handlers}>
        <sphereGeometry args={[0.55, 12, 12]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>
      <mesh ref={body}>
        <sphereGeometry args={[0.2, 32, 32]} />
        <meshStandardMaterial color="#0e1622" emissive={data.tone} emissiveIntensity={0.35} roughness={0.35} metalness={0.6} />
      </mesh>
      <mesh ref={ring}>
        <ringGeometry args={[0.3, 0.325, 64]} />
        <meshBasicMaterial ref={ringMat} color={data.tone} transparent opacity={0.9} side={THREE.DoubleSide} />
      </mesh>
    </group>
  );
}

// -- anomaly shockwaves -----------------------------------------------------------------

const WAVE_POOL = 10;

function Shockwaves({ nodes, names, pulsesRef, reduced }: {
  nodes: THREE.Vector3[]; names: string[]; pulsesRef: React.MutableRefObject<Pulse[]>; reduced: boolean;
}) {
  const refs = useRef<(THREE.Mesh | null)[]>([]);
  useFrame((state) => {
    const now = Date.now();
    const live = pulsesRef.current.filter((p) => now - p.at < 2200).slice(-WAVE_POOL);
    refs.current.forEach((mesh, i) => {
      if (!mesh) return;
      const pulse = live[i];
      if (!pulse || reduced) {
        mesh.visible = false;
        return;
      }
      const idx = pulse.service ? names.indexOf(pulse.service) : -1;
      const origin = idx >= 0 ? nodes[idx] : CORE;
      const age = (now - pulse.at) / 2200;
      mesh.visible = true;
      mesh.position.copy(origin);
      mesh.lookAt(state.camera.position);
      const s = 0.4 + age * (pulse.severity === "CRITICAL" ? 3.2 : 2.2);
      mesh.scale.setScalar(s);
      const mat = mesh.material as THREE.MeshBasicMaterial;
      mat.color.set(SEVERITY_HEX[pulse.severity]);
      mat.opacity = (1 - age) * 0.7;
    });
  });
  return (
    <>
      {Array.from({ length: WAVE_POOL }, (_, i) => (
        <mesh key={i} ref={(m) => { refs.current[i] = m; }} visible={false}>
          <ringGeometry args={[0.48, 0.5, 64]} />
          <meshBasicMaterial transparent opacity={0} depthWrite={false} side={THREE.DoubleSide} blending={THREE.AdditiveBlending} />
        </mesh>
      ))}
    </>
  );
}

// -- dependency edges -----------------------------------------------------------------

function Dependencies({ nodes, names, deps }: { nodes: THREE.Vector3[]; names: string[]; deps: Record<string, string[]> }) {
  const geometry = useMemo(() => {
    const pts: number[] = [];
    names.forEach((name, i) => {
      for (const dep of deps[name] ?? []) {
        const j = names.indexOf(dep);
        if (j < 0) continue;
        const a = nodes[i];
        const b = nodes[j];
        const mid = a.clone().add(b).multiplyScalar(0.5);
        mid.y -= 0.9;
        const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
        const samples = curve.getPoints(32);
        for (let k = 0; k < samples.length - 1; k++) {
          pts.push(samples[k].x, samples[k].y, samples[k].z, samples[k + 1].x, samples[k + 1].y, samples[k + 1].z);
        }
      }
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    return g;
  }, [nodes, names, deps]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return (
    <lineSegments geometry={geometry}>
      <lineBasicMaterial color="#8ea3bf" transparent opacity={0.16} />
    </lineSegments>
  );
}

// -- ground ----------------------------------------------------------------------------

const groundFragment = /* glsl */ `
  varying vec2 vUv;
  uniform vec3 uColor;
  void main() {
    vec2 g = abs(fract(vUv * 40.0 - 0.5) - 0.5) / fwidth(vUv * 40.0);
    float line = 1.0 - min(min(g.x, g.y), 1.0);
    float fade = 1.0 - smoothstep(0.05, 0.5, length(vUv - 0.5));
    gl_FragColor = vec4(uColor, line * fade * 0.22);
  }
`;
const groundVertex = /* glsl */ `
  varying vec2 vUv;
  void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
`;

function Ground() {
  const uniforms = useMemo(() => ({ uColor: { value: new THREE.Color("#5c7a9c") } }), []);
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.7, 0]}>
      <planeGeometry args={[40, 40]} />
      <shaderMaterial vertexShader={groundVertex} fragmentShader={groundFragment} uniforms={uniforms} transparent depthWrite={false} />
    </mesh>
  );
}

// -- camera ----------------------------------------------------------------------------

const LANDING_KEYS: { at: number; pos: [number, number, number]; look: [number, number, number] }[] = [
  { at: 0.0, pos: [0.6, 3.4, 9.2], look: [0, -0.2, 0] },
  { at: 0.18, pos: [4.6, 1.2, 4.6], look: [1.6, 0, 0.8] },
  { at: 0.36, pos: [2.2, 0.6, 3.2], look: [0.6, 0.2, 0] },
  { at: 0.54, pos: [-1.6, 2.2, 3.6], look: [0, 0, 0] },
  { at: 0.72, pos: [0, 5.8, 5.4], look: [0, 0, 0] },
  { at: 1.0, pos: [0, 3.0, 8.0], look: [0, 0, 0] },
];

function sampleKeys(p: number) {
  let i = 0;
  while (i < LANDING_KEYS.length - 2 && p > LANDING_KEYS[i + 1].at) i++;
  const a = LANDING_KEYS[i];
  const b = LANDING_KEYS[i + 1];
  const t = THREE.MathUtils.smootherstep(p, a.at, b.at);
  return {
    pos: new THREE.Vector3(...a.pos).lerp(new THREE.Vector3(...b.pos), t),
    look: new THREE.Vector3(...a.look).lerp(new THREE.Vector3(...b.look), t),
  };
}

function CameraRig({ mode, progress, focusPos, reduced }: {
  mode: SceneMode; progress?: MotionValue<number>; focusPos: THREE.Vector3 | null; reduced: boolean;
}) {
  const look = useRef(new THREE.Vector3());
  const pointer = useRef(new THREE.Vector2());
  const { camera } = useThree();

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      pointer.current.set((e.clientX / window.innerWidth) * 2 - 1, (e.clientY / window.innerHeight) * 2 - 1);
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, []);

  useFrame((state) => {
    let pos: THREE.Vector3;
    let target: THREE.Vector3;
    if (focusPos) {
      const out = focusPos.clone().setY(0).normalize();
      pos = focusPos.clone().add(out.multiplyScalar(2.2)).add(new THREE.Vector3(0, 0.9, 0));
      target = focusPos.clone();
    } else if (mode === "landing" && progress) {
      const k = sampleKeys(progress.get());
      pos = k.pos;
      target = k.look;
    } else {
      const t = reduced ? 0 : state.clock.elapsedTime * 0.05;
      // Portrait panels need a longer lens distance to keep the whole ring in view.
      const aspect = state.size.width / Math.max(1, state.size.height);
      const fit = Math.min(2.2, Math.max(1, 1.45 / aspect));
      const r = (mode === "map" ? 8.6 : 9.4) * fit;
      pos = new THREE.Vector3(Math.sin(t) * r * 0.35, (mode === "map" ? 4.6 : 3.9) * fit, Math.cos(t) * r);
      target = new THREE.Vector3(0, -0.2, 0);
    }
    if (!reduced) {
      pos.x += pointer.current.x * 0.35;
      pos.y += -pointer.current.y * 0.2;
    }
    camera.position.lerp(pos, reduced ? 1 : 0.045);
    look.current.lerp(target, reduced ? 1 : 0.06);
    camera.lookAt(look.current);
  });
  return null;
}

// -- scene root ------------------------------------------------------------------------

function toLaneData(row: ServiceRow | undefined, name: string, synthetic: boolean, t: number): LaneData {
  if (!row || synthetic) {
    const wobble = 0.6 + 0.4 * Math.sin(t * 0.3 + name.length);
    return { name, rps: IDLE.rps * wobble, err: IDLE.err, agitation: 0, severity: null, tone: SIGNAL_HEX };
  }
  const tone = TONE_HEX[serviceTone(row)];
  const severity = row.worst_severity;
  const agitation = severity === "CRITICAL" ? 1 : severity === "HIGH" ? 0.7 : severity === "MEDIUM" ? 0.4 : severity ? 0.2 : 0;
  return { name, rps: row.requests_per_second, err: row.error_rate, agitation, severity, tone };
}

export function sceneNames(services: Record<string, ServiceRow>): string[] {
  const known = Object.keys(services);
  return (known.length ? known : DEFAULT_SERVICES).slice(0, MAX_LANES);
}

type LabelRefs = React.MutableRefObject<Record<string, HTMLDivElement | null>>;

function SceneContents({ mode, progress, focus, onSelect, reducedMotion, labelRefs }: Omit<TelemetrySceneProps, "active"> & { labelRefs: LabelRefs }) {
  const services = useLive((s) => s.services);
  const hydrated = useLive((s) => s.hydrated);
  const names = useMemo(() => sceneNames(services), [services]);
  const deps = useMemo(() => {
    const out: Record<string, string[]> = {};
    for (const [name, row] of Object.entries(services)) out[name] = row.depends_on ?? [];
    return out;
  }, [services]);
  const nodes = useMemo(() => nodePositions(names.length, mode), [names.length, mode]);

  const synthetic = !hydrated;
  const rows = useRef<LaneData[]>(names.map((n) => toLaneData(services[n], n, synthetic, 0)));
  const pulsesRef = useRef<Pulse[]>([]);
  const [hovered, setHovered] = useState<string | null>(null);
  const [tones, setTones] = useState<LaneData[]>(() => names.map((n) => toLaneData(services[n], n, synthetic, 0)));
  const projected = useMemo(() => new THREE.Vector3(), []);
  const showLabels = mode !== "landing" && !focus;

  useFrame((state) => {
    const live = useLive.getState();
    rows.current = names.map((n) => toLaneData(live.services[n], n, synthetic, state.clock.elapsedTime));
    pulsesRef.current = live.pulses;
    // Labels are plain DOM positioned from here: no per-label React roots.
    const { width, height } = state.size;
    names.forEach((name, i) => {
      const el = labelRefs.current[name];
      if (!el) return;
      projected.copy(nodes[i]).setY(nodes[i].y - 0.55).project(state.camera);
      const visible = showLabels && projected.z < 1;
      el.style.opacity = visible ? "1" : "0";
      el.style.transform = `translate(-50%, 0) translate(${(projected.x * 0.5 + 0.5) * width}px, ${(-projected.y * 0.5 + 0.5) * height}px)`;
      el.dataset.hover = hovered === name ? "1" : "0";
    });
  });

  // Node colours are material props: refresh at a human rate, not per frame.
  useEffect(() => {
    const id = window.setInterval(() => setTones(rows.current.slice()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const focusIndex = focus ? names.indexOf(focus) : -1;
  const focusPos = focusIndex >= 0 ? nodes[focusIndex] : null;

  return (
    <>
      <color attach="background" args={["#05080d"]} />
      <fog attach="fog" args={["#05080d", 9, 22]} />
      <ambientLight intensity={0.4} />
      <pointLight position={[0, 3, 0]} intensity={18} color={SIGNAL_HEX} distance={12} />
      <CameraRig mode={mode} progress={progress} focusPos={focusPos} reduced={reducedMotion} />
      <Ground />
      <Core pulsesRef={pulsesRef} reduced={reducedMotion} />
      <Dependencies nodes={nodes} names={names} deps={deps} />
      <Lanes nodes={nodes} rows={rows} reduced={reducedMotion} />
      <Shockwaves nodes={nodes} names={names} pulsesRef={pulsesRef} reduced={reducedMotion} />
      {names.map((name, i) => (
        <ServiceNode
          key={name}
          position={nodes[i]}
          index={i}
          rows={rows}
          data={tones[i] ?? toLaneData(services[name], name, synthetic, 0)}
          interactive={mode !== "landing" && !!onSelect}
          onSelect={onSelect}
          hovered={hovered === name || focus === name}
          setHovered={setHovered}
        />
      ))}
    </>
  );
}

/**
 * Map pointers from the canvas's live on-screen rect. The default mapping
 * divides offsetX by a cached size, which goes stale while the page is still
 * animating in and makes nodes unclickable.
 */
const pointerEvents = (store: Parameters<typeof createEvents>[0]) => ({
  ...createEvents(store),
  compute(event: DomEvent, state: RootState) {
    const rect = state.gl.domElement.getBoundingClientRect();
    state.pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    state.raycaster.setFromCamera(state.pointer, state.camera);
  },
});

function LabelLayer({ labelRefs, hidden }: { labelRefs: LabelRefs; hidden: boolean }) {
  const services = useLive((s) => s.services);
  if (hidden) return null;
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
      {sceneNames(services).map((name) => {
        const row = services[name];
        return (
          <div
            key={name}
            ref={(el) => { labelRefs.current[name] = el; }}
            className="group absolute left-0 top-0 whitespace-nowrap text-center opacity-0 transition-opacity duration-300"
          >
            <p className="text-[12px] font-medium tracking-tight text-fg-muted group-data-[hover=1]:text-fg">{row?.label ?? serviceLabel(name)}</p>
            <p className="font-mono text-[10.5px]" style={{ color: row?.worst_severity ? SEVERITY_HEX[row.worst_severity] : "#627085" }}>
              {row ? `${pct(row.error_rate)} err` : ""}
            </p>
          </div>
        );
      })}
    </div>
  );
}

export default function TelemetryScene({ active, reducedMotion, ...props }: TelemetrySceneProps) {
  const labelRefs = useRef<Record<string, HTMLDivElement | null>>({});
  useEffect(() => () => { document.body.style.cursor = ""; }, []);
  return (
    <div className="relative h-full w-full">
      <Canvas
        frameloop={active ? (reducedMotion ? "demand" : "always") : "never"}
        dpr={[1, 1.75]}
        camera={{ position: [0.6, 3.4, 9.2], fov: 42, near: 0.1, far: 60 }}
        gl={{ antialias: true, alpha: false, powerPreference: "high-performance" }}
        aria-label="Live telemetry: services streaming log events into the detection core"
        role="img"
        events={pointerEvents}
      >
        <SceneContents reducedMotion={reducedMotion} labelRefs={labelRefs} {...props} />
      </Canvas>
      <LabelLayer labelRefs={labelRefs} hidden={props.mode === "landing"} />
    </div>
  );
}

function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

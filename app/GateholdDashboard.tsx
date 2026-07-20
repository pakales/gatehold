"use client";

import {
  Activity,
  ArrowRight,
  Check,
  CircleDot,
  Cpu,
  Gauge,
  HardDrive,
  LockKeyhole,
  MemoryStick,
  Pause,
  Play,
  Radio,
  RefreshCw,
  ShieldCheck,
  Unplug,
  Users,
  X,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const DAEMON_ORIGIN = "http://127.0.0.1:47820";
const DEMO_STEP_MS = 2800;

type KeyState = "pass" | "hold" | "idle";
type Tone = "mint" | "amber" | "coral" | "neutral";
type LiveState = "replay" | "checking" | "live" | "blocked" | "offline";

type Lane = {
  id: string;
  agent: string;
  task: string;
  scope: string;
  status:
    | "CLEARED"
    | "RUNNING"
    | "SEMANTIC HOLD"
    | "CAPACITY HOLD"
    | "QUEUED"
    | "STANDBY"
    | "RELEASED";
  tone: Tone;
  weight: "light" | "heavy";
  workstream: { state: KeyState; label: string };
  capacity: { state: KeyState; label: string };
  note: string;
};

type HostSnapshot = {
  cpu: number;
  ram: number;
  heavyActive: number;
  heavyLimit: number;
  activeLeases: number;
  queue: number;
};

type DemoScene = {
  id: string;
  step: string;
  shortLabel: string;
  title: string;
  summary: string;
  verdict: "CLEARED" | "HOLD" | "RELEASED";
  verdictTone: Tone;
  focusLaneIndex: number;
  host: HostSnapshot;
  lanes: readonly Lane[];
  events: readonly {
    id: string;
    time: string;
    tone: Tone;
    title: string;
    detail: string;
  }[];
};

type LocalDaemonSnapshot = {
  host?: {
    cpu_percent?: number;
    memory_percent?: number;
    pressure_ok?: boolean;
  };
  capacity?: {
    heavy_active?: number;
    heavy_limit?: number;
    heavy_available?: number;
  };
  active_leases?: unknown[];
  queue?: unknown[];
};

const demoScenes: readonly DemoScene[] = [
  {
    id: "scene-a-cleared",
    step: "A",
    shortLabel: "Clean admit",
    title: "Auth refresh gets both keys",
    summary:
      "Agent 07 owns auth/session and the host has room. The task enters an isolated runtime lane.",
    verdict: "CLEARED",
    verdictTone: "mint",
    focusLaneIndex: 0,
    host: {
      cpu: 38,
      ram: 52,
      heavyActive: 1,
      heavyLimit: 2,
      activeLeases: 2,
      queue: 0,
    },
    lanes: [
      {
        id: "lane-07",
        agent: "Agent 07",
        task: "Repair token refresh",
        scope: "auth/session · lane-07 · :49157",
        status: "RUNNING",
        tone: "mint",
        weight: "heavy",
        workstream: { state: "pass", label: "Owner locked" },
        capacity: { state: "pass", label: "Headroom" },
        note: "Lease renews every 20s",
      },
      {
        id: "lane-12",
        agent: "Agent 12",
        task: "Billing receipt tests",
        scope: "billing/receipts · lane-12 · :49158",
        status: "CLEARED",
        tone: "mint",
        weight: "light",
        workstream: { state: "pass", label: "Independent" },
        capacity: { state: "pass", label: "Headroom" },
        note: "Isolated browser profile",
      },
      {
        id: "lane-18",
        agent: "Agent 18",
        task: "iOS archive",
        scope: "mobile/release · ready",
        status: "STANDBY",
        tone: "neutral",
        weight: "heavy",
        workstream: { state: "pass", label: "Independent" },
        capacity: { state: "idle", label: "Not requested" },
        note: "Heavy request not submitted",
      },
    ],
    events: [
      {
        id: "a-1",
        time: "09:41:02",
        tone: "neutral",
        title: "Clearance requested",
        detail: "Agent 07 · auth/session",
      },
      {
        id: "a-2",
        time: "09:41:03",
        tone: "mint",
        title: "Workstream locked",
        detail: "lease gh_07b2 · TTL 60s",
      },
      {
        id: "a-3",
        time: "09:41:03",
        tone: "mint",
        title: "Runtime admitted",
        detail: "lane-07 · port 49157",
      },
    ],
  },
  {
    id: "scene-b-semantic-hold",
    step: "B",
    shortLabel: "Semantic hold",
    title: "Different words. Same workstream.",
    summary:
      "Agent 18 asks to “harden session renewal.” GPT-5.6 raises a conservative review hold; deterministic policy remains authoritative.",
    verdict: "HOLD",
    verdictTone: "coral",
    focusLaneIndex: 1,
    host: {
      cpu: 44,
      ram: 56,
      heavyActive: 1,
      heavyLimit: 2,
      activeLeases: 2,
      queue: 1,
    },
    lanes: [
      {
        id: "lane-07",
        agent: "Agent 07",
        task: "Repair token refresh",
        scope: "auth/session · lane-07 · :49157",
        status: "RUNNING",
        tone: "mint",
        weight: "heavy",
        workstream: { state: "pass", label: "Owner locked" },
        capacity: { state: "pass", label: "Headroom" },
        note: "Authoritative lease owner",
      },
      {
        id: "lane-18",
        agent: "Agent 18",
        task: "Harden session renewal",
        scope: "identity/session · pending",
        status: "SEMANTIC HOLD",
        tone: "coral",
        weight: "light",
        workstream: { state: "hold", label: "Overlap" },
        capacity: { state: "pass", label: "Headroom" },
        note: "Meaning overlaps auth/session",
      },
      {
        id: "lane-12",
        agent: "Agent 12",
        task: "Billing receipt tests",
        scope: "billing/receipts · lane-12 · :49158",
        status: "CLEARED",
        tone: "mint",
        weight: "light",
        workstream: { state: "pass", label: "Independent" },
        capacity: { state: "pass", label: "Headroom" },
        note: "Unrelated work continues",
      },
    ],
    events: [
      {
        id: "b-1",
        time: "09:42:11",
        tone: "neutral",
        title: "Agent 18 requested",
        detail: "“Harden session renewal”",
      },
      {
        id: "b-2",
        time: "09:42:12",
        tone: "amber",
        title: "Semantic overlap raised",
        detail: "GPT-5.6 · bounded classifier",
      },
      {
        id: "b-3",
        time: "09:42:12",
        tone: "coral",
        title: "Workstream hold",
        detail: "Existing lease remains authoritative",
      },
    ],
  },
  {
    id: "scene-c-capacity-hold",
    step: "C",
    shortLabel: "Capacity hold",
    title: "Independent task. Host is full.",
    summary:
      "The archive does not overlap, but memory pressure is high and both heavy slots are occupied. It waits in FIFO order.",
    verdict: "HOLD",
    verdictTone: "amber",
    focusLaneIndex: 2,
    host: {
      cpu: 86,
      ram: 91,
      heavyActive: 2,
      heavyLimit: 2,
      activeLeases: 3,
      queue: 2,
    },
    lanes: [
      {
        id: "lane-07",
        agent: "Agent 07",
        task: "Repair token refresh",
        scope: "auth/session · lane-07 · :49157",
        status: "RUNNING",
        tone: "mint",
        weight: "heavy",
        workstream: { state: "pass", label: "Owner locked" },
        capacity: { state: "pass", label: "Admitted" },
        note: "Cooperative task stays active",
      },
      {
        id: "lane-12",
        agent: "Agent 12",
        task: "Web integration suite",
        scope: "web/verify · lane-12 · :49158",
        status: "RUNNING",
        tone: "mint",
        weight: "heavy",
        workstream: { state: "pass", label: "Independent" },
        capacity: { state: "pass", label: "Slot 2 of 2" },
        note: "Gatehold never kills it",
      },
      {
        id: "lane-18",
        agent: "Agent 18",
        task: "iOS release archive",
        scope: "mobile/release · queued",
        status: "CAPACITY HOLD",
        tone: "amber",
        weight: "heavy",
        workstream: { state: "pass", label: "Independent" },
        capacity: { state: "hold", label: "Host full" },
        note: "FIFO position 01",
      },
    ],
    events: [
      {
        id: "c-1",
        time: "09:44:07",
        tone: "mint",
        title: "Workstream clear",
        detail: "mobile/release is independent",
      },
      {
        id: "c-2",
        time: "09:44:07",
        tone: "amber",
        title: "Capacity key withheld",
        detail: "RAM 91% · heavy slots 2/2",
      },
      {
        id: "c-3",
        time: "09:44:08",
        tone: "neutral",
        title: "Queued safely",
        detail: "Agent 18 · FIFO 01",
      },
    ],
  },
  {
    id: "scene-d-release",
    step: "D",
    shortLabel: "Clean finish",
    title: "Cleanup clears the next lane",
    summary:
      "Agent 12 finishes and returns its heavy slot. Gatehold later cleans only an exact runtime it booted and confirmed; prebooted human simulators stay untouched.",
    verdict: "RELEASED",
    verdictTone: "mint",
    focusLaneIndex: 1,
    host: {
      cpu: 61,
      ram: 68,
      heavyActive: 2,
      heavyLimit: 2,
      activeLeases: 3,
      queue: 1,
    },
    lanes: [
      {
        id: "lane-07",
        agent: "Agent 07",
        task: "Repair token refresh",
        scope: "auth/session · lane-07 · :49157",
        status: "RUNNING",
        tone: "mint",
        weight: "heavy",
        workstream: { state: "pass", label: "Owner locked" },
        capacity: { state: "pass", label: "Admitted" },
        note: "No interruption",
      },
      {
        id: "lane-12",
        agent: "Agent 12",
        task: "Web integration suite",
        scope: "web/verify · receipt 8f3a",
        status: "RELEASED",
        tone: "neutral",
        weight: "heavy",
        workstream: { state: "idle", label: "Cleanup verified" },
        capacity: { state: "idle", label: "Slot returned" },
        note: "Owned process group + port cleaned",
      },
      {
        id: "lane-18",
        agent: "Agent 18",
        task: "iOS release archive",
        scope: "mobile/release · lane-18 · sim-02",
        status: "RUNNING",
        tone: "mint",
        weight: "heavy",
        workstream: { state: "pass", label: "Owner locked" },
        capacity: { state: "pass", label: "Slot admitted" },
        note: "Exact sim-02 boot only · human simulator untouched",
      },
    ],
    events: [
      {
        id: "d-1",
        time: "09:45:30",
        tone: "mint",
        title: "Owned cleanup verified",
        detail: "process group · :49158 · profile",
      },
      {
        id: "d-2",
        time: "09:45:31",
        tone: "neutral",
        title: "Heavy slot returned",
        detail: "Agent 12 · receipt 8f3a",
      },
      {
        id: "d-3",
        time: "09:45:31",
        tone: "mint",
        title: "Next task admitted",
        detail: "mobile/release · exact owned sim-02",
      },
    ],
  },
];

const liveCopy: Record<LiveState, { label: string; description: string }> = {
  replay: { label: "Replay", description: "Bounded demo · works offline" },
  checking: {
    label: "Checking",
    description: "Looking only at 127.0.0.1",
  },
  live: { label: "Live", description: "Read-only daemon snapshot" },
  blocked: {
    label: "Blocked",
    description: "Private loopback mode only",
  },
  offline: {
    label: "Offline",
    description: "Local daemon unavailable · replay active",
  },
};

const boundaryCopy: Record<LiveState, { title: string; detail: string }> = {
  replay: {
    title: "REPLAY HOST METRICS · REPLAY SCENARIO",
    detail: "Bounded demo data.",
  },
  checking: {
    title: "CHECKING LOCAL HOST · REPLAY SCENARIO",
    detail: "Agent lanes and events remain deterministic replay.",
  },
  live: {
    title: "LIVE HOST METRICS · REPLAY SCENARIO",
    detail: "Only host metrics and counts are live; A–D lanes and events remain replay.",
  },
  blocked: {
    title: "LOCAL ACCESS BLOCKED · REPLAY SCENARIO",
    detail:
      "Use the documented loopback operator URL and allowlist its exact origin.",
  },
  offline: {
    title: "LOCAL HOST OFFLINE · REPLAY SCENARIO",
    detail: "The bounded A–D demo remains fully available.",
  },
};

const footerCopy: Record<LiveState, string> = {
  replay:
    "REPLAY ONLY · Host metrics, A–D lanes, and events are bounded demo data.",
  checking:
    "CHECKING LOCAL HOST · A–D lanes and events remain bounded replay data.",
  live:
    "LIVE HOST METRICS · A–D lanes and events remain bounded replay data.",
  blocked:
    "LOCAL MODE OFF · A–D replay remains active; private access requires the documented loopback URL and exact-origin allowlist.",
  offline:
    "LOCAL HOST OFFLINE · A–D replay remains active with bounded demo data.",
};

function clampMetric(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(0, Math.min(100, Math.round(value)))
    : fallback;
}

function isLocalOperatorSurface(): boolean {
  const currentUrl = new URL(window.location.href);
  const isLoopback =
    currentUrl.hostname === "127.0.0.1" ||
    currentUrl.hostname === "localhost" ||
    currentUrl.hostname === "[::1]";
  return (
    currentUrl.protocol === "http:" &&
    isLoopback &&
    currentUrl.searchParams.get("local") === "1"
  );
}

function StatusMark({ state }: { state: KeyState }) {
  if (state === "pass") return <Check aria-hidden="true" size={13} />;
  if (state === "hold") return <X aria-hidden="true" size={13} />;
  return <Pause aria-hidden="true" size={12} />;
}

function ClearanceCell({
  kind,
  clearance,
}: {
  kind: "Workstream" | "Capacity";
  clearance: Lane["workstream"];
}) {
  return (
    <div className={`clearance-cell key-${clearance.state}`}>
      <span className="clearance-icon">
        <StatusMark state={clearance.state} />
      </span>
      <span>
        <small>{kind} key</small>
        <strong>{clearance.label}</strong>
      </span>
    </div>
  );
}

function DecisionKey({
  kind,
  clearance,
}: {
  kind: string;
  clearance: Lane["workstream"];
}) {
  return (
    <span className={`decision-key key-${clearance.state}`}>
      <span className="decision-key-icon">
        <StatusMark state={clearance.state} />
      </span>
      <span>
        <small>{kind}</small>
        <strong>{clearance.label}</strong>
      </span>
    </span>
  );
}

function Metric({
  label,
  value,
  detail,
  icon,
  warning,
  progress,
}: {
  label: string;
  value: string;
  detail: string;
  icon: React.ReactNode;
  warning?: boolean;
  progress?: number;
}) {
  return (
    <div className={`metric${warning ? " metric-warning" : ""}`}>
      <div className="metric-icon">{icon}</div>
      <div className="metric-copy">
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
      {typeof progress === "number" ? (
        <span
          className="metric-meter"
          role="progressbar"
          aria-label={`${label} ${value}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress}
        >
          <span style={{ width: `${progress}%` }} />
        </span>
      ) : null}
    </div>
  );
}

export function GateholdDashboard() {
  const [sceneIndex, setSceneIndex] = useState(1);
  const [isRunning, setIsRunning] = useState(false);
  const [liveState, setLiveState] = useState<LiveState>("replay");
  const [localSnapshot, setLocalSnapshot] =
    useState<LocalDaemonSnapshot | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const scene = demoScenes[sceneIndex];
  const focusLane = scene.lanes[scene.focusLaneIndex] ?? scene.lanes[0];
  const modeCopy = liveCopy[liveState];
  const sourceBoundary = boundaryCopy[liveState];
  const isLiveHost = liveState === "live";

  const displayHost = useMemo<HostSnapshot>(() => {
    if (liveState !== "live" || !localSnapshot) return scene.host;
    return {
      cpu: clampMetric(localSnapshot.host?.cpu_percent, scene.host.cpu),
      ram: clampMetric(localSnapshot.host?.memory_percent, scene.host.ram),
      heavyActive:
        localSnapshot.capacity?.heavy_active ?? scene.host.heavyActive,
      heavyLimit: localSnapshot.capacity?.heavy_limit ?? scene.host.heavyLimit,
      activeLeases: Array.isArray(localSnapshot.active_leases)
        ? localSnapshot.active_leases.length
        : scene.host.activeLeases,
      queue: Array.isArray(localSnapshot.queue)
        ? localSnapshot.queue.length
        : scene.host.queue,
    };
  }, [liveState, localSnapshot, scene.host]);

  const refreshLocalSnapshot = useCallback(async () => {
    const response = await fetch(`${DAEMON_ORIGIN}/v1/snapshot`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      credentials: "omit",
    });
    if (response.status === 401 || response.status === 403) {
      setLiveState("blocked");
      return false;
    }
    if (!response.ok) throw new Error(`Snapshot returned ${response.status}`);
    setLocalSnapshot((await response.json()) as LocalDaemonSnapshot);
    setLiveState("live");
    return true;
  }, []);

  const connectLocal = useCallback(async () => {
    if (liveState === "checking") return;
    if (!isLocalOperatorSurface()) {
      setLocalSnapshot(null);
      setLiveState("blocked");
      return;
    }
    setLiveState("checking");
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 1800);
    try {
      let health: Response;
      try {
        health = await fetch(`${DAEMON_ORIGIN}/healthz`, {
          cache: "no-store",
          headers: { Accept: "application/json" },
          credentials: "omit",
          signal: controller.signal,
        });
      } catch {
        setLocalSnapshot(null);
        setLiveState("offline");
        return;
      }
      if (health.status === 401 || health.status === 403) {
        setLocalSnapshot(null);
        setLiveState("blocked");
        return;
      }
      if (!health.ok) {
        setLocalSnapshot(null);
        setLiveState("offline");
        return;
      }
      try {
        await refreshLocalSnapshot();
      } catch {
        setLocalSnapshot(null);
        setLiveState("offline");
      }
    } finally {
      window.clearTimeout(timeout);
    }
  }, [liveState, refreshLocalSnapshot]);

  useEffect(() => {
    if (!isRunning) return;
    let nextScene = 0;
    const interval = window.setInterval(() => {
      nextScene += 1;
      setSceneIndex(nextScene);
      if (nextScene === demoScenes.length - 1) {
        window.clearInterval(interval);
        setIsRunning(false);
      }
    }, DEMO_STEP_MS);
    return () => window.clearInterval(interval);
  }, [isRunning]);

  useEffect(() => {
    if (liveState !== "live") {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      return;
    }
    const events = new EventSource(`${DAEMON_ORIGIN}/v1/events`, {
      withCredentials: false,
    });
    eventSourceRef.current = events;
    const refreshFromEvent = () => {
      void refreshLocalSnapshot().catch(() => setLiveState("offline"));
    };
    const eventKinds = [
      "request.queued",
      "request.waiting",
      "request.deterministic_hold",
      "request.semantic_hold",
      "lease.granted",
      "lease.heartbeat",
      "lease.released",
      "lease.expired",
    ];
    for (const eventKind of eventKinds) {
      events.addEventListener(eventKind, refreshFromEvent);
    }
    const fallbackRefresh = window.setInterval(refreshFromEvent, 10_000);
    return () => {
      window.clearInterval(fallbackRefresh);
      for (const eventKind of eventKinds) {
        events.removeEventListener(eventKind, refreshFromEvent);
      }
      events.close();
      eventSourceRef.current = null;
    };
  }, [liveState, refreshLocalSnapshot]);

  function runDemo() {
    setSceneIndex(0);
    setIsRunning(true);
  }

  function selectScene(index: number) {
    setIsRunning(false);
    setSceneIndex(index);
  }

  return (
    <main
      className={`gatehold-shell${isRunning ? " demo-running" : ""}`}
    >
      <div className="ambient-grid" aria-hidden="true" />
      <header className="topbar">
        <a className="brand" href="#control-deck" aria-label="Gatehold home">
          <span className="brand-mark" aria-hidden="true">
            <span />
          </span>
          <span className="brand-copy">
            <strong>GATEHOLD</strong>
            <small>Every agent needs clearance.</small>
          </span>
        </a>
        <div className="mode-cluster" aria-live="polite">
          <span className={`mode-pulse mode-${liveState}`} aria-hidden="true" />
          <span>
            <strong>{modeCopy.label}</strong>
            <small>{modeCopy.description}</small>
          </span>
        </div>
        <div className="header-actions">
          <button
            className="button button-primary"
            type="button"
            onClick={runDemo}
            disabled={isRunning}
          >
            {isRunning ? (
              <Activity aria-hidden="true" size={16} />
            ) : (
              <Play aria-hidden="true" size={16} fill="currentColor" />
            )}
            <span className="button-label-full">
              {isRunning ? "Playing clearance…" : "Play 4-step demo"}
            </span>
            <span className="button-label-short">
              {isRunning ? "Playing…" : "Play demo"}
            </span>
          </button>
        </div>
      </header>

      <section
        className={`hero-stage hero-${scene.verdictTone}`}
        aria-labelledby="control-deck"
      >
        <div className="intro">
          <p className="eyebrow">
            <CircleDot aria-hidden="true" size={13} />
            Local clearance for parallel coding agents
          </p>
          <h1 id="control-deck">
            <span className="headline-main">One machine.</span>
            <span className="headline-main">Many agents.</span>
            <span className="headline-accent">One clearance layer.</span>
          </h1>
          <div className="intro-note">
            <strong className="product-contract">
              Two keys to start. Verified cleanup to release.
            </strong>
            <p>
              Gatehold blocks overlapping work, queues heavy jobs when the host
              is full, and releases a lane only after owned cleanup is verified.
            </p>
            <div className="authority-rule">
              <ShieldCheck aria-hidden="true" size={17} />
              <span>
                <strong>Deterministic policy grants clearance.</strong>
                <small>
                  {
                    "GPT-5.6 can only add a hold. It never grants clearance or overrides deterministic policy."
                  }
                </small>
              </span>
            </div>
          </div>
        </div>

        <section
          className={`decision-deck decision-${scene.verdictTone}`}
          aria-live="polite"
          aria-atomic="true"
        >
          <div className="decision-signal">
            <span>Clearance decision · Scene {scene.step}</span>
            <strong>{scene.verdict}</strong>
          </div>
          <div className="decision-copy">
            <span className="decision-agent">
              {focusLane.agent} · {focusLane.weight} lane
            </span>
            <h2>{scene.title}</h2>
            <p>{scene.summary}</p>
          </div>
          <div className="decision-contract" aria-label="Gatehold two-key rule">
            <DecisionKey
              kind={
                scene.verdict === "RELEASED"
                  ? "Cleanup receipt"
                  : "Workstream key"
              }
              clearance={focusLane.workstream}
            />
            <DecisionKey
              kind={
                scene.verdict === "RELEASED"
                  ? "Capacity return"
                  : "Capacity key"
              }
              clearance={focusLane.capacity}
            />
          </div>
        </section>

        <section className="scenario-console" aria-label="Demo controls">
          <div className="source-rail">
            <div
              className={`source-boundary source-boundary-${liveState}`}
              role="status"
              aria-live="polite"
            >
              <Radio aria-hidden="true" size={13} />
              <strong>{sourceBoundary.title}</strong>
              <span>{sourceBoundary.detail}</span>
            </div>
            <button
              className="local-mode-control"
              type="button"
              onClick={() => void connectLocal()}
              disabled={liveState === "checking"}
              aria-label={
                liveState === "live"
                  ? "Refresh private local daemon"
                  : "Check private local daemon"
              }
              title="Private loopback mode requires ?local=1 and an exact-origin allowlist"
            >
              {liveState === "checking" ? (
                <RefreshCw aria-hidden="true" size={14} className="spin" />
              ) : liveState === "live" ? (
                <Radio aria-hidden="true" size={14} />
              ) : (
                <Unplug aria-hidden="true" size={14} />
              )}
              <span>{liveState === "live" ? "Refresh local" : "Local mode"}</span>
            </button>
          </div>

          <nav className="scene-switcher" aria-label="Collision demo scenes">
            {demoScenes.map((demoScene, index) => (
              <button
                key={demoScene.id}
                type="button"
                className={`${index === sceneIndex ? "scene-active " : ""}scene-${demoScene.verdictTone}`}
                aria-current={index === sceneIndex ? "step" : undefined}
                aria-label={`Scene ${demoScene.step}: ${demoScene.shortLabel}`}
                onClick={() => selectScene(index)}
              >
                <span>{demoScene.step}</span>
                <strong>{demoScene.shortLabel}</strong>
              </button>
            ))}
          </nav>
        </section>
      </section>

      <section
        className="metric-strip"
        aria-label={`${isLiveHost ? "Live" : "Replay"} Host Core metrics`}
      >
        <Metric
          label="CPU load"
          value={`${displayHost.cpu}%`}
          detail={displayHost.cpu >= 80 ? "Pressure high" : "Inside policy"}
          icon={<Cpu aria-hidden="true" size={17} />}
          warning={displayHost.cpu >= 80}
          progress={displayHost.cpu}
        />
        <Metric
          label="Memory"
          value={`${displayHost.ram}%`}
          detail={displayHost.ram >= 85 ? "Admission paused" : "Headroom ready"}
          icon={<MemoryStick aria-hidden="true" size={17} />}
          warning={displayHost.ram >= 85}
          progress={displayHost.ram}
        />
        <Metric
          label="Heavy lanes"
          value={`${displayHost.heavyActive} / ${displayHost.heavyLimit}`}
          detail={
            displayHost.heavyActive >= displayHost.heavyLimit
              ? "Capacity full"
              : "Slot available"
          }
          icon={<Zap aria-hidden="true" size={17} />}
          warning={displayHost.heavyActive >= displayHost.heavyLimit}
        />
        <Metric
          label="Active leases"
          value={`${displayHost.activeLeases}`}
          detail={`${displayHost.queue} waiting`}
          icon={<LockKeyhole aria-hidden="true" size={17} />}
        />
      </section>

      <section className="control-grid">
        <section className="lanes-column" aria-labelledby="agent-lanes-title">
          <div className="section-heading">
            <div>
              <p className="panel-kicker">Bounded A–D scenario</p>
              <h2 id="agent-lanes-title">Agent clearance lanes</h2>
            </div>
            <span className="section-count">
              {scene.lanes.length} replay lanes
            </span>
          </div>
          <div className="lane-list">
            {scene.lanes.map((lane, index) => (
              <article
                className={`lane-card lane-${lane.tone}${
                  index === scene.focusLaneIndex ? " lane-focus" : ""
                }`}
                key={`${scene.id}-${lane.id}`}
              >
                <div className="lane-index" aria-hidden="true">
                  {String(index + 1).padStart(2, "0")}
                </div>
                <div className="lane-main">
                  <div className="lane-title-row">
                    <div>
                      <span className="agent-name">{lane.agent}</span>
                      <h3>{lane.task}</h3>
                    </div>
                    <span
                      className={`lane-status status-${lane.tone}`}
                      aria-label={`${lane.agent} status ${lane.status}`}
                    >
                      {lane.status}
                    </span>
                  </div>
                  <p className="lane-scope">
                    <HardDrive aria-hidden="true" size={13} />
                    {lane.scope}
                    <span>{lane.weight}</span>
                  </p>
                  <div className="clearance-grid">
                    <ClearanceCell
                      kind="Workstream"
                      clearance={lane.workstream}
                    />
                    <ClearanceCell kind="Capacity" clearance={lane.capacity} />
                  </div>
                  <p className="lane-note">{lane.note}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <aside className="panel event-panel" aria-labelledby="event-rail-title">
          <div className="panel-heading">
            <div>
              <p className="panel-kicker">Bounded scenario signals</p>
              <h2 id="event-rail-title">Decision trace</h2>
            </div>
            <Activity aria-hidden="true" size={18} />
          </div>
          <ol className="event-list" aria-live="polite">
            {scene.events.map((event) => (
              <li
                key={`${scene.id}-${event.id}`}
                className={`event-${event.tone}`}
              >
                <span className="event-node" aria-hidden="true" />
                <div>
                  <time>{event.time}</time>
                  <strong>{event.title}</strong>
                  <p>{event.detail}</p>
                </div>
              </li>
            ))}
          </ol>
          <div className="rail-summary">
            <div>
              <Gauge aria-hidden="true" size={15} />
              <span>
                <small>Policy</small>
                <strong>two-key@1</strong>
              </span>
            </div>
            <div>
              <Users aria-hidden="true" size={15} />
              <span>
                <small>{isLiveHost ? "Live host queue" : "Replay queue"}</small>
                <strong>{displayHost.queue} waiting</strong>
              </span>
            </div>
          </div>
          <button
            className="replay-link"
            type="button"
            onClick={() => selectScene((sceneIndex + 1) % demoScenes.length)}
          >
            Next decision
            <ArrowRight aria-hidden="true" size={15} />
          </button>
        </aside>
      </section>

      <footer className="product-footnote">
        <p>
          <Radio aria-hidden="true" size={13} />
          {footerCopy[liveState]}
        </p>
        <p>
          Cooperative governor · never a security sandbox · never kills
          unrelated processes
        </p>
      </footer>
    </main>
  );
}

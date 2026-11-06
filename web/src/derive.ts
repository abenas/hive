// Tudo aqui é derivado da trilha de auditoria (eventos): o cronograma e as métricas
// usam a mesma fonte que a auditoria, então o que se vê é o que foi registrado.
import type { HiveEvent, MissionDetail } from "./api";

export interface Span {
  lane: string; // papel do agente, ou "human"
  taskId: string | null;
  start: number;
  end: number | null; // null = em andamento
  attempt: number;
  kind: "work" | "wait" | "failed";
  label: string;
}

export interface Tick { lane: string; at: number; ms: number; tokens: number; model: string }

const t = (iso: string) => new Date(iso).getTime();

export function timeline(m: MissionDetail, events: HiveEvent[]) {
  const spans: Span[] = [];
  const ticks: Tick[] = [];
  const open = new Map<string, Span>();
  const attempts = new Map<string, number>();
  let orchStart: number | null = null;
  let gateStart: { at: number; gate: string } | null = null;

  for (const e of events) {
    const at = t(e.ts);
    switch (e.type) {
      case "orchestrator.interpreting":
      case "orchestrator.planning":
        orchStart ??= at;
        break;
      case "plan.created":
        if (orchStart !== null) {
          spans.push({ lane: "orchestrator", taskId: null, start: orchStart, end: at, attempt: 1, kind: "work", label: "Briefing e plano" });
          orchStart = null;
        }
        break;
      case "gate.awaiting":
        gateStart = { at, gate: e.data.gate };
        break;
      case "gate.approved":
      case "gate.rejected":
        if (gateStart) {
          spans.push({ lane: "human", taskId: null, start: gateStart.at, end: at, attempt: 1, kind: "wait",
            label: gateStart.gate === "plan" ? "Revisão do plano" : "Go-live" });
          gateStart = null;
        }
        break;
      case "task.started": {
        const n = (attempts.get(e.task_id!) ?? 0) + 1;
        attempts.set(e.task_id!, n);
        const task = m.tasks.find((x) => x.id === e.task_id);
        const span: Span = { lane: e.actor, taskId: e.task_id, start: at, end: null, attempt: n, kind: "work",
          label: task?.title ?? e.actor };
        spans.push(span);
        open.set(e.task_id!, span);
        break;
      }
      case "task.completed":
      case "task.failed": {
        const span = open.get(e.task_id!);
        if (span) {
          span.end = at;
          if (e.type === "task.failed" || e.data.passed === false) span.kind = "failed";
          open.delete(e.task_id!);
        }
        break;
      }
      case "llm.call":
        ticks.push({ lane: e.actor, at, ms: e.data.latency_ms, tokens: e.data.output_tokens, model: e.data.model });
        break;
    }
  }
  if (orchStart !== null) spans.push({ lane: "orchestrator", taskId: null, start: orchStart, end: null, attempt: 1, kind: "work", label: "Briefing e plano" });
  if (gateStart) spans.push({ lane: "human", taskId: null, start: gateStart.at, end: null, attempt: 1, kind: "wait", label: "Aguardando você" });
  const start = events.length ? t(events[0].ts) : Date.now();
  const last = events.length ? t(events[events.length - 1].ts) : start;
  return { spans, ticks, start, last };
}

export interface Metrics {
  durationMs: number;
  agentMs: number; // tempo de trabalho dos agentes (sem espera humana)
  humanMs: number;
  calls: number;
  tokensIn: number;
  tokensOut: number;
  tokensPerSec: number;
  costUsd: number;
  simulated: boolean;
  reworks: number;
  models: string[];
  qaPassed: boolean | null;
  images: { llm: number; procedural: number };
}

export function metrics(m: MissionDetail, events: HiveEvent[]): Metrics {
  const { spans, start, last } = timeline(m, events);
  const end = ["completed", "failed", "rejected"].includes(m.status) ? last : Date.now();
  const humanMs = spans.filter((s) => s.kind === "wait").reduce((a, s) => a + ((s.end ?? end) - s.start), 0);
  const calls = events.filter((e) => e.type === "llm.call");
  const outTokens = calls.reduce((a, e) => a + e.data.output_tokens, 0);
  const genMs = calls.reduce((a, e) => a + e.data.latency_ms, 0);
  const illustrator = m.tasks.find((x) => x.agent === "illustrator")?.result?.evidence ?? [];
  const qa = m.tasks.find((x) => x.agent === "qa");
  return {
    durationMs: end - start,
    agentMs: end - start - humanMs,
    humanMs,
    calls: calls.length,
    tokensIn: calls.reduce((a, e) => a + e.data.input_tokens, 0),
    tokensOut: outTokens,
    tokensPerSec: genMs ? outTokens / (genMs / 1000) : 0,
    costUsd: m.cost_usd,
    simulated: calls.some((e) => e.data.simulated),
    reworks: events.filter((e) => e.type === "task.rework").length,
    models: [...new Set(calls.map((e) => `${e.data.provider}:${e.data.model}`))],
    qaPassed: qa?.status === "done" ? true : qa?.status === "failed" ? false : null,
    images: {
      llm: illustrator.filter((e) => e.passed === true).length,
      procedural: illustrator.filter((e) => e.passed === false).length,
    },
  };
}

export function fmtDuration(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ${String(s % 60).padStart(2, "0")} s`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}

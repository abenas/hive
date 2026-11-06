import { useEffect, useMemo, useState } from "react";
import { agentColor, HUMAN, type AgentCard, type HiveEvent, type MissionDetail } from "../api";
import { fmtDuration, timeline } from "../derive";
import { Face } from "./Panels";

const STEPS = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600].map((s) => s * 1000);

export function Gantt({ mission, events, agents, onSelect }: {
  mission: MissionDetail; events: HiveEvent[]; agents: Record<string, AgentCard>; onSelect: (taskId: string) => void;
}) {
  const live = !["completed", "failed", "rejected"].includes(mission.status);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [live]);

  const { spans, ticks, start, last } = useMemo(() => timeline(mission, events), [mission, events]);
  const end = live ? Math.max(now, last) : last;
  const total = Math.max(end - start, 1000);
  const pct = (at: number) => `${((at - start) / total) * 100}%`;
  const step = STEPS.find((s) => total / s <= 8) ?? 3600_000;
  const marks = Array.from({ length: Math.floor(total / step) + 1 }, (_, i) => i * step);

  // Ordem das linhas: orquestrador, agentes na ordem do plano, e por fim a pessoa.
  const lanes = ["orchestrator", ...[...new Set(mission.tasks.map((t) => t.agent))]];
  if (spans.some((s) => s.lane === "human")) lanes.push("human");

  if (!spans.length) {
    return <div className="graph-empty">O cronograma começa assim que o orquestrador assume a missão.</div>;
  }
  return (
    <div className="gantt" role="img" aria-label="Cronograma de trabalho de cada agente nesta missão">
      <div className="g-grid">
        {marks.map((ms) => <div key={ms} className="g-gridline" style={{ left: `calc(var(--label) + (100% - var(--label)) * ${ms / total})` }} />)}
        {lanes.map((lane) => {
          const isHuman = lane === "human";
          const a = isHuman ? HUMAN : agents[lane];
          const laneSpans = spans.filter((s) => s.lane === lane);
          const busy = laneSpans.filter((s) => s.kind !== "wait").reduce((acc, s) => acc + ((s.end ?? end) - s.start), 0);
          return (
            <div className="g-row" key={lane} style={{ ["--agent" as string]: agentColor(lane) }}>
              <div className="g-label">
                <Face role={lane} name={a?.name ?? lane} />
                <div className="who">{a?.name ?? lane}<small>{isHuman ? "tempo de espera" : fmtDuration(busy)}</small></div>
              </div>
              <div className="g-lane">
                {laneSpans.map((s, i) => {
                  const sEnd = s.end ?? end;
                  const cls = ["g-bar", s.kind === "wait" ? "wait" : "", s.kind === "failed" ? "failed" : "",
                    s.attempt > 1 ? "rework" : "", s.end === null ? "running" : ""].join(" ");
                  const width = ((sEnd - s.start) / total) * 100;
                  const text = `${s.label}${s.attempt > 1 ? ` (tentativa ${s.attempt})` : ""} — ${fmtDuration(sEnd - s.start)}`;
                  return (
                    <div key={i} className={cls} title={text} style={{ left: pct(s.start), width: `${width}%` }}
                      onClick={() => s.taskId && onSelect(s.taskId)}>
                      {width > 9 ? fmtDuration(sEnd - s.start) : ""}
                    </div>
                  );
                })}
                {ticks.filter((k) => k.lane === lane).map((k, i) => (
                  <div key={`t${i}`} className="g-tick" style={{ left: pct(k.at) }}
                    title={`${k.model}: ${k.tokens} tokens em ${fmtDuration(k.ms)}`} />
                ))}
              </div>
            </div>
          );
        })}
        {live && <div className="g-now" style={{ left: `calc(var(--label) + (100% - var(--label)) * ${(end - start) / total})` }} />}
        <div className="g-axis">
          {marks.map((ms) => <span key={ms} style={{ left: `${(ms / total) * 100}%` }}>{fmtDuration(ms)}</span>)}
        </div>
      </div>
    </div>
  );
}
